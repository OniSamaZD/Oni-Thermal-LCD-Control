"""Immutable physical-display metadata used only by desktop preview geometry.

Pixel geometry, physical panel geometry, enclosure dimensions and output
orientation are deliberately separate.  A profile never authorizes a device
or changes its encoder/transport behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import math


class GeometryProvenance(str, Enum):
    ONI_PHYSICAL_MEASUREMENT = "ONI_PHYSICAL_MEASUREMENT"
    MANUFACTURER_SPECIFICATION = "MANUFACTURER_SPECIFICATION"
    REFERENCE_DATABASE = "REFERENCE_DATABASE"
    COMMUNITY_PHYSICAL_MEASUREMENT = "COMMUNITY_PHYSICAL_MEASUREMENT"
    COMMUNITY_REPORT = "COMMUNITY_REPORT"
    DERIVED_FROM_VERIFIED_GEOMETRY = "DERIVED_FROM_VERIFIED_GEOMETRY"
    UNKNOWN = "UNKNOWN"


class PhysicalScaleState(str, Enum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PhysicalDisplayProfile:
    profile_id: str
    native_size: tuple[int, int] | None
    render_size: tuple[int, int] | None
    excluded_rows: int = 0
    diagonal_inches: float | None = None
    active_width_mm: float | None = None
    active_height_mm: float | None = None
    enclosure_size_mm: tuple[float, float, float] | None = None
    output_orientation_degrees: int = 0
    geometry_provenance: GeometryProvenance = GeometryProvenance.UNKNOWN
    resolution_provenance: GeometryProvenance = GeometryProvenance.REFERENCE_DATABASE
    orientation_provenance: GeometryProvenance = GeometryProvenance.UNKNOWN
    source: str = ""

    def __post_init__(self):
        for name, size in (("native", self.native_size), ("render", self.render_size)):
            if size is not None and (len(size) != 2 or min(size) <= 0):
                raise ValueError(f"{name} display dimensions must be positive")
        if self.excluded_rows < 0:
            raise ValueError("excluded rows cannot be negative")
        if self.diagonal_inches is not None and self.diagonal_inches <= 0:
            raise ValueError("physical diagonal must be positive")
        if (self.active_width_mm is None) != (self.active_height_mm is None):
            raise ValueError("active width and height must be supplied together")
        if self.active_width_mm is not None and min(self.active_width_mm, self.active_height_mm) <= 0:
            raise ValueError("active display dimensions must be positive")

    @property
    def aspect_ratio(self) -> float | None:
        size = self.render_size or self.native_size
        return size[0] / size[1] if size else None

    @property
    def physical_scale_state(self) -> PhysicalScaleState:
        if self.diagonal_inches is not None or self.active_width_mm is not None:
            return PhysicalScaleState.KNOWN
        if self.render_size is not None or self.native_size is not None or self.enclosure_size_mm is not None:
            return PhysicalScaleState.PARTIAL
        return PhysicalScaleState.UNKNOWN

    @property
    def derived_active_size_mm(self) -> tuple[float, float] | None:
        if self.active_width_mm is not None:
            return self.active_width_mm, self.active_height_mm
        aspect = self.aspect_ratio
        if self.diagonal_inches is None or aspect is None:
            return None
        diagonal_mm = self.diagonal_inches * 25.4
        height = diagonal_mm / math.sqrt(aspect * aspect + 1.0)
        return height * aspect, height

    @property
    def active_size_provenance(self) -> GeometryProvenance:
        if self.active_width_mm is not None:
            return self.geometry_provenance
        if self.derived_active_size_mm is not None:
            return GeometryProvenance.DERIVED_FROM_VERIFIED_GEOMETRY
        return GeometryProvenance.UNKNOWN


_KNOWN: dict[str, PhysicalDisplayProfile] = {
    "trofeo-vision-686": PhysicalDisplayProfile(
        "trofeo-vision-686", (1280, 480), (1280, 480), diagonal_inches=6.86,
        enclosure_size_mm=(187.2, 72.1, 21.0),
        geometry_provenance=GeometryProvenance.MANUFACTURER_SPECIFICATION,
        source="Thermalright Trofeo Vision LCD product specification",
    ),
    "trofeo-vision-916": PhysicalDisplayProfile(
        "trofeo-vision-916", (1920, 480), (1920, 462), excluded_rows=18,
        diagonal_inches=9.16, enclosure_size_mm=(251.0, 68.0, 17.0),
        geometry_provenance=GeometryProvenance.MANUFACTURER_SPECIFICATION,
        source="Thermalright Trofeo Vision 9.16 LCD product specification; ONI reviewed render area",
    ),
    "trofeo-vision-113": PhysicalDisplayProfile(
        "trofeo-vision-113", (1920, 400), (1920, 400), diagonal_inches=11.3,
        enclosure_size_mm=(272.0, 70.0, 14.0),
        geometry_provenance=GeometryProvenance.MANUFACTURER_SPECIFICATION,
        source="Thermalright Trofeo Vision 11.3 LCD product specification",
    ),
    "fan-frame-vision-1": PhysicalDisplayProfile(
        "fan-frame-vision-1", (640, 172), (640, 172), diagonal_inches=3.69,
        enclosure_size_mm=(120.0, 120.0, 15.0),
        geometry_provenance=GeometryProvenance.MANUFACTURER_SPECIFICATION,
        source="Thermalright Fan Frame Vision-1 product specification",
    ),
    "wonder-vision-360-panel": PhysicalDisplayProfile(
        "wonder-vision-360-panel", (2400, 1080), (1600, 720), diagonal_inches=6.67,
        geometry_provenance=GeometryProvenance.REFERENCE_DATABASE,
        source="Thermalright reference database; v1/v2 identified as the same panel generation",
    ),
    "frozen-warframe-ultra": PhysicalDisplayProfile(
        "frozen-warframe-ultra", (480, 480), (480, 480), output_orientation_degrees=180,
        geometry_provenance=GeometryProvenance.UNKNOWN,
        orientation_provenance=GeometryProvenance.COMMUNITY_REPORT,
        source="InfoPanel reference geometry; hstones community orientation report",
    ),
}

_MODEL_PROFILE_ALIASES = {
    "wonder-vision-360": "wonder-vision-360-panel",
    "wonder-vision-360-v2": "wonder-vision-360-panel",
}


def known_physical_profiles() -> tuple[PhysicalDisplayProfile, ...]:
    return tuple(_KNOWN.values())


@lru_cache(maxsize=512)
def physical_profile(
    profile_id: str,
    native_size: tuple[int, int] | None = None,
    render_size: tuple[int, int] | None = None,
) -> PhysicalDisplayProfile:
    """Resolve known metadata or create an explicit non-authoritative fallback."""
    known = _KNOWN.get(_MODEL_PROFILE_ALIASES.get(profile_id, profile_id))
    if known is not None:
        if native_size and known.native_size != native_size:
            raise ValueError(f"native geometry conflicts with physical profile {profile_id}")
        if render_size and known.render_size != render_size:
            raise ValueError(f"render geometry conflicts with physical profile {profile_id}")
        return known
    return PhysicalDisplayProfile(
        profile_id or "unknown-display", native_size, render_size,
        geometry_provenance=GeometryProvenance.UNKNOWN,
        resolution_provenance=GeometryProvenance.REFERENCE_DATABASE if render_size or native_size else GeometryProvenance.UNKNOWN,
        source="Existing ONI model/catalog geometry; physical size unknown",
    )


def profile_for_catalog_model(model) -> PhysicalDisplayProfile:
    sizes = tuple(model.resolutions)
    render = sizes[0] if sizes else None
    if model.key in _KNOWN or model.key in _MODEL_PROFILE_ALIASES:
        return physical_profile(model.key)
    return physical_profile(model.key, render, render)


def audit_catalog_geometry(models) -> dict[str, object]:
    rows=[]
    for model in models:
        profile=profile_for_catalog_model(model)
        rows.append({
            "key":model.key,"manufacturer":model.manufacturer,"model":model.model,
            "identifiers":tuple(model.identifiers),"transport":model.connection_type,
            "resolutions":tuple(model.resolutions),"profile_id":profile.profile_id,
            "scale_state":profile.physical_scale_state.value,"diagonal_inches":profile.diagonal_inches,
            "active_size_mm":(profile.active_width_mm,profile.active_height_mm) if profile.active_width_mm is not None else None,
            "enclosure_size_mm":profile.enclosure_size_mm,"excluded_rows":profile.excluded_rows,
            "orientation_degrees":profile.output_orientation_degrees,
            "geometry_provenance":profile.geometry_provenance.value,"source":profile.source,
        })
    return {
        "total":len(rows),
        "known_diagonal":sum(item["diagonal_inches"] is not None for item in rows),
        "known_active_size":sum(item["active_size_mm"] is not None for item in rows),
        "resolution_only":sum(bool(item["resolutions"]) and item["diagonal_inches"] is None and item["active_size_mm"] is None for item in rows),
        "completely_unknown":sum(not item["resolutions"] and item["diagonal_inches"] is None and item["active_size_mm"] is None for item in rows),
        "rows":tuple(rows),
    }


def geometry_status_text(profile: PhysicalDisplayProfile) -> str:
    if profile.diagonal_inches is not None:
        return f'{profile.diagonal_inches:g}" — {profile.geometry_provenance.value.replace("_", " ").title()}'
    if profile.physical_scale_state is PhysicalScaleState.PARTIAL:
        return "Physical size unknown — aspect ratio only"
    return "Physical geometry unknown"
