"""Data model and sensor binding resolution for customizable sensor themes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from .sensors import SensorValue, resolve_semantic_sensor


THEME_FORMAT = "oni-sensor-theme"
SCHEMA_VERSION = 1
MAX_ELEMENTS = 512
MAX_CANVAS_EDGE = 8192

DISPLAY_PRESETS: dict[str, tuple[int, int]] = {
    "0416:5408": (1920, 462),
    "0416:5302": (1280, 480),
    "trofeo_vision_9_16": (1920, 462),
    "trofeo_vision_6_86": (1280, 480),
}

ELEMENT_TYPES = frozenset({
    "text", "sensor_value", "sensor_label", "image", "icon",
    "progress_bar", "horizontal_bar", "vertical_bar", "ring_gauge",
    "arc_gauge", "line_graph", "clock", "date",
})

_COMMON_ELEMENT_FIELDS = {
    "id", "name", "type", "x", "y", "width", "height", "rotation", "opacity", "visible", "locked", "z_index",
    "foreground_color", "background_color", "border_color", "border_width", "corner_radius",
    "shadow", "shadow_color", "shadow_offset_x", "shadow_offset_y", "shadow_blur",
    "glow", "glow_color", "glow_strength",
}
_TYPOGRAPHY_FIELDS = {
    "text", "font_family", "font_file", "font_size", "font_weight", "italic", "alignment",
    "vertical_alignment", "letter_spacing", "text_color",
}
_SENSOR_FIELDS = {
    "sensor_binding", "unit", "decimal_precision", "prefix", "suffix", "minimum", "maximum",
    "warning_threshold", "critical_threshold", "unavailable_text", "value_color", "warning_color", "critical_color",
}
_GAUGE_BAR_FIELDS = {"thickness", "start_angle", "end_angle", "direction", "track_color"}
_GRAPH_FIELDS = {"history_duration", "line_width", "fill", "fill_color", "smoothing", "automatic_scale", "scale_min", "scale_max"}
_IMAGE_FIELDS = {"asset", "image_fit", "crop"}


def applicable_element_fields(element_type: str) -> frozenset[str]:
    """Return the editable schema fields applicable to an element type."""
    if element_type not in ELEMENT_TYPES:
        raise ThemeValidationError(f"unsupported element type: {element_type}")
    allowed = set(_COMMON_ELEMENT_FIELDS)
    if element_type in {"text", "sensor_value", "sensor_label", "clock", "date"}:
        allowed.update(_TYPOGRAPHY_FIELDS)
    if element_type in {"sensor_value", "sensor_label", "progress_bar", "horizontal_bar", "vertical_bar", "ring_gauge", "arc_gauge", "line_graph"}:
        allowed.update(_SENSOR_FIELDS)
    if element_type in {"progress_bar", "horizontal_bar", "vertical_bar", "ring_gauge", "arc_gauge"}:
        allowed.update(_GAUGE_BAR_FIELDS)
    if element_type == "line_graph":
        allowed.update(_GRAPH_FIELDS)
    if element_type in {"image", "icon"}:
        allowed.update(_IMAGE_FIELDS)
    if element_type == "clock":
        allowed.add("time_format")
    if element_type == "date":
        allowed.add("date_format")
    return frozenset(allowed)

# Logical names are intentionally derived from the aliases already supported
# by sensors.manager. Direct canonical keys and qualified provider IDs also
# resolve at runtime, so a theme never depends on a GUI widget instance.
SUPPORTED_SENSOR_BINDINGS: dict[str, str] = {
    "cpu.temperature": "cpu_temp",
    "cpu.usage": "cpu_usage",
    "cpu.clock": "cpu_clock",
    "cpu.package_power": "cpu_power",
    "gpu.temperature": "gpu_temp",
    "gpu.hotspot": "gpu_hotspot",
    "gpu.usage": "gpu_usage",
    "gpu.clock": "gpu_clock",
    "gpu.memory_clock": "gpu_memory_clock",
    "gpu.memory_usage": "vram_usage",
    "gpu.memory_used": "vram_used",
    "gpu.memory_total": "vram_total",
    "gpu.power": "gpu_power",
    "gpu.fan_speed": "fan_rpm",
    "memory.usage": "ram_usage",
    "storage.temperature": "ssd_temp",
    "network.download": "network_download",
    "network.upload": "network_upload",
    "game.fps": "fps",
    "game.fps_1_low": "fps_1low",
    "game.frametime": "frametime",
    "cooling.fan_speed": "fan_rpm",
    "cooling.pump_speed": "pump_rpm",
}


class ThemeValidationError(ValueError):
    """A theme is malformed, unsafe, or outside bounded limits."""


def _finite(value: object, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ThemeValidationError(f"{field_name} must be numeric") from exc
    if not math.isfinite(result):
        raise ThemeValidationError(f"{field_name} must be finite")
    return result


def _integer(value: object, field_name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ThemeValidationError(f"{field_name} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ThemeValidationError(f"{field_name} must be an integer")
    return result


def _color(value: str, field_name: str, *, allow_empty: bool = True) -> str:
    value = str(value)
    if allow_empty and not value:
        return value
    if value == "transparent" or re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
        return value
    raise ThemeValidationError(f"{field_name} must be #RRGGBB, #RRGGBBAA, or transparent")


def _safe_member(value: str, prefix: str) -> str:
    if not value:
        return ""
    member = PurePosixPath(value)
    if member.is_absolute() or ".." in member.parts or "\\" in value or not value.startswith(prefix):
        raise ThemeValidationError(f"unsafe theme resource path: {value}")
    return value


@dataclass(slots=True)
class ThemeCanvas:
    width: int
    height: int
    preset: str = "custom"
    scale_mode: str = "contain"

    def __post_init__(self) -> None:
        self.width, self.height = _integer(self.width, "canvas width"), _integer(self.height, "canvas height")
        if not (1 <= self.width <= MAX_CANVAS_EDGE and 1 <= self.height <= MAX_CANVAS_EDGE):
            raise ThemeValidationError("canvas dimensions are outside supported limits")
        if self.scale_mode not in {"contain", "cover", "stretch"}:
            raise ThemeValidationError("canvas scale_mode must be contain, cover, or stretch")
        if self.preset != "custom" and self.preset not in DISPLAY_PRESETS:
            raise ThemeValidationError(f"unknown display preset: {self.preset}")
        if self.preset in DISPLAY_PRESETS and (self.width, self.height) != DISPLAY_PRESETS[self.preset]:
            raise ThemeValidationError("canvas dimensions do not match its display preset")

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "ThemeCanvas":
        if not isinstance(raw, Mapping):
            raise ThemeValidationError("canvas must be an object")
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ThemeValidationError(f"unknown canvas properties: {', '.join(sorted(unknown))}")
        preset = str(raw.get("preset", "custom"))
        preset_size = DISPLAY_PRESETS.get(preset)
        width = raw.get("width", preset_size[0] if preset_size else None)
        height = raw.get("height", preset_size[1] if preset_size else None)
        if width is None or height is None:
            raise ThemeValidationError("custom canvas requires width and height")
        return cls(width, height, preset, str(raw.get("scale_mode", "contain")))


@dataclass(slots=True)
class ThemeElement:
    id: str
    name: str
    type: str
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0
    opacity: float = 1.0
    visible: bool = True
    locked: bool = False
    z_index: int = 0

    text: str = ""
    font_family: str = "Segoe UI"
    font_file: str = ""
    font_size: float = 32.0
    font_weight: int = 400
    italic: bool = False
    alignment: str = "left"
    vertical_alignment: str = "middle"
    letter_spacing: float = 0.0
    text_color: str = "#F2F6FF"

    foreground_color: str = "#2BC8FF"
    background_color: str = "transparent"
    border_color: str = "transparent"
    border_width: float = 0.0
    corner_radius: float = 0.0
    shadow: bool = False
    shadow_color: str = "#00000080"
    shadow_offset_x: float = 3.0
    shadow_offset_y: float = 3.0
    shadow_blur: float = 4.0
    glow: bool = False
    glow_color: str = "#2BC8FF80"
    glow_strength: float = 6.0

    sensor_binding: str = ""
    unit: str = ""
    decimal_precision: int = 1
    prefix: str = ""
    suffix: str = ""
    minimum: float = 0.0
    maximum: float = 100.0
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    unavailable_text: str = "--"

    thickness: float = 12.0
    start_angle: float = 135.0
    end_angle: float = 405.0
    direction: str = "clockwise"
    track_color: str = "#173047"
    value_color: str = "#2BC8FF"
    warning_color: str = "#FFB020"
    critical_color: str = "#FF4D5A"

    history_duration: float = 60.0
    line_width: float = 3.0
    fill: bool = False
    fill_color: str = "#2BC8FF30"
    smoothing: bool = False
    automatic_scale: bool = False
    scale_min: float = 0.0
    scale_max: float = 100.0

    asset: str = ""
    image_fit: str = "contain"
    crop: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    time_format: str = "%H:%M"
    date_format: str = "%A, %d %B"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not isinstance(self.name, str) or not isinstance(self.type, str):
            raise ThemeValidationError("element id, name, and type must be strings")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.id):
            raise ThemeValidationError("element id must be a stable 1-64 character identifier")
        if not self.name or len(self.name) > 128:
            raise ThemeValidationError("element name is required and must be at most 128 characters")
        if self.type not in ELEMENT_TYPES:
            raise ThemeValidationError(f"unsupported element type: {self.type}")
        for key in ("x", "y", "width", "height", "rotation", "opacity", "font_size", "letter_spacing",
                    "border_width", "corner_radius", "shadow_offset_x", "shadow_offset_y", "shadow_blur",
                    "glow_strength", "minimum", "maximum", "thickness", "start_angle", "end_angle",
                    "history_duration", "line_width", "scale_min", "scale_max"):
            setattr(self, key, _finite(getattr(self, key), key))
        if self.width <= 0 or self.height <= 0 or self.width > MAX_CANVAS_EDGE or self.height > MAX_CANVAS_EDGE:
            raise ThemeValidationError("element dimensions must be positive and bounded")
        if not -MAX_CANVAS_EDGE <= self.x <= MAX_CANVAS_EDGE or not -MAX_CANVAS_EDGE <= self.y <= MAX_CANVAS_EDGE:
            raise ThemeValidationError("element position is outside supported limits")
        if not 0 <= self.opacity <= 1:
            raise ThemeValidationError("opacity must be between 0 and 1")
        self.font_weight = _integer(self.font_weight, "font_weight")
        if not 1 <= self.font_size <= 512 or not 100 <= self.font_weight <= 900:
            raise ThemeValidationError("font size or weight is outside supported limits")
        self.z_index = _integer(self.z_index, "z_index")
        if not -1_000_000 <= self.z_index <= 1_000_000:
            raise ThemeValidationError("z_index is outside supported limits")
        self.decimal_precision = _integer(self.decimal_precision, "decimal_precision")
        if not 0 <= self.decimal_precision <= 8:
            raise ThemeValidationError("decimal_precision must be between 0 and 8")
        if self.maximum <= self.minimum or self.scale_max <= self.scale_min:
            raise ThemeValidationError("maximum values must be greater than minimum values")
        for key in ("warning_threshold", "critical_threshold"):
            if getattr(self, key) is not None:
                setattr(self, key, _finite(getattr(self, key), key))
        if self.alignment not in {"left", "center", "right"}:
            raise ThemeValidationError("invalid text alignment")
        if self.vertical_alignment not in {"top", "middle", "bottom"}:
            raise ThemeValidationError("invalid vertical text alignment")
        if self.direction not in {"clockwise", "counterclockwise", "left_to_right", "right_to_left", "bottom_to_top", "top_to_bottom"}:
            raise ThemeValidationError("invalid gauge/bar direction")
        if self.image_fit not in {"contain", "cover", "stretch", "crop"}:
            raise ThemeValidationError("invalid image_fit")
        for key in ("visible", "locked", "italic", "shadow", "glow", "fill", "smoothing", "automatic_scale"):
            if not isinstance(getattr(self, key), bool):
                raise ThemeValidationError(f"{key} must be true or false")
        for key in ("text", "font_family", "font_file", "sensor_binding", "unit", "prefix", "suffix", "unavailable_text", "asset", "time_format", "date_format"):
            if not isinstance(getattr(self, key), str):
                raise ThemeValidationError(f"{key} must be a string")
        if not isinstance(self.crop, list) or len(self.crop) != 4 or any(not 0 <= _finite(item, "crop") <= 1 for item in self.crop):
            raise ThemeValidationError("crop must contain four normalized values")
        if self.crop[2] <= self.crop[0] or self.crop[3] <= self.crop[1]:
            raise ThemeValidationError("crop right/bottom must exceed left/top")
        for key in ("text_color", "foreground_color", "background_color", "border_color", "shadow_color",
                    "glow_color", "track_color", "value_color", "warning_color", "critical_color", "fill_color"):
            setattr(self, key, _color(getattr(self, key), key))
        self.asset = _safe_member(self.asset, "assets/")
        self.font_file = _safe_member(self.font_file, "fonts/")
        if self.type in {"sensor_value", "sensor_label", "progress_bar", "horizontal_bar", "vertical_bar",
                         "ring_gauge", "arc_gauge", "line_graph"} and not self.sensor_binding:
            raise ThemeValidationError(f"{self.type} requires sensor_binding")
        if self.type in {"image", "icon"} and not self.asset:
            raise ThemeValidationError(f"{self.type} requires an asset")

    def to_dict(self) -> dict[str, Any]:
        """Serialize only properties applicable to this element type."""
        allowed = applicable_element_fields(self.type)
        return {item.name: deepcopy(getattr(self, item.name)) for item in fields(self) if item.name in allowed}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "ThemeElement":
        if not isinstance(raw, Mapping):
            raise ThemeValidationError("theme element must be an object")
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ThemeValidationError(f"unknown element properties: {', '.join(sorted(unknown))}")
        try:
            return cls(**dict(raw))
        except TypeError as exc:
            raise ThemeValidationError(f"element is missing a required property: {exc}") from exc


@dataclass(slots=True)
class SensorTheme:
    id: str
    name: str
    canvas: ThemeCanvas
    elements: list[ThemeElement] = field(default_factory=list)
    description: str = ""
    author: str = ""
    background_color: str = "#03070D"
    schema_version: int = SCHEMA_VERSION
    format: str = THEME_FORMAT
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not isinstance(self.name, str):
            raise ThemeValidationError("theme id and name must be strings")
        self.schema_version = _integer(self.schema_version, "schema_version")
        if self.format != THEME_FORMAT or self.schema_version != SCHEMA_VERSION:
            raise ThemeValidationError("unsupported sensor theme format/version")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.id):
            raise ThemeValidationError("theme id must be a stable 1-64 character identifier")
        if not self.name or len(self.name) > 128:
            raise ThemeValidationError("theme name is required and must be at most 128 characters")
        if len(self.elements) > MAX_ELEMENTS:
            raise ThemeValidationError("theme contains too many elements")
        duplicates = {item.id for item in self.elements if sum(other.id == item.id for other in self.elements) > 1}
        if duplicates:
            raise ThemeValidationError(f"duplicate element ids: {', '.join(sorted(duplicates))}")
        self.background_color = _color(self.background_color, "background_color", allow_empty=False)
        if not isinstance(self.description, str) or not isinstance(self.author, str):
            raise ThemeValidationError("theme description and author must be strings")
        if not isinstance(self.metadata, dict):
            raise ThemeValidationError("metadata must be an object")
        try:
            json.dumps(self.metadata, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ThemeValidationError("metadata must contain JSON-compatible data") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "name": self.name, "canvas": asdict(self.canvas),
            "elements": [element.to_dict() for element in self.elements],
            "description": self.description, "author": self.author,
            "background_color": self.background_color, "schema_version": self.schema_version,
            "format": self.format, "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "SensorTheme":
        migrated = migrate_theme_dict(raw)
        allowed = {item.name for item in fields(cls)}
        unknown = set(migrated) - allowed
        if unknown:
            raise ThemeValidationError(f"unknown theme properties: {', '.join(sorted(unknown))}")
        canvas = ThemeCanvas.from_dict(migrated.get("canvas", {}))
        elements = [ThemeElement.from_dict(item) for item in migrated.get("elements", [])]
        values = dict(migrated)
        values["canvas"], values["elements"] = canvas, elements
        try:
            return cls(**values)
        except TypeError as exc:
            raise ThemeValidationError(f"theme is missing a required property: {exc}") from exc


def migrate_theme_dict(raw: Mapping[str, object]) -> dict[str, object]:
    """Migrate the documented schema-0 prototype without executing content."""
    if not isinstance(raw, Mapping):
        raise ThemeValidationError("theme.json must contain an object")
    data = deepcopy(dict(raw))
    version = data.get("schema_version", data.get("version", 0))
    try:
        version = int(version)
    except (TypeError, ValueError) as exc:
        raise ThemeValidationError("theme schema version is invalid") from exc
    if version > SCHEMA_VERSION or version < 0:
        raise ThemeValidationError(f"unsupported sensor theme schema version: {version}")
    if version == 0:
        if "canvas" not in data:
            data["canvas"] = {
                "width": data.pop("width", 1920), "height": data.pop("height", 462),
                "preset": data.pop("preset", "custom"), "scale_mode": data.pop("scale_mode", "contain"),
            }
        migrated_elements = []
        for raw_element in data.get("elements", []):
            element = dict(raw_element)
            renames = {
                "kind": "type", "sensor_id": "sensor_binding", "min": "minimum", "max": "maximum",
                "color": "foreground_color", "background": "background_color", "align": "alignment",
            }
            for old, new in renames.items():
                if old in element and new not in element:
                    element[new] = element.pop(old)
            if element.get("type") == "bar":
                element["type"] = "horizontal_bar"
            elif element.get("type") == "graph":
                element["type"] = "line_graph"
            migrated_elements.append(element)
        data["elements"] = migrated_elements
    data.pop("version", None)
    data["schema_version"] = SCHEMA_VERSION
    data["format"] = THEME_FORMAT
    return data


def validate_theme(theme: SensorTheme, available_resources: Iterable[str] = ()) -> None:
    """Validate references after structural dataclass validation."""
    available = set(available_resources)
    for element in theme.elements:
        for resource in (element.asset, element.font_file):
            if resource and resource not in available:
                raise ThemeValidationError(f"referenced theme resource is missing: {resource}")


@dataclass(frozen=True, slots=True)
class ResolvedSensor:
    binding: str
    value: float | int | str | None
    unit: str = ""
    label: str = ""
    available: bool = False


class SensorBindingResolver:
    """Resolve stable logical keys through current read-only sensor values."""

    def resolve(self, binding: str, values: Mapping[str, object] | Iterable[SensorValue]) -> ResolvedSensor:
        if isinstance(values, Mapping):
            raw = values.get(binding)
            if isinstance(raw, SensorValue):
                return self._from_sensor(binding, raw)
            if binding in values:
                return ResolvedSensor(binding, raw, available=raw is not None)
            return ResolvedSensor(binding, None)
        records = tuple(value for value in values if isinstance(value, SensorValue))
        direct = next((value for value in records if binding in {
            value.definition.canonical_key, value.definition.qualified_id, value.id,
        }), None)
        if direct is not None:
            return self._from_sensor(binding, direct)
        alias = SUPPORTED_SENSOR_BINDINGS.get(binding)
        match = resolve_semantic_sensor(alias, records) if alias else None
        return self._from_sensor(binding, match) if match else ResolvedSensor(binding, None)

    @staticmethod
    def _from_sensor(binding: str, sensor: SensorValue) -> ResolvedSensor:
        available = bool(sensor.valid and sensor.value is not None)
        return ResolvedSensor(binding, sensor.value if available else None, sensor.unit, sensor.name, available)


def format_sensor_value(element: ThemeElement, sensor: ResolvedSensor) -> str:
    if not sensor.available or sensor.value is None:
        return element.unavailable_text
    value = sensor.value
    if isinstance(value, bool):
        body = str(value)
    elif isinstance(value, (int, float)):
        body = f"{float(value):.{element.decimal_precision}f}"
    else:
        body = str(value)
    unit = element.unit if element.unit else sensor.unit
    return f"{element.prefix}{body}{unit}{element.suffix}"
