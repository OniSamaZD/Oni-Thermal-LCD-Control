from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock


class OutputMode(str, Enum):
    STOPPED = "stopped"
    MEDIA = "media"
    HARDWARE_MONITOR = "hardware_monitor"
    MEDIA_WITH_SENSOR_OVERLAY = "media_with_sensor_overlay"


@dataclass(frozen=True, slots=True)
class OutputLease:
    mode: OutputMode
    generation: int


class OutputOwnership:
    """Atomic, per-display final-frame producer ownership.

    A generation invalidates work which was prepared before a mode transition.
    The DisplaySession remains the single transport consumer; this object prevents
    independent media/monitor producers from alternately feeding its latest slot.
    """

    def __init__(self):
        self._lock = RLock()
        self._mode = OutputMode.STOPPED
        self._generation = 0

    def transition(self, mode: OutputMode | str) -> OutputLease:
        mode = OutputMode(mode)
        with self._lock:
            if mode != self._mode:
                self._generation += 1
                self._mode = mode
            return OutputLease(self._mode, self._generation)

    def lease(self) -> OutputLease:
        with self._lock:
            return OutputLease(self._mode, self._generation)

    def accepts(self, lease: OutputLease, *modes: OutputMode) -> bool:
        with self._lock:
            return lease.generation == self._generation and self._mode == lease.mode and self._mode in modes
