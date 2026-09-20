from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceMode:
    name:str
    diagnostics_interval_ms:int
    sensor_interval_ms:int
    preview_when_hidden:bool
    log_level:str
    description:str


MODES={m.name:m for m in (
    ResourceMode("Ultra Low Resource",2000,1000,False,"WARNING","Static-first; minimum UI and sensor wakeups"),
    ResourceMode("Low Resource",1500,1000,False,"WARNING","Reduced hidden preview and background work"),
    ResourceMode("Normal",500,500,False,"INFO","Balanced desktop operation"),
    ResourceMode("High FPS",250,250,False,"INFO","Faster media and monitor feedback"),
    ResourceMode("Game Mode",2000,1000,False,"WARNING","Cached frames, low UI overhead, no process priority changes"),
)}


def resource_mode(name:str)->ResourceMode:
    if name not in MODES:raise ValueError("unknown resource mode")
    return MODES[name]
