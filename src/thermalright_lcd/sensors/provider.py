from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time

from .models import SensorValue


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    available: bool
    last_error: str = ""
    latency_ms: float = 0.0
    values_read: int = 0


class SensorProvider(ABC):
    """Failure-containing boundary for a read-only sensor source."""

    name = "unknown"

    def __init__(self) -> None:
        self.status = ProviderStatus(self.name, False)

    def poll(self) -> tuple[SensorValue, ...]:
        started = time.perf_counter()
        try:
            values = tuple(self._read_values())
            latency = (time.perf_counter() - started) * 1000
            self.status = ProviderStatus(self.name, True, latency_ms=latency, values_read=len(values))
            return values
        except (FileNotFoundError, PermissionError) as exc:
            self.status = ProviderStatus(self.name, False, str(exc), (time.perf_counter() - started) * 1000)
            return ()
        except Exception as exc:  # provider corruption must not affect another provider/media
            self.status = ProviderStatus(self.name, False, f"{type(exc).__name__}: {exc}", (time.perf_counter() - started) * 1000)
            return ()

    @abstractmethod
    def _read_values(self) -> tuple[SensorValue, ...] | list[SensorValue]: ...
