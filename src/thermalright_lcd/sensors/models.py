from __future__ import annotations

from dataclasses import dataclass
import math
import time


@dataclass(frozen=True, slots=True)
class SensorDefinition:
    """Stable metadata for one provider measurement."""

    id: str
    provider: str
    name: str
    category: str = "Other"
    unit: str = ""
    canonical_key: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.provider or not self.name:
            raise ValueError("sensor id, provider, and name are required")

    @property
    def qualified_id(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def dedup_key(self) -> str:
        return self.canonical_key or _normalise_key(self.category, self.name, self.unit)


@dataclass(frozen=True, slots=True)
class SensorValue:
    definition: SensorDefinition
    value: float | int | str | None
    timestamp: float
    valid: bool = True
    error: str = ""

    @classmethod
    def now(
        cls, definition: SensorDefinition, value: float | int | str | None,
        *, valid: bool = True, error: str = "",
    ) -> "SensorValue":
        if isinstance(value, float) and not math.isfinite(value):
            valid, error = False, error or "non-finite value"
        return cls(definition, value, time.time(), valid, error)

    @property
    def id(self) -> str: return self.definition.id
    @property
    def provider(self) -> str: return self.definition.provider
    @property
    def name(self) -> str: return self.definition.name
    @property
    def category(self) -> str: return self.definition.category
    @property
    def unit(self) -> str: return self.definition.unit


def _normalise_key(*parts: str) -> str:
    return ".".join("".join(c.lower() for c in part if c.isalnum()) for part in parts)
