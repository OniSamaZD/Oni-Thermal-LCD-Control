"""Pure geometry helpers for physically representative LCD previews.

The values returned here affect only the desktop UI preview.  Device render
dimensions and transport framing remain owned by the device definition and
media pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class PhysicalPreviewSpec:
    pixel_size: tuple[int, int]
    diagonal_inches: float | None = None
    physical_scale_known: bool | None = None

    @property
    def aspect_ratio(self) -> float:
        width, height = self.pixel_size
        if width <= 0 or height <= 0:
            raise ValueError("preview pixel dimensions must be positive")
        return width / height

    @classmethod
    def from_profile(cls, profile) -> "PhysicalPreviewSpec":
        size = profile.render_size or profile.native_size
        if size is None:
            raise ValueError("physical profile has no preview geometry")
        return cls(size, profile.diagonal_inches, profile.diagonal_inches is not None or profile.active_width_mm is not None)


def _physical_envelope(spec: PhysicalPreviewSpec, diagonal: float) -> tuple[float, float]:
    height = diagonal / math.sqrt(spec.aspect_ratio * spec.aspect_ratio + 1.0)
    return height * spec.aspect_ratio, height


def physical_preview_sizes(
    specs: tuple[PhysicalPreviewSpec, ...],
    bounds: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    """Fit previews with one shared pixels-per-inch scale.

    A common scale makes known physical sizes comparable. Each result remains
    contained by its own card allocation and preserves pixel aspect. Unknown
    physical sizes use an independent neutral fit and never constrain or imply
    membership in the known physical comparison scale.
    """
    if len(specs) != len(bounds):
        raise ValueError("each preview requires one available-size bound")
    if not specs:
        return ()
    for spec in specs:spec.aspect_ratio
    known_indices=tuple(index for index,spec in enumerate(specs) if spec.diagonal_inches and spec.diagonal_inches>0)
    shared_scale=None
    if known_indices:
        shared_scale=min(
            min(max(1,bounds[index][0])/(_physical_envelope(specs[index],float(specs[index].diagonal_inches))[0]),
                max(1,bounds[index][1])/(_physical_envelope(specs[index],float(specs[index].diagonal_inches))[1]))
            for index in known_indices
        )
        shared_scale=max(.01,shared_scale)
    result=[]
    for index,(spec,(available_width,available_height)) in enumerate(zip(specs,bounds)):
        available_width=max(1,int(available_width));available_height=max(1,int(available_height))
        if index in known_indices:
            unit_width,unit_height=_physical_envelope(spec,float(spec.diagonal_inches));width=round(unit_width*shared_scale);height=round(unit_height*shared_scale)
        else:
            # Unknown-size previews are deliberately neutral and fitted on their
            # own.  They do not participate in, or constrain, physical scaling.
            target_width=max(1,round(available_width*.72));target_height=max(1,round(available_height*.72))
            scale=min(target_width/spec.pixel_size[0],target_height/spec.pixel_size[1])
            width=round(spec.pixel_size[0]*scale);height=round(spec.pixel_size[1]*scale)
        result.append((max(1,min(available_width,width)),max(1,min(available_height,height))))
    return tuple(result)
