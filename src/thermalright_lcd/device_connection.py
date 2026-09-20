from __future__ import annotations

import json,threading,time
from collections import deque
import sys
from pathlib import Path

from .encoder import EncodedFrame, validate_5302, validate_5408
from .live_state import (RealUsbTransport, SafetyError, TimeoutPolicy, TransportError,
                         expected_identity, load_allowlist, load_sequence,
                         validate_identity, validate_ready)
from .capabilities import capabilities
from .reviewed_devices import REVIEWED_DEVICE_DEFINITIONS, reviewed_device_definition, reviewed_lifecycle


class DisabledHardwareSender:
    """GUI sender used while the explicit generated-media gate is disabled."""

    enabled = False

    def __init__(self, reason: str = "Generated-media hardware control is locked"):
        self.reason = reason

    def __call__(self, frame: EncodedFrame) -> int:
        raise SafetyError(self.reason)

    def close(self) -> None:
        return None


class GeneratedFrameConnection:
    """One validated long-lived device session for arbitrary encoded frames.

    Initialization and readiness are capture-derived. Frames are independently
    validated before every send; PID 5408 additionally requires its exact ACK.
    There are no retries and no per-frame PnP discovery.
    """

    enabled = True

    def __init__(self, target: dict, lifecycle: dict, transport, timeouts: TimeoutPolicy = TimeoutPolicy(), conflict_supplier=None, trace_hook=None):
        self.target = target
        self.identity = expected_identity(target)
        self.lifecycle = lifecycle
        self.transport = transport
        self.timeouts = timeouts
        self.conflict_supplier=conflict_supplier
        self._opened = False
        self._lock = threading.RLock()
        self.frames = 0
        self.acks = 0
        self.frame_metrics=deque(maxlen=2048)
        self.trace_hook=trace_hook

    def _trace(self,event,**fields):
        hook=self.trace_hook
        if hook is not None:
            try:hook(event,device_id=self.identity.vid_pid,**fields)
            except Exception:pass

    def open(self) -> None:
        with self._lock:
            if self._opened:
                return
            self._trace("device_open_begin")
            if self.conflict_supplier is None:
                from .conflicts import thermalright_processes
                conflicts=thermalright_processes()
            else:conflicts=self.conflict_supplier()
            if conflicts:
                raise SafetyError("Thermalright Control Center or LCD helper is holding a display")
            actual = self.transport.discover()
            self._trace("device_discovered",device_path=actual.device_path,interface=actual.interface,out_endpoint=actual.out_endpoint,in_endpoint=actual.in_endpoint,container_id=actual.container_id)
            validate_identity(actual, self.identity)
            self.transport.revalidate(self.identity)
            self._trace("device_identity_validated")
            self.transport.open(self.timeouts.open_ms)
            self._trace("device_handle_opened")
            try:
                n = self.transport.write(self.identity.out_endpoint, self.lifecycle["init"], self.timeouts.transfer_ms)
                self._trace("initialization_write_complete",bytes=n)
                if n != len(self.lifecycle["init"]):
                    raise TransportError("short initialization write")
                ready = self.transport.read(self.identity.in_endpoint, len(self.lifecycle["ready"]), self.timeouts.readiness_ms)
                validate_ready(self.identity.vid_pid, ready, self.lifecycle["ready"], validation=self.lifecycle.get("ready_validation", "exact"))
                self._trace("readiness_validated",bytes=len(ready))
                if self.transport.pending_input():
                    raise TransportError("unexpected response before generated frame")
                self._opened = True
                self._trace("device_open_complete")
            except Exception:
                self._trace("device_open_error")
                try:
                    self.transport.close(self.timeouts.close_ms)
                finally:
                    raise

    def __call__(self, frame: EncodedFrame) -> int:
        with self._lock:
            if frame.vid_pid != self.identity.vid_pid:
                raise SafetyError("encoded frame targets the wrong device")
            validation = validate_5408(frame) if frame.vid_pid == "0416:5408" else validate_5302(frame)
            if not validation["valid"] or not validation.get("padding_zero", False):
                raise SafetyError("generated frame failed protocol validation")
            try:
                self.open()
                frame_started=time.perf_counter();total = 0;write_durations=[];self._trace("frame_write_begin",frame=self.frames+1,reports=len(frame.writes))
                for payload in frame.writes:
                    write_started=time.perf_counter()
                    n = self.transport.write(self.identity.out_endpoint, payload, self.timeouts.transfer_ms)
                    write_durations.append((time.perf_counter()-write_started)*1000)
                    if n != len(payload):
                        raise TransportError("short generated-frame write")
                    total += n
                if capabilities(frame.vid_pid).frame_ack_required:
                    expected = self.lifecycle["ack"]
                    ack_started=time.perf_counter()
                    ack = self.transport.read(self.identity.in_endpoint, len(expected), self.timeouts.frame_ack_ms)
                    ack_ms=(time.perf_counter()-ack_started)*1000
                    if ack != expected:
                        raise SafetyError("unexpected generated-frame ACK")
                    if self.transport.pending_input():
                        raise TransportError("duplicate/extra generated-frame response")
                    self.acks += 1
                    self._trace("frame_ack_validated",frame=self.frames+1,bytes=len(ack),ack_ms=ack_ms)
                elif self.transport.pending_input():
                    raise TransportError("unexpected response after PID 5302 generated frame")
                else:ack_ms=0.0
                self.frames += 1
                self.frame_metrics.append({"frame":self.frames,"bytes":total,"reports":len(frame.writes),"write_ms":sum(write_durations),"ack_ms":ack_ms,"total_ms":(time.perf_counter()-frame_started)*1000,"max_write_ms":max(write_durations,default=0.0)})
                self._trace("frame_write_complete",frame=self.frames,bytes=total,reports=len(frame.writes),write_ms=sum(write_durations),ack_ms=ack_ms,total_ms=(time.perf_counter()-frame_started)*1000)
                return total
            except Exception:
                # Fail closed and make the next user-requested reconnect start
                # from a fresh validated handle. Never retry automatically.
                try:self.transport.close(self.timeouts.close_ms)
                except Exception:pass
                self._opened=False
                self._trace("frame_write_error")
                raise

    def close(self) -> None:
        with self._lock:
            if not self._opened:
                return
            self._trace("device_close_begin")
            try:
                self.transport.close(self.timeouts.close_ms)
            finally:
                self._opened = False
                self.transport.revalidate(self.identity)
                self._trace("device_close_complete")


