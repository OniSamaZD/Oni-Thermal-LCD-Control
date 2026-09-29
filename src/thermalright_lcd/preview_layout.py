"""Pure geometry helpers for physically representative LCD previews.

The values returned here affect only the desktop UI preview.  Device render
dimensions and transport framing remain owned by the device definition and
media pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics


@dataclass(frozen=True, slots=True)
class PhysicalPreviewSpec:
    pixel_size: tuple[int, int]
    diagonal_inches: float | None = None

    @property
    def aspect_ratio(self) -> float:
        width, height = self.pixel_size
        if width <= 0 or height <= 0:
            raise ValueError("preview pixel dimensions must be positive")
        return width / height


def _effective_diagonals(specs: tuple[PhysicalPreviewSpec, ...]) -> tuple[float, ...]:
    """Return safe relative diagonals without claiming missing measurements."""
    known = [float(spec.diagonal_inches) for spec in specs if spec.diagonal_inches and spec.diagonal_inches > 0]
    fallback = statistics.median(known) if known else 7.0
    return tuple(float(spec.diagonal_inches) if spec.diagonal_inches and spec.diagonal_inches > 0 else fallback for spec in specs)


def physical_preview_sizes(
    specs: tuple[PhysicalPreviewSpec, ...],
    bounds: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    """Fit previews with one shared pixels-per-inch scale.

    A common scale makes known physical sizes comparable.  Each result also
    remains contained by its own card allocation and preserves pixel aspect.
    Unknown physical sizes use the median known diagonal (or a neutral 7-inch
    fallback when all are unknown), so they remain safe and non-authoritative.
    """
    if len(specs) != len(bounds):
        raise ValueError("each preview requires one available-size bound")
    if not specs:
        return ()
    diagonals = _effective_diagonals(specs)
    envelopes: list[tuple[float, float]] = []
    scales: list[float] = []
    for spec, diagonal, (available_width, available_height) in zip(specs, diagonals, bounds):
        aspect = spec.aspect_ratio
        unit_height = diagonal / math.sqrt(aspect * aspect + 1.0)
        unit_width = unit_height * aspect
        envelopes.append((unit_width, unit_height))
        scales.append(min(max(1, available_width) / unit_width, max(1, available_height) / unit_height))
    shared_scale = max(0.01, min(scales))
    return tuple(
        (max(1, min(int(available_width), round(unit_width * shared_scale))),
         max(1, min(int(available_height), round(unit_height * shared_scale))))
        for (unit_width, unit_height), (available_width, available_height) in zip(envelopes, bounds)
    )
