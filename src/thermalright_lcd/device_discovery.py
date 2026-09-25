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


def discover_supported_displays() -> tuple[DiscoveredDisplay, ...]:
    """Discover reviewed hardware read-only and fail closed on ambiguity."""
    results: list[DiscoveredDisplay] = []
    for device_id in DEVICES:
        if device_id.startswith("thermalright-ref:"):continue
        try:
            definition = reviewed_device_definition(device_id)
            if definition.get("access_method") == "windows-hid":
                from .windows_hid import materialize_reviewed_hid_target
                target = materialize_reviewed_hid_target(definition)
            else:
                from .windows_usb import materialize_reviewed_winusb_target
                target = materialize_reviewed_winusb_target(definition)
            stable_id = str(target.get("stable_instance_id") or target.get("confirmed_device_path") or "").strip()
            if not stable_id:
                raise SafetyError("reviewed device has no stable physical identity")
            results.append(DiscoveredDisplay(stable_id, device_id))
        except DeviceDisconnected:
            continue
        except (OSError, RuntimeError, SafetyError, KeyError, ValueError) as exc:
            results.append(DiscoveredDisplay(f"blocked:{device_id}", device_id, "blocked", str(exc)))
    # Community-reference devices are created only from currently present PnP
    # interfaces, then must pass their protocol handshake before registration.
    try:
        from .devices.thermalright_reference import enumerate_connected_candidates,ConnectedPanelCandidate
        from .windows_usb import reference_winusb_connection
        candidates=tuple(item for item in enumerate_connected_candidates() if item.vid_pid in {"87ad:70db","0416:5409","0416:5406"} and item.service.upper()=="WINUSB")
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
