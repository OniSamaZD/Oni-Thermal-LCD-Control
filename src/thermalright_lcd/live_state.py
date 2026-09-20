from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .replay import SafetyError, load_allowlist


class State(str, Enum):
    DISCONNECTED="DISCONNECTED"; DISCOVERED="DISCOVERED"; VALIDATED="VALIDATED"
    OPENING="OPENING"; WAITING_FOR_READY="WAITING_FOR_READY"; READY="READY"
    SENDING_FRAME="SENDING_FRAME"; WAITING_FOR_FRAME_ACK="WAITING_FOR_FRAME_ACK"
    FRAME_ACCEPTED="FRAME_ACCEPTED"; CLOSING="CLOSING"; CLOSED="CLOSED"
    HOLDING="HOLDING"
    ERROR="ERROR"; ABORTED="ABORTED"


@dataclass(frozen=True)
class TimeoutPolicy:
    open_ms: int = 2000
    readiness_ms: int = 1000
    transfer_ms: int = 1000
    frame_ack_ms: int = 1000
    close_ms: int = 2000


@dataclass(frozen=True)
class DeviceIdentity:
    vid_pid: str
    stable_instance_id: str
    container_id: str
    interface: int
    out_endpoint: str
    in_endpoint: str | None
    transfer_type: str
    driver: str = "WINUSB"
    generation: str = "stable"
    device_path: str | None = None
    maximum_transfer_size: int = 0


class TransportError(RuntimeError): pass
class TransportTimeout(TransportError): pass
class TransportStall(TransportError): pass
class DeviceDisconnected(TransportError): pass
class DeviceReenumerated(TransportError): pass


class UsbTransport(ABC):
    @abstractmethod
    def discover(self) -> DeviceIdentity: ...
    @abstractmethod
    def open(self, timeout_ms: int) -> None: ...
    @abstractmethod
    def write(self, endpoint: str, payload: bytes, timeout_ms: int) -> int: ...
    @abstractmethod
    def read(self, endpoint: str, length: int, timeout_ms: int) -> bytes: ...
    @abstractmethod
    def pending_input(self) -> bool: ...
    @abstractmethod
    def revalidate(self, expected: DeviceIdentity) -> None: ...
    @abstractmethod
    def close(self, timeout_ms: int) -> None: ...


