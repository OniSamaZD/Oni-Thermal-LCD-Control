from __future__ import annotations

from .base import DeviceDefinition
from .trofeo_5302 import DEVICE as TROFEO_5302
from .trofeo_5408 import DEVICE as TROFEO_5408

DEVICES: dict[str, DeviceDefinition] = {item.vid_pid: item for item in (TROFEO_5408, TROFEO_5302)}


def register_device(device: DeviceDefinition) -> None:
    if device.vid_pid in DEVICES:
        raise ValueError(f"device already registered: {device.vid_pid}")
    DEVICES[device.vid_pid] = device


def device_definition(vid_pid: str) -> DeviceDefinition:
    try:
        return DEVICES[vid_pid]
    except KeyError:
        raise ValueError(f"unsupported device: {vid_pid}") from None