def application_root() -> Path:
    """Resolve bundled data correctly in source and PyInstaller builds."""
    if getattr(sys,"frozen",False) and hasattr(sys,"_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _legacy_gui_configuration(root: Path, device_id: str):
    """Load an existing exact-machine authorization when it is complete."""
    path = root / "config/device-allowlist.json"
    if not path.is_file(): return None
    try:
        allow = load_allowlist(path)
        target = next((item for item in allow["devices"] if item.get("vid_pid") == device_id), None)
        if target is None:return None
        if not target.get("allowGuiGeneratedMedia", False):return (None, None, "local-deny")
        tx = (root / "analysis/pid5408-new-session-first-frame.json" if device_id == "0416:5408"
              else root / "analysis/pid5302-same-session-first-frame.json")
        lifecycle = load_sequence(root / "analysis/session-report.json", tx, device_id, 1, require_same_session=True)
        return target, lifecycle, "legacy-exact"
    except (OSError, KeyError, ValueError, json.JSONDecodeError):return None


def _public_gui_configuration(device_id: str):
    target = reviewed_device_definition(device_id)
    if target.get("access_method") == "windows-hid":
        from .windows_hid import materialize_reviewed_hid_target
        target = materialize_reviewed_hid_target(target)
    else:
        from .windows_usb import materialize_reviewed_winusb_target
        target = materialize_reviewed_winusb_target(target)
    return target, reviewed_lifecycle(device_id), "public-reviewed"


def build_gui_sender(device_id: str, root: Path | None = None):
    """Build one validated sender for a reviewed public device definition."""
    root = root or application_root()
    if device_id not in REVIEWED_DEVICE_DEFINITIONS:return DisabledHardwareSender(f"Unsupported device definition: {device_id}")
    legacy = _legacy_gui_configuration(root, device_id)
    if legacy and legacy[2] == "local-deny":return DisabledHardwareSender("Hardware control disabled by local configuration")
    try:target, lifecycle, _source = legacy or _public_gui_configuration(device_id)
    except Exception as exc:return DisabledHardwareSender(f"Reviewed device unavailable or incompatible: {exc}")
    seconds = int(target.get("guiSessionMaxSeconds", 3600))
    max_frame_writes = int(target.get("guiMaxFrameWrites", 4096))
    fps = 6 if device_id == "0416:5408" else 12
    max_writes = 1 + seconds * fps * max_frame_writes
    max_bytes = max_writes * int(target["host_payload_size"])
    if target.get("access_method") == "windows-hid":
        from .windows_hid import CtypesWindowsHidApi, RealHidTransport, discover_hid_identity
        transport = RealHidTransport(target, lambda: discover_hid_identity(target), CtypesWindowsHidApi(), max_writes, max_bytes)
    else:
        from .windows_usb import CtypesWinUsbApi, discover_identity
        transport = RealUsbTransport(target, lambda: discover_identity(target), CtypesWinUsbApi(), max_writes, max_bytes)
    return GeneratedFrameConnection(target, lifecycle, transport)