class RealUsbTransport(UsbTransport):
    """WinUSB transport with discovery and API boundaries injectable for offline tests."""
    def __init__(self, target: dict, identity_supplier, api, write_budget_count: int, write_budget_bytes: int):
        self.target=target; self.identity_supplier=identity_supplier; self.api=api
        self.identity=None; self.file_handle=None; self.usb_handle=None; self._opened_generation=None
        self.write_budget_count=write_budget_count; self.write_budget_bytes=write_budget_bytes
        self.write_count=0; self.write_bytes=0
        self.hardware_ever_opened=False; self.hardware_write_calls=0
        self.pipe_reset_count=0
    def discover(self):
        d=self.identity_supplier()
        if not d.device_path: raise SafetyError("no confirmed WinUSB device interface path")
        self.identity=d; return d
    def open(self,timeout_ms):
        if not self.identity: raise SafetyError("discover/validate before open")
        try:
            self.file_handle=self.api.create_file(self.identity.device_path,timeout_ms)
            self.hardware_ever_opened=True
            self.usb_handle=self.api.winusb_initialize(self.file_handle)
            expected_type={"bulk":2,"interrupt":3}[self.target["transfer_type"]]
            for ep in (int(self.target["endpoint"],16),int(self.target["response_endpoint"],16)):
                pipe=self.api.query_pipe(self.usb_handle,self.target["interface"],ep)
                if pipe["endpoint"]!=ep or pipe["type"]!=expected_type: raise SafetyError("endpoint/transfer type mismatch")
                if pipe["maximum_packet_size"]<=0: raise SafetyError("invalid maximum packet size")
                self.api.set_timeout(self.usb_handle,ep,timeout_ms)
                # A prior canceled/stalled WinUSB transfer can leave the pipe
                # halted across handle reopen. Reset is a documented host-side
                # recovery operation, not a vendor/device protocol command.
                reset=getattr(self.api,"reset_pipe",None)
                if reset is not None:reset(self.usb_handle,ep);self.pipe_reset_count+=1
            self._opened_generation=self.identity.generation
        except Exception:
            self.close(timeout_ms); raise
    def write(self,endpoint,payload,timeout_ms):
        if not self.usb_handle: raise DeviceDisconnected("USB handle is not open")
        if self.write_count+1>self.write_budget_count or self.write_bytes+len(payload)>self.write_budget_bytes:
            raise SafetyError("physical first-session write budget exceeded")
        self.api.set_timeout(self.usb_handle,int(endpoint,16),timeout_ms)
        self.hardware_write_calls+=1
        n=self.api.write_pipe(self.usb_handle,int(endpoint,16),payload)
        if n!=len(payload): raise TransportError("short write")
        self.write_count+=1; self.write_bytes+=n
        return n
    def read(self,endpoint,length,timeout_ms):
        if not self.usb_handle: raise DeviceDisconnected("USB handle is not open")
        self.api.set_timeout(self.usb_handle,int(endpoint,16),timeout_ms)
        data=self.api.read_pipe(self.usb_handle,int(endpoint,16),length)
        if len(data)!=length: raise TransportError("short read")
        return data
    def pending_input(self):
        if not self.usb_handle: return False
        ep=int(self.target["response_endpoint"],16)
        self.api.set_timeout(self.usb_handle,ep,1)
        try: return bool(self.api.read_pipe(self.usb_handle,ep,self.target["open_response"]["payload_size"]))
        except TransportTimeout: return False
    def revalidate(self,expected):
        current=self.identity_supplier(); validate_identity(current,expected)
        if self._opened_generation is not None and current.generation!=self._opened_generation: raise DeviceReenumerated("device re-enumerated")
        if self.identity and current.device_path!=self.identity.device_path: raise DeviceReenumerated("device path changed")
    def close(self,timeout_ms):
        error=None
        try:
            if self.usb_handle:
                for ep in (int(self.target["endpoint"],16),int(self.target["response_endpoint"],16)):
                    try: self.api.abort_pipe(self.usb_handle,ep)
                    except Exception as e: error=error or e
                self.api.free(self.usb_handle)
        finally:
            self.usb_handle=None
            try: self.api.close_handle(self.file_handle)
            finally: self.file_handle=None
        if error: raise error


class DryRunUsbTransport(UsbTransport):
    def __init__(self, identity: DeviceIdentity, responses: list[bytes], faults: dict[str, Any] | None = None):
        self.identity, self.responses, self.faults = identity, list(responses), faults or {}
        self.writes: list[tuple[str, int]] = []; self.opened = False; self.closed = False; self.pending_checks = 0

    def _fault(self, name: str, index: int | None = None):
        value = self.faults.get(name)
        if value is True or (index is not None and value == index):
            exc = {"timeout": TransportTimeout, "stall": TransportStall,
                   "disconnect": DeviceDisconnected, "reenumerate": DeviceReenumerated}.get(name, TransportError)
            raise exc(name)

    def discover(self): return self.identity
    def open(self, timeout_ms): self._fault("timeout"); self.opened = True
    def write(self, endpoint, payload, timeout_ms):
        index=len(self.writes); self._fault("disconnect", index); self._fault("stall", index); self._fault("reenumerate", index)
        self.writes.append((endpoint, len(payload)))
        if self.faults.get("short_write") == index: return len(payload)-1
        return len(payload)
    def read(self, endpoint, length, timeout_ms):
        self._fault("read_timeout"); self._fault("disconnect_read")
        if not self.responses: raise TransportTimeout("missing response")
        data=self.responses.pop(0)
        if self.faults.get("short_read"): return data[:-1]
        return data
    def pending_input(self):
        current=self.pending_checks; self.pending_checks += 1
        return self.faults.get("pending_at") == current
    def revalidate(self, expected):
        self._fault("reenumerate_revalidate")
        if self.identity.generation != expected.generation: raise DeviceReenumerated("generation changed")
    def close(self, timeout_ms): self._fault("close_timeout"); self.closed=True; self.opened=False


def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


