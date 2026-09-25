from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceDefinition:
    """Evidence-backed model boundary used by UI, media and transport selection."""
    vid_pid: str
    manufacturer: str
    model: str
    encoded_size: tuple[int, int]
    nominal_size: tuple[int, int]
    backend: str
    interface: int
    out_endpoint: str
    in_endpoint: str | None
    transfer_type: str
    host_payload_size: int
    frame_ack_required: bool
    orientation: str = "landscape"
    full_frame_jpeg_required: bool = True
    dirty_region_protocol: bool = False
    transport_factory: str = ""
    connection_type: str = "USB"
    support_status: str = "Physically verified"
    brightness_support: str = "software"
    maximum_fps: int = 30


@dataclass(frozen=True, slots=True)
class DeviceFamilyDefinition:
    family_id: str
    manufacturer: str
    models: tuple[str, ...]
    resolutions: tuple[tuple[int, int], ...]
    connection_type: str
    identifiers: tuple[str, ...]
    support_status: str
    protocol_reference: str
    reference_license: str
    output_enabled: bool = False
    notes: str = ""
