from __future__ import annotations

from .devices import DEVICES, DeviceDefinition

# Backward-compatible public name used throughout the proven pipeline.
DeviceCapabilities = DeviceDefinition


def capabilities(vid_pid:str)->DeviceCapabilities:
    try:return DEVICES[vid_pid]
    except KeyError:raise ValueError(f"unsupported device: {vid_pid}") from None