def load_sequence(session_file: Path, transaction_file: Path, vid_pid: str, index: int = 1,
                  require_same_session: bool = False) -> dict:
    session=json.loads(session_file.read_text(encoding="utf-8")); txr=json.loads(transaction_file.read_text(encoding="utf-8"))
    s=session["devices"][vid_pid]; tx=next(x for x in txr["devices"][vid_pid]["transactions"] if x["index"] == index)
    opened=next(x for x in s["events"] if x["category"] == "session-open")
    ready=next(x for x in s["events"] if x["category"] == "device-ready")
    if require_same_session and tx["start_timestamp"] < ready["timestamp"]:
        raise SafetyError("frame transaction predates the selected session readiness; cross-session mode mixing rejected")
    import base64
    stem=transaction_file.stem
    seq_id=f"{vid_pid}/capture-transaction-{index}" if stem=="transactions" else f"{vid_pid}/{stem}-transaction-{index}"
    return {"id":seq_id, "source_kind":tx.get("source_kind",txr.get("source_kind","captured")), "init": bytes.fromhex(opened["payload_hex"]),
            "ready": bytes.fromhex(ready["payload_hex"]),
            "frame": [base64.b64decode(x["payload_b64"]) for x in tx["payload_packets"]],
            "ack": bytes.fromhex(tx["expected_response"]["payload_hex"]) if tx.get("expected_response") else None,
            "jpeg_sha256":tx["jpeg_sha256"],"jpeg_bytes":tx["jpeg_bytes"],
            "dimensions":(1920,462) if vid_pid=="0416:5408" else (1280,480),
            "ready_to_frame_delay_ms":max(0.0,(tx["start_timestamp"]-ready["timestamp"])*1000) if require_same_session else 0.0}


def expected_identity(target: dict) -> DeviceIdentity:
    return DeviceIdentity(target["vid_pid"], target["stable_instance_id"], target["container_id"], target["interface"],
                          target["endpoint"], target.get("response_endpoint"), target["transfer_type"],
                          driver=target.get("driver","WINUSB"), device_path=target.get("confirmed_device_path"),
                          maximum_transfer_size=target["host_payload_size"])


def validate_identity(actual: DeviceIdentity, expected: DeviceIdentity) -> None:
    for field in ("vid_pid","stable_instance_id","container_id","interface","out_endpoint","in_endpoint","transfer_type"):
        if str(getattr(actual, field)).lower() != str(getattr(expected, field)).lower(): raise SafetyError(f"{field} mismatch")
    if actual.driver.upper() != str(expected.driver or "WINUSB").upper(): raise SafetyError("driver compatibility mismatch")
    if expected.device_path and str(actual.device_path).lower() != expected.device_path.lower(): raise SafetyError("device path mismatch")
    if actual.maximum_transfer_size and actual.maximum_transfer_size < expected.maximum_transfer_size: raise SafetyError("maximum transfer size mismatch")


def validate_ready(vid_pid: str, data: bytes, exact: bytes, *, validation: str = "exact") -> dict:
    if validation not in {"exact", "reviewed-fields"}: raise SafetyError("unknown readiness validation policy")
    if validation == "exact" and data != exact: raise SafetyError("unexpected readiness response payload")
    if vid_pid == "0416:5408":
        if len(data)!=512 or data[:2]!=b"\x03\xff": raise SafetyError("malformed 5408 readiness response")
        fields={"physical_width":int.from_bytes(data[24:26],"little"), "physical_height":int.from_bytes(data[28:30],"little"), "excluded_rows":data[44]}
        if fields != {"physical_width":1920,"physical_height":480,"excluded_rows":18}: raise SafetyError("5408 mandatory mode fields mismatch")
        return fields
    if len(data)!=36 or data[:8]!=bytes.fromhex("dadbdcdd01800000") or data[20:27]!=b"AP4S122":
        raise SafetyError("5302 identity/readiness mismatch")
    return {"identity_ascii":"AP4S122", "command":0x8001}


