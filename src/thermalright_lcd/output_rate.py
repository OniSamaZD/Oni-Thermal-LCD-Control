from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .persistence import POLICIES, video_transport_target


class OutputRateKind(str, Enum):
    AUTOMATIC = "automatic"
    EVENT_DRIVEN = "event_driven"
    FIXED = "fixed"
    MAXIMUM = "maximum"


@dataclass(frozen=True, slots=True)
class OutputRate:
    label: str
    kind: OutputRateKind
    fps: float | None

    @property
    def interval_seconds(self) -> float | None:
        return None if self.fps is None else 1.0 / self.fps


RATE_LABELS = (
    "Auto (Recommended)", "10", "15", "20", "24", "25", "30", "40", "50", "60",
)


def resolve_output_rate(label: str, device_id: str, *, animated: bool,
                        quality_profile: str = "Balanced") -> OutputRate:
    """Resolve a persisted UI label without integer truncation.

    Automatic retains the proven device persistence cadence for static content
    and the measured transport target for time-based media. Event-driven has no
    periodic resend deadline; a changed generation is sent immediately.
    """
    normalized = str(label or "Automatic").strip()
    folded = normalized.casefold()
    # Profiles written before 2026-09-01 may contain the retired 0.2 row.
    # Keep loading them, but normalize to the supported low-rate replacement.
    if folded == "0.2":
        normalized = folded = "0.1"
    if folded in {"auto", "automatic", "auto (recommended)"}:
        fps = (video_transport_target(device_id, quality_profile) if animated
               else float(POLICIES[device_id].requested_fps))
        return OutputRate("Automatic", OutputRateKind.AUTOMATIC, fps)
    if folded in {"event-driven", "event driven", "event_driven"}:
        return OutputRate("Event-driven", OutputRateKind.EVENT_DRIVEN, None)
    if folded in {"maximum", "max"}:
        fps = video_transport_target(device_id, quality_profile)
        return OutputRate("Maximum", OutputRateKind.MAXIMUM, float(fps))
    # Backward-compatible profiles may contain 24, 45, 60 or Custom even when
    # those entries are no longer part of the compact static-oriented menu.
    fps = 30.0 if folded == "custom" else float(normalized)
    if fps <= 0:
        raise ValueError("output FPS must be positive")
    return OutputRate(normalized, OutputRateKind.FIXED, fps)
