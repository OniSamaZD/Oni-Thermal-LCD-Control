"""Runtime bindings for positively identified community Thermalright panels."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .devices.base import DeviceDefinition
from .devices.registry import DEVICES


@dataclass(slots=True)
class ReferenceRuntimeBinding:
    device_id: str
    stable_id: str
    model: object
    sender_factory: object


_BINDINGS: dict[str, ReferenceRuntimeBinding] = {}


def install_reference_binding(stable_id: str, model, sender_factory, *, namespace: str = "thermalright-ref") -> ReferenceRuntimeBinding:
    suffix=hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:12]
    device_id=f"{namespace}:{model.key}:{suffix}"
    binding=ReferenceRuntimeBinding(device_id,stable_id,model,sender_factory);_BINDINGS[device_id]=binding
    DEVICES[device_id]=DeviceDefinition(
        device_id,getattr(model,"manufacturer","Thermalright"),model.name,model.render_size,model.native_size,
        model.transport,0,"dynamic","dynamic",model.transport,4096,
        model.protocol in {"trofeo-bulk","trofeo-bulk-ly1","ali"},
        full_frame_jpeg_required=model.pixel_format=="jpeg",transport_factory="reference-runtime",
        connection_type={"hid":"HID","winusb":"WinUSB","scsi":"SCSI pass-through","serial":"USB serial"}[model.transport],
        support_status="Implemented — community hardware validation required",maximum_fps=30,
    )
    from .persistence import POLICIES,VIDEO_TRANSPORT_TARGETS,PersistencePolicy
    POLICIES[device_id]=PersistencePolicy(device_id,5.0,5.0,.2,True,
        "protocol-specific acknowledgement when required","REFERENCE IMPLEMENTATION",
        ("InfoPanel ThermalrightPanel protocol implementation; community hardware validation required",),2.0)
    VIDEO_TRANSPORT_TARGETS[device_id]=min(30.0,float(DEVICES[device_id].maximum_fps))
    return binding


def reference_binding(device_id: str) -> ReferenceRuntimeBinding:
    return _BINDINGS[device_id]


def reference_model(device_id: str):
    return _BINDINGS[device_id].model


def build_reference_sender(device_id: str):
    return _BINDINGS[device_id].sender_factory()


def remove_reference_binding(device_id: str) -> None:
    _BINDINGS.pop(device_id,None);DEVICES.pop(device_id,None)
    from .persistence import POLICIES,VIDEO_TRANSPORT_TARGETS
    POLICIES.pop(device_id,None);VIDEO_TRANSPORT_TARGETS.pop(device_id,None)