class LiveReplayMachine:
    def __init__(self, target: dict, sequence: dict, transport: UsbTransport, timeouts: TimeoutPolicy = TimeoutPolicy(),
                 hold_open_ms: int = 0, sleeper=time.sleep):
        if not 0 <= hold_open_ms <= 30000: raise ValueError("hold_open_ms must be between 0 and 30000")
        self.target, self.sequence, self.transport, self.timeouts = target, sequence, transport, timeouts
        self.hold_open_ms=hold_open_ms;self.sleeper=sleeper
        self.state=State.DISCONNECTED; self.events=[]; self._tick=0; self.identity=expected_identity(target)

    def log(self, state: State, **details):
        old=self.state; self.state=state; self._tick += 1
        self.events.append({"timestamp_ms":self._tick, "from":old.value, "to":state.value,
                            "device_identity":self.identity.stable_instance_id, "endpoint":None,
                            "transfer_length":None, "expected_response_class":None,
                            "actual_response_class":None, "error":None, **details})

    def abort(self, reason: str, error: bool = False):
        self.log(State.ERROR if error else State.ABORTED, error=reason)
        try: self.transport.close(self.timeouts.close_ms)
        except Exception: pass

    def run(self) -> dict:
        try:
            actual=self.transport.discover(); self.log(State.DISCOVERED)
            validate_identity(actual,self.identity); self.log(State.VALIDATED)
            self.transport.revalidate(self.identity); self.log(State.OPENING)
            self.transport.open(self.timeouts.open_ms)
            n=self.transport.write(self.identity.out_endpoint,self.sequence["init"],self.timeouts.transfer_ms)
            if n!=len(self.sequence["init"]): raise TransportError("short initialization write")
            self.log(State.WAITING_FOR_READY,endpoint=self.identity.out_endpoint,transfer_length=n,expected_response_class="DEVICE_READY")
            ready=self.transport.read(self.identity.in_endpoint,len(self.sequence["ready"]),self.timeouts.readiness_ms)
            ready_clock=time.monotonic()
            fields=validate_ready(self.identity.vid_pid,ready,self.sequence["ready"])
            self.log(State.READY,endpoint=self.identity.in_endpoint,transfer_length=len(ready),actual_response_class="DEVICE_READY",parsed_fields=fields)
            if self.transport.pending_input(): raise TransportError("duplicate/extra response before frame")
            self.transport.revalidate(self.identity)
            delay=self.sequence.get("ready_to_frame_delay_ms",0)/1000
            remaining=delay-(time.monotonic()-ready_clock)
            if remaining>0: time.sleep(remaining)
            self.log(State.SENDING_FRAME,ready_to_frame_delay_ms=self.sequence.get("ready_to_frame_delay_ms",0))
            for payload in self.sequence["frame"]:
                n=self.transport.write(self.identity.out_endpoint,payload,self.timeouts.transfer_ms)
                if n!=len(payload): raise TransportError("short frame write")
            if self.identity.vid_pid == "0416:5408":
                self.log(State.WAITING_FOR_FRAME_ACK,endpoint=self.identity.in_endpoint,expected_response_class="FRAME_ACK")
                ack=self.transport.read(self.identity.in_endpoint,len(self.sequence["ack"]),self.timeouts.frame_ack_ms)
                if ack!=self.sequence["ack"]: raise SafetyError("unexpected frame ACK")
                self.log(State.FRAME_ACCEPTED,endpoint=self.identity.in_endpoint,transfer_length=len(ack),actual_response_class="FRAME_ACK")
                if self.transport.pending_input(): raise TransportError("duplicate/extra frame response")
            else:
                if self.transport.pending_input(): raise TransportError("unexpected response after 5302 frame")
                self.log(State.FRAME_ACCEPTED,actual_response_class="NO_ACK_EXPECTED")
            if self.hold_open_ms:
                # Deliberately hold the validated handle with zero additional writes.
                # This isolates session persistence from refresh/keepalive behavior.
                self.log(State.HOLDING,hold_open_ms=self.hold_open_ms,additional_writes=0)
                self.sleeper(self.hold_open_ms/1000)
                self.transport.revalidate(self.identity)
            self.log(State.CLOSING); self.transport.close(self.timeouts.close_ms); self.log(State.CLOSED)
        except SafetyError as e: self.abort(str(e))
        except (TransportError,OSError) as e: self.abort(str(e), True)
        return {"sequence_id":self.sequence["id"],"final_state":self.state.value,"success":self.state==State.CLOSED,
                "writes":getattr(self.transport,"write_count",len(getattr(self.transport,"writes",[]))),
                "written_bytes":getattr(self.transport,"write_bytes",sum(x[1] for x in getattr(self.transport,"writes",[]))),
                "events":self.events,
                "usb_hardware_opened":bool(getattr(self.transport,"hardware_ever_opened",False)),
                "usb_hardware_written":bool(getattr(self.transport,"hardware_write_calls",0))}


