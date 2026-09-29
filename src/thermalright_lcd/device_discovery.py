from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .devices.registry import DEVICES, device_definition
from .live_state import DeviceDisconnected, SafetyError
from .reviewed_devices import reviewed_device_definition


@dataclass(frozen=True, slots=True)
class DiscoveredDisplay:
    """Read-only discovery result. Constructing one never opens an output handle."""

    stable_id: str
    device_id: str
    status: str = "connected"
    detail: str = ""

    @property
    def definition(self):
        return device_definition(self.device_id)

    @property
    def connectable(self) -> bool:
        return self.status == "connected" and self.device_id in DEVICES


def discover_supported_displays(snapshot_factory=None) -> tuple[DiscoveredDisplay, ...]:
    """Discover reviewed hardware read-only and fail closed on ambiguity."""
    if snapshot_factory is None:
        from .windows_metadata import collect_windows_metadata_snapshot
        snapshot_factory = collect_windows_metadata_snapshot
    snapshot = snapshot_factory()
    results: list[DiscoveredDisplay] = []
    for device_id in tuple(DEVICES):
        if device_id.startswith(("thermalright-ref:","community-ref:")):continue
        try:
            definition = reviewed_device_definition(device_id)
            if definition.get("access_method") == "windows-hid":
                from .windows_hid import materialize_reviewed_hid_target,reviewed_reference_hid_connection
                target = materialize_reviewed_hid_target(definition,snapshot=snapshot)
                probe_factory=lambda target:reviewed_reference_hid_connection(target,snapshot=snapshot)
            else:
                from .windows_usb import materialize_reviewed_winusb_target,reviewed_reference_winusb_connection
                target = materialize_reviewed_winusb_target(definition,snapshot=snapshot)
                probe_factory=lambda target:reviewed_reference_winusb_connection(target,snapshot=snapshot)
            stable_id = str(target.get("stable_instance_id") or target.get("confirmed_device_path") or "").strip()
            if not stable_id:
                raise SafetyError("reviewed device has no stable physical identity")
            runtime_probe_factory=(lambda target:reviewed_reference_hid_connection(target)) if definition.get("access_method")=="windows-hid" else (lambda target:reviewed_reference_winusb_connection(target))
            results.append(resolve_shared_reviewed_target(device_id,target,probe_factory,runtime_probe_factory))
        except DeviceDisconnected:
            continue
        except (OSError, RuntimeError, SafetyError, KeyError, ValueError, AttributeError) as exc:
            results.append(DiscoveredDisplay(f"blocked:{device_id}", device_id, "blocked", str(exc)))
    # Community-reference devices are created only from currently present PnP
    # interfaces, then must pass their protocol handshake before registration.
    try:
        from .devices.thermalright_reference import enumerate_connected_candidates,ConnectedPanelCandidate
        from .windows_usb import reference_winusb_connection
        candidates=tuple(item for item in enumerate_connected_candidates(snapshot=snapshot) if item.vid_pid in {"87ad:70db","0416:5409","0416:5406"} and item.service.upper()=="WINUSB")
        results.extend(resolve_reference_candidates(candidates,reference_winusb_connection))
        from .windows_scsi import enumerate_scsi_candidates,ScsiPanelConnection
        scsi=tuple(ConnectedPanelCandidate(path,vid_pid,"SCSI","connected",path,"",path) for path,vid_pid in enumerate_scsi_candidates())
        results.extend(resolve_reference_candidates(scsi,lambda item:ScsiPanelConnection(item.instance_id,item.vid_pid)))
    except (OSError,RuntimeError,SafetyError,ValueError):
        pass
    try:
        from .community_runtime import discover_community_displays
        results.extend(discover_community_displays())
    except (OSError,RuntimeError,SafetyError,ValueError):
        pass
    return tuple(results)


def resolve_shared_reviewed_target(device_id: str, target: dict, probe_factory, runtime_probe_factory=None) -> DiscoveredDisplay:
    """Resolve a shared PID once before either reviewed or variant binding wins."""
    expected={"0416:5408":"trofeo-vision-916","0416:5302":"trofeo-vision-686"}
    if device_id not in expected:raise SafetyError(f"no shared-PID resolver for {device_id}")
    stable_id=str(target.get("stable_instance_id") or target.get("confirmed_device_path") or "").strip()
    if not stable_id:raise SafetyError("reviewed device has no stable physical identity")
    connection=probe_factory(target)
    try:model=connection.open()
    finally:connection.close()
    if model.key==expected[device_id]:return DiscoveredDisplay(stable_id,device_id,"connected",model.name)
    if model.vid_pid!=device_id:raise SafetyError("resolved model VID/PID does not match the physical candidate")
    from .reference_runtime import install_reference_binding
    runtime_probe_factory=runtime_probe_factory or probe_factory
    binding=install_reference_binding(stable_id,model,lambda t=target,f=runtime_probe_factory:f(t))
    return DiscoveredDisplay(stable_id,binding.device_id,"connected",model.name)


def simulated_reviewed_displays(device_ids: Iterable[str] = ("0416:5408", "0416:5302")) -> tuple[DiscoveredDisplay, ...]:
    return tuple(DiscoveredDisplay(f"simulated:{device_id}", device_id) for device_id in device_ids)


def resolve_reference_candidates(candidates, probe_factory) -> tuple[DiscoveredDisplay, ...]:
    """Probe only enumerated physical candidates and install exact runtime bindings."""
    from .reference_runtime import install_reference_binding
    results=[]
    for candidate in candidates:
        try:
            connection=probe_factory(candidate);model=connection.open();connection.close()
            binding=install_reference_binding(candidate.instance_id,model,lambda c=candidate:probe_factory(c))
            results.append(DiscoveredDisplay(candidate.instance_id,binding.device_id,"connected",model.name))
        except Exception as exc:
            # Unknown/ambiguous hardware is observable for diagnostics but can
            # never become a DisplaySession.
            results.append(DiscoveredDisplay(candidate.instance_id,f"unsupported:{candidate.vid_pid}","blocked",str(exc)))
    return tuple(results)


class DisplayLifecycle:
    """Stable-identity reconciliation with exactly one runtime per device."""

    def __init__(self, create: Callable[[DiscoveredDisplay], object], destroy: Callable[[object], None]):
        self._create = create
        self._destroy = destroy
        self._runtimes: dict[str, object] = {}
        self._observations: dict[str, DiscoveredDisplay] = {}

    @property
    def runtimes(self) -> dict[str, object]:
        return dict(self._runtimes)

    @property
    def observations(self) -> tuple[DiscoveredDisplay, ...]:
        return tuple(self._observations.values())

    def reconcile(self, observations: Iterable[DiscoveredDisplay]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        current = {item.stable_id: item for item in observations}
        wanted = {key: item for key, item in current.items() if item.connectable}
        removed = tuple(key for key in self._runtimes if key not in wanted)
        for key in removed:
            runtime = self._runtimes.pop(key)
            self._destroy(runtime)
        added = []
        for key, item in wanted.items():
            if key in self._runtimes:
                continue
            self._runtimes[key] = self._create(item)
            added.append(key)
        self._observations = current
        return tuple(added), removed

    def clear(self) -> None:
        for runtime in tuple(self._runtimes.values()):
            self._destroy(runtime)
        self._runtimes.clear(); self._observations.clear()
