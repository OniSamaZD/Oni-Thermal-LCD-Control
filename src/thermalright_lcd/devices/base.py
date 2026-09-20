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