class PersistentReplayMachine(LiveReplayMachine):
    """Bounded repeated captured-frame proof. It has no authorization or CLI path."""
    def __init__(self,target,sequence,transport,frame_count,interval_seconds,timeouts=TimeoutPolicy(),clock=time.monotonic,sleeper=time.sleep,duration_seconds:float|None=None,start_gate=None,wall_clock=time.time):
        if frame_count<1:raise ValueError("frame_count must be positive")
        if not 0<interval_seconds<=1:raise ValueError("invalid persistence interval")
        if duration_seconds is not None and duration_seconds<=0:raise ValueError("duration must be positive")
        super().__init__(target,sequence,transport,timeouts,sleeper=sleeper)
        self.frame_count=frame_count;self.interval_seconds=interval_seconds;self.clock=clock;self.duration_seconds=duration_seconds;self.start_gate=start_gate;self.wall_clock=wall_clock
    def run(self):
        starts=[];wall_starts=[];durations=[];ack_latencies=[];accepted=0;overruns=0;data_started_wall=None;data_ended_wall=None
        try:
            actual=self.transport.discover();self.log(State.DISCOVERED);validate_identity(actual,self.identity);self.log(State.VALIDATED)
            self.transport.revalidate(self.identity);self.log(State.OPENING);self.transport.open(self.timeouts.open_ms)
            n=self.transport.write(self.identity.out_endpoint,self.sequence["init"],self.timeouts.transfer_ms)
            if n!=len(self.sequence["init"]):raise TransportError("short initialization write")
            self.log(State.WAITING_FOR_READY,expected_response_class="DEVICE_READY")
            ready=self.transport.read(self.identity.in_endpoint,len(self.sequence["ready"]),self.timeouts.readiness_ms)
            validate_ready(self.identity.vid_pid,ready,self.sequence["ready"]);self.log(State.READY,actual_response_class="DEVICE_READY")
            if self.start_gate:
                try:self.start_gate()
                except Exception as e:raise TransportError(f"dual start gate failed: {e}")
            data_started_wall=self.wall_clock()
            session_started=self.clock();deadline=session_started
            for index in range(self.frame_count):
                if self.duration_seconds is not None and self.clock()-session_started>=self.duration_seconds:break
                remaining=deadline-self.clock()
                if remaining>0:self.sleeper(remaining)
                started=self.clock()
                if self.duration_seconds is not None and started-session_started>=self.duration_seconds:break
                starts.append(started);wall_starts.append(self.wall_clock())
                self.log(State.SENDING_FRAME,frame_index=index+1,frame_count=self.frame_count)
                for payload in self.sequence["frame"]:
                    n=self.transport.write(self.identity.out_endpoint,payload,self.timeouts.transfer_ms)
                    if n!=len(payload):raise TransportError("short frame write")
                sent=self.clock();durations.append(sent-started)
                if self.identity.vid_pid=="0416:5408":
                    self.log(State.WAITING_FOR_FRAME_ACK,frame_index=index+1,expected_response_class="FRAME_ACK")
                    ack=self.transport.read(self.identity.in_endpoint,len(self.sequence["ack"]),self.timeouts.frame_ack_ms)
                    ack_latencies.append(self.clock()-sent)
                    if ack!=self.sequence["ack"]:raise SafetyError("unexpected frame ACK")
                    if self.transport.pending_input():raise TransportError("duplicate/extra frame response")
                elif self.transport.pending_input():raise TransportError("unexpected response after 5302 frame")
                self.log(State.FRAME_ACCEPTED,frame_index=index+1,actual_response_class="FRAME_ACK" if self.sequence["ack"] else "NO_ACK_EXPECTED")
                accepted+=1
                deadline+=self.interval_seconds
                # Never accumulate scheduled work when a frame takes longer than
                # the requested interval. The latest cached frame is sent next.
                now=self.clock();late=now-deadline
                if late>0:
                    # Sub-millisecond timer jitter is not a meaningful overrun.
                    # Reset to now so no scheduling debt or catch-up burst forms.
                    if late>=.001:overruns+=1
                    deadline=now
            if self.duration_seconds is not None:
                remaining=self.duration_seconds-(self.clock()-session_started)
                if remaining>0:self.sleeper(remaining)
            data_ended_wall=self.wall_clock()
            # Release the handle at the bounded data-phase deadline. Full
            # PnP/HID rediscovery costs ~1.62 s, so it runs after close and can
            # still classify a generation/path change without extending writes.
            self.log(State.CLOSING);self.transport.close(self.timeouts.close_ms)
            self.transport.revalidate(self.identity);self.log(State.CLOSED)
        except SafetyError as e:self.abort(str(e))
        except (TransportError,OSError) as e:self.abort(str(e),True)
        elapsed=(starts[-1]-starts[0]) if len(starts)>1 else 0
        frame_bytes=sum(map(len,self.sequence["frame"]));completed=len(durations)
        return {"sequence_id":self.sequence["id"],"final_state":self.state.value,"success":self.state==State.CLOSED,
            "requested_frames":self.frame_count,"transmitted_frames":completed,"accepted_frames":accepted,"completed_frames":accepted,"expected_ack_count":self.frame_count if self.sequence["ack"] else 0,
            "actual_fps":((completed-1)/elapsed if elapsed>0 else 0),"mean_send_ms":sum(durations)*1000/completed if completed else 0,
            "mean_ack_latency_ms":sum(ack_latencies)*1000/len(ack_latencies) if ack_latencies else 0,
            "ack_count":len(ack_latencies),"scheduler_overruns":overruns,"dropped_or_deferred_frames":self.frame_count-accepted,
            "data_phase_started_epoch":data_started_wall,"data_phase_ended_epoch":data_ended_wall,
            "first_frame_epoch":wall_starts[0] if wall_starts else None,"last_frame_epoch":wall_starts[-1] if wall_starts else None,
            "estimated_usb_bytes_per_second":(completed*frame_bytes/(durations[-1]+elapsed) if completed and durations and durations[-1]+elapsed>0 else 0),
            "writes":getattr(self.transport,"write_count",len(getattr(self.transport,"writes",[]))),
            "written_bytes":getattr(self.transport,"write_bytes",sum(x[1] for x in getattr(self.transport,"writes",[]))),
            "events":self.events,"usb_hardware_opened":bool(getattr(self.transport,"hardware_ever_opened",False)),
            "usb_hardware_written":bool(getattr(self.transport,"hardware_write_calls",0))}


def preflight(allowlist_file: Path, session_file: Path, transaction_file: Path, vid_pid: str, inventory_file: Path) -> dict:
    allow=load_allowlist(allowlist_file); target=next(x for x in allow["devices"] if x["vid_pid"]==vid_pid)
    seq=load_sequence(session_file,transaction_file,vid_pid)
    inventory=json.loads(inventory_file.read_text(encoding="utf-8-sig"))
    candidates=[x for x in inventory if x.get("instance_id","").upper()==target["stable_instance_id"].upper()]
    identity_ok=len(candidates)==1 and candidates[0].get("status")=="OK" and candidates[0].get("container_id","").upper()==target["container_id"].upper()
    winusb=any(x.get("container_id","").upper()==target["container_id"].upper() and x.get("service","").upper()=="WINUSB"
               and f"MI_{target['interface']:02d}" in x.get("instance_id","").upper() for x in inventory)
    # PID 5408 is single-interface and its stable node is itself WINUSB.
    if target["vid_pid"] == "0416:5408": winusb=bool(candidates and candidates[0].get("service","").upper()=="WINUSB")
    present=identity_ok and winusb
    return {"target_identity":target["stable_instance_id"],"pid":vid_pid.split(":")[1],"interface":target["interface"],
            "out_endpoint":target["endpoint"],"in_endpoint":target.get("response_endpoint"),"transfer_type":target["transfer_type"],
            "driver":target.get("driver","WINUSB"),"access_method":target.get("access_method","winusb"),
            "expected_init_hash":_sha(seq["init"]),"expected_readiness_hash":_sha(seq["ready"]),
            "expected_frame_hash":_sha(b"".join(seq["frame"])),"expected_ack_hash":_sha(seq["ack"]) if seq["ack"] else None,
            "timeout_policy":TimeoutPolicy().__dict__,"live_preconditions_pass":present,
            "live_send_authorized":target["live_send_authorized"],"endpoints_opened":False,"usb_written":False}


def live_preflight(allowlist_file: Path, session_file: Path, transaction_file: Path,
                   stable_id: str, sequence_id: str, inventory_file: Path, transaction_index:int=1) -> dict:
    allow=load_allowlist(allowlist_file)
    target=next((x for x in allow["devices"] if x["stable_instance_id"].lower()==stable_id.lower()),None)
    checks={"allowlisted_identity":bool(target)}
    if not target:
        return {"checks":checks,"pass":False,"endpoints_opened":False,"usb_written":False}
    vid_pid=target["vid_pid"]; seq=load_sequence(session_file,transaction_file,vid_pid,transaction_index,require_same_session=True)
    base=preflight(allowlist_file,session_file,transaction_file,vid_pid,inventory_file)
    inventory=json.loads(inventory_file.read_text(encoding="utf-8-sig"))
    node=next((x for x in inventory if x.get("instance_id","").lower()==stable_id.lower()),{})
    try:
        if target.get("access_method")=="windows-hid":
            from .windows_hid import discover_hid_identity
            fresh=discover_hid_identity(target);path_ok=fresh.device_path.lower()==target["confirmed_device_path"].lower()
        else:
            from .windows_usb import discover_identity, device_path_registered
            fresh=discover_identity(target);path_ok=device_path_registered(target)
        fresh_ok=True
    except Exception:
        fresh=None; fresh_ok=False
    vid,pid=vid_pid.split(":"); hardware=" ".join(node.get("hardware_ids",[])).lower()
    checks.update({"vid_pid":f"vid_{vid}&pid_{pid}" in hardware,
                   "container_id":fresh_ok and fresh.container_id.lower()==target["container_id"].lower(),
                   "stable_identity":fresh_ok and fresh.stable_instance_id.lower()==stable_id.lower(),
                   "driver_service":fresh_ok and fresh.driver.upper()==target.get("driver","WINUSB").upper(),
                   "device_path":path_ok if fresh_ok else False,
                   "interface":target["interface"] in (0,1), "out_endpoint":target["endpoint"] in ("0x09","0x02"),
                   "in_endpoint":target["response_endpoint"] in ("0x81","0x83"),
                   "transfer_type":target["transfer_type"] in ("bulk","interrupt"),
                   "maximum_transfer_size":target["host_payload_size"] in (4096,512),
                   "known_good_sequence":seq["id"]==sequence_id,
                   "allowLiveReplay":target.get("allowLiveReplay") is True})
    return {**base,"sequence_id":seq["id"],"checks":checks,"pass":all(checks.values()),
            "endpoints_opened":False,"usb_written":False}


def require_live_authorization(target: dict, supplied_stable_id: str | None, supplied_sequence: str | None,
                               expected_sequence: str, send: bool, acknowledged: bool,
                               confirmation: str | None, expected_phrase: str = "SEND EXACT CAPTURED FRAME") -> None:
    failures=[]
    if not send: failures.append("--send missing")
    if not acknowledged: failures.append("--i-understand-live-usb missing")
    if supplied_stable_id != target["stable_instance_id"]: failures.append("exact stable device ID mismatch")
    if supplied_sequence != expected_sequence: failures.append("exact known-good sequence mismatch")
    if target.get("allowLiveReplay") is not True: failures.append("allowLiveReplay=false")
    if confirmation != expected_phrase: failures.append("confirmation phrase mismatch")
    if failures: raise SafetyError("; ".join(failures))
