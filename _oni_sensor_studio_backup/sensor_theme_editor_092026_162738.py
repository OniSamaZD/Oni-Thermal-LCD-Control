"""Visual editor for the data-driven Phase 1 sensor-theme engine."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
from typing import Callable, Iterable
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import QByteArray, QMimeData, QPointF, QRectF, QSize, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFileDialog, QFontComboBox, QFormLayout, QFrame, QGraphicsItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .sensor_theme import (
    DISPLAY_PRESETS, ELEMENT_TYPES, SUPPORTED_SENSOR_BINDINGS, SensorBindingResolver, SensorTheme,
    ThemeCanvas, ThemeElement, ThemeValidationError, applicable_element_fields,
)
from .sensor_theme_package import export_theme_package
from .sensor_theme_renderer import SensorThemeRenderer
from .sensor_theme_store import SensorThemeStore, StoredTheme


FRIENDLY_ELEMENT_NAMES = {
    "text": "Text", "sensor_value": "Sensor Value", "sensor_label": "Sensor Label", "sensor_label_value": "Sensor Label + Value", "value_unit": "Value + Unit",
    "image": "Image", "icon": "Icon", "progress_bar": "Progress Bar",
    "horizontal_bar": "Horizontal Bar", "vertical_bar": "Vertical Bar",
    "ring_gauge": "Ring Gauge", "arc_gauge": "Arc Gauge",
    "line_graph": "Line Graph", "area_graph": "Area Graph", "progress_indicator": "Progress Indicator", "clock": "Clock", "date": "Date", "fps": "FPS", "frametime": "Frametime",
}

FRIENDLY_SENSOR_NAMES = {
    "cpu.temperature": "CPU Temperature", "cpu.usage": "CPU Usage",
    "cpu.clock": "CPU Clock", "cpu.package_power": "CPU Package Power",
    "gpu.temperature": "GPU Temperature", "gpu.hotspot": "GPU Hotspot",
    "gpu.usage": "GPU Usage", "gpu.clock": "GPU Clock",
    "gpu.memory_clock": "GPU Memory Clock", "gpu.memory_usage": "GPU Memory Usage",
    "gpu.memory_used": "GPU Memory Used", "gpu.memory_total": "GPU Memory Total",
    "gpu.power": "GPU Power", "gpu.fan_speed": "GPU Fan Speed",
    "memory.usage": "Memory Usage", "storage.temperature": "Storage Temperature",
    "network.download": "Network Download", "network.upload": "Network Upload",
    "game.fps": "Game FPS", "game.fps_1_low": "Game 1% Low FPS",
    "game.frametime": "Game Frametime", "cooling.fan_speed": "Cooling Fan Speed",
    "cooling.pump_speed": "Cooling Pump Speed",
}

SAMPLE_SENSOR_VALUES = {
    "cpu.temperature": 64.2, "cpu.usage": 57, "cpu.clock": 5125,
    "cpu.package_power": 121, "gpu.temperature": 70.5, "gpu.hotspot": 82,
    "gpu.usage": 76, "gpu.clock": 2670, "gpu.memory_clock": 10501,
    "gpu.memory_usage": 44, "gpu.memory_used": 10.6, "gpu.memory_total": 24,
    "gpu.power": 286, "gpu.fan_speed": 1480, "memory.usage": 62,
    "storage.temperature": 43, "network.download": 84.3, "network.upload": 11.8,
    "game.fps": 142, "game.fps_1_low": 97, "game.frametime": 7.1,
    "cooling.fan_speed": 1180, "cooling.pump_speed": 2460,
}

SAMPLE_HISTORY = {
    "cpu.usage": [32, 45, 51, 68, 57],
    "gpu.usage": [48, 64, 72, 81, 76],
    "game.frametime": [8.2, 7.8, 9.4, 6.9, 7.1, 10.2, 7.4, 6.8, 7.1],
}

DISPLAY_LABELS = {
    "0416:5408": "Trofeo Vision 9.16 — 1920×462",
    "0416:5302": "Trofeo Vision 6.86 — 1280×480",
    "custom": "Custom canvas",
}


def _theme_signature(theme: SensorTheme) -> str:
    return json.dumps(theme.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _image_to_pixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


class SensorThemeDocument(QObject):
    """Editable theme state with snapshot command history and safe persistence."""

    themeChanged = Signal(object)
    dirtyChanged = Signal(bool)
    historyChanged = Signal(bool, bool)

    def __init__(self, store: SensorThemeStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.theme: SensorTheme | None = None
        self.asset_root: Path | None = None
        self.built_in = False
        self._history: list[dict[str, object]] = []
        self._history_index = -1
        self._saved_signature = ""
        self._saved_raw: dict[str, object] | None = None
        self._interaction_before: dict[str, object] | None = None
        self.clipboard: list[dict[str, object]] = []

    @property
    def dirty(self) -> bool:
        return bool(self.theme and _theme_signature(self.theme) != self._saved_signature)

    @property
    def can_undo(self) -> bool:
        return self._history_index > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._history_index < len(self._history) - 1

    def _emit_state(self) -> None:
        self.dirtyChanged.emit(self.dirty)
        self.historyChanged.emit(self.can_undo, self.can_redo)

    def load(self, stored: StoredTheme) -> None:
        self.theme = SensorTheme.from_dict(stored.theme.to_dict())
        self.asset_root = stored.root
        self.built_in = stored.built_in
        snapshot = self.theme.to_dict()
        self._history = [deepcopy(snapshot)]
        self._history_index = 0
        self._saved_signature = _theme_signature(self.theme)
        self._saved_raw = deepcopy(snapshot)
        self._interaction_before = None
        self.themeChanged.emit(self.theme)
        self._emit_state()

    def new(self, name: str, preset: str = "0416:5408", *, width: int | None = None, height: int | None = None) -> SensorTheme:
        self.theme = self.store.create(name, preset=preset, width=width, height=height)
        self.asset_root = self.store.user_directory / self.theme.id
        self.built_in = False
        self._history = [deepcopy(self.theme.to_dict())]
        self._history_index = 0
        self._saved_signature = ""
        self._saved_raw = None
        self.themeChanged.emit(self.theme)
        self._emit_state()
        return self.theme

    def _replace(self, raw: dict[str, object], *, emit: bool = True) -> None:
        self.theme = SensorTheme.from_dict(deepcopy(raw))
        if emit:
            self.themeChanged.emit(self.theme)
            self._emit_state()

    def _record(self, before: dict[str, object]) -> bool:
        if self.theme is None or self.theme.to_dict() == before:
            return False
        self._history = self._history[:self._history_index + 1]
        self._history.append(deepcopy(self.theme.to_dict()))
        self._history_index += 1
        self.themeChanged.emit(self.theme)
        self._emit_state()
        return True

    def mutate(self, callback: Callable[[SensorTheme], None]) -> bool:
        if self.theme is None:
            return False
        before = deepcopy(self.theme.to_dict())
        callback(self.theme)
        # Reconstruct once so every edit passes the Phase 1 validator.
        self.theme = SensorTheme.from_dict(self.theme.to_dict())
        return self._record(before)

    def begin_interaction(self) -> None:
        if self.theme is not None and self._interaction_before is None:
            self._interaction_before = deepcopy(self.theme.to_dict())

    def end_interaction(self) -> bool:
        before, self._interaction_before = self._interaction_before, None
        return self._record(before) if before is not None else False

    def preview_changed(self) -> None:
        self.dirtyChanged.emit(self.dirty)

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        self._history_index -= 1
        self._replace(self._history[self._history_index])
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        self._history_index += 1
        self._replace(self._history[self._history_index])
        return True

    def discard_changes(self) -> bool:
        if self._saved_raw is None:
            return False
        snapshot = deepcopy(self._saved_raw)
        self._history = [deepcopy(snapshot)]; self._history_index = 0
        self._replace(snapshot)
        return True

    def element(self, element_id: str) -> ThemeElement | None:
        return next((item for item in self.theme.elements if item.id == element_id), None) if self.theme else None

    def _unique_element_id(self, base: str) -> str:
        existing = {item.id for item in self.theme.elements} if self.theme else set()
        clean = "".join(character if character.isalnum() else "-" for character in base.casefold()).strip("-") or "element"
        candidate = clean[:48]
        index = 2
        while candidate in existing:
            candidate = f"{clean[:44]}-{index}"
            index += 1
        return candidate

    def _resource_root_for_edit(self) -> Path:
        if self.theme is None:
            raise ThemeValidationError("no theme is open")
        if not self.built_in and self.asset_root is not None:
            root = self.asset_root
        else:
            root = self.store.user_directory / ".editor-work" / self.theme.id
            self.asset_root = root
        root.mkdir(parents=True, exist_ok=True)
        return root

    def ensure_placeholder_asset(self) -> str:
        relative = "assets/placeholder.png"
        target = self._resource_root_for_edit() / "assets" / "placeholder.png"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (160, 96), "#071522")
            image.save(target, "PNG")
        return relative

    def add_resource_file(self, source: Path, *, font: bool = False) -> str:
        source = Path(source)
        if not source.is_file():
            raise ThemeValidationError("selected resource does not exist")
        allowed = {".ttf", ".otf"} if font else {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        if source.suffix.casefold() not in allowed:
            raise ThemeValidationError("selected resource type is not supported")
        folder = "fonts" if font else "assets"
        destination_dir = self._resource_root_for_edit() / folder
        destination_dir.mkdir(parents=True, exist_ok=True)
        stem = "".join(character if character.isalnum() or character in "-_" else "-" for character in source.stem)[:48] or "resource"
        destination = destination_dir / f"{stem}{source.suffix.casefold()}"
        index = 2
        while destination.exists() and destination.resolve() != source.resolve():
            destination = destination_dir / f"{stem}-{index}{source.suffix.casefold()}"; index += 1
        if destination.resolve() != source.resolve(): shutil.copy2(source, destination)
        return f"{folder}/{destination.name}"

    def add_element(self, element_type: str, position: tuple[float, float] | None = None) -> ThemeElement:
        if self.theme is None or element_type not in ELEMENT_TYPES:
            raise ThemeValidationError(f"unsupported element type: {element_type}")
        x, y = position or (self.theme.canvas.width * .1, self.theme.canvas.height * .15)
        width, height = (260, 70)
        raw: dict[str, object] = {
            "id": self._unique_element_id(element_type), "name": FRIENDLY_ELEMENT_NAMES[element_type],
            "type": element_type, "x": round(x), "y": round(y), "width": width, "height": height,
        }
        if element_type == "text":
            raw.update(text="Your text", font_size=32, font_weight=600)
        elif element_type in {"sensor_value", "sensor_label", "sensor_label_value", "value_unit"}:
            raw.update(sensor_binding="cpu.usage", text="CPU USAGE" if element_type == "sensor_label" else "", font_size=30)
        elif element_type in {"image", "icon"}:
            raw.update(asset=self.ensure_placeholder_asset(), width=220, height=120)
        elif element_type in {"progress_bar", "progress_indicator", "horizontal_bar"}:
            raw.update(sensor_binding="cpu.usage", width=360, height=28, direction="left_to_right", corner_radius=12)
        elif element_type == "vertical_bar":
            raw.update(sensor_binding="cpu.usage", width=36, height=220, direction="bottom_to_top", corner_radius=12)
        elif element_type in {"ring_gauge", "arc_gauge"}:
            raw.update(sensor_binding="cpu.usage", width=220, height=220, thickness=18)
        elif element_type in {"line_graph", "area_graph"}:
            raw.update(sensor_binding="cpu.usage", width=440, height=180, fill=element_type=="area_graph", background_color="#071522", border_color="#164B67", border_width=1)
        elif element_type == "clock":
            raw.update(width=280, text="", font_size=42, font_weight=600, alignment="center")
        elif element_type == "date":
            raw.update(width=360, text="", font_size=26, alignment="center")
        elif element_type=="fps":raw.update(sensor_binding="game.fps",unit="FPS",width=240,font_size=38)
        elif element_type=="frametime":raw.update(sensor_binding="game.frametime",unit="ms",width=260,font_size=36,decimal_precision=1)
        element = ThemeElement.from_dict(raw)
        max_x = max(0, self.theme.canvas.width - element.width)
        max_y = max(0, self.theme.canvas.height - element.height)
        element.x, element.y = min(max_x, element.x), min(max_y, element.y)
        self.mutate(lambda theme: theme.elements.append(element))
        return self.element(element.id)

    def delete(self, element_ids: Iterable[str]) -> bool:
        selected = set(element_ids)
        return self.mutate(lambda theme: setattr(theme, "elements", [item for item in theme.elements if item.id not in selected]))

    def copy(self, element_ids: Iterable[str]) -> None:
        selected = set(element_ids)
        self.clipboard = [deepcopy(item.to_dict()) for item in self.theme.elements if item.id in selected] if self.theme else []

    def paste(self) -> list[str]:
        if not self.theme or not self.clipboard:
            return []
        created: list[ThemeElement] = []
        for raw in self.clipboard:
            item = dict(raw)
            item["id"] = self._unique_element_id(str(item.get("id", "element")))
            item["name"] = f"{item.get('name', 'Element')} Copy"
            item["x"] = min(self.theme.canvas.width - float(item["width"]), float(item["x"]) + 16)
            item["y"] = min(self.theme.canvas.height - float(item["height"]), float(item["y"]) + 16)
            created.append(ThemeElement.from_dict(item))
        self.mutate(lambda theme: theme.elements.extend(created))
        return [item.id for item in created]

    def duplicate_elements(self, element_ids: Iterable[str]) -> list[str]:
        self.copy(element_ids)
        return self.paste()

    def set_property(self, element_id: str, name: str, value: object) -> bool:
        current = self.element(element_id)
        if current is None or name not in applicable_element_fields(current.type):
            return False
        raw = current.to_dict()
        raw[name] = value
        replacement = ThemeElement.from_dict(raw)
        def apply(theme: SensorTheme) -> None:
            index = next(index for index, item in enumerate(theme.elements) if item.id == element_id)
            theme.elements[index] = replacement
        return self.mutate(apply)

    def reorder(self, element_ids: Iterable[str], operation: str) -> bool:
        selected = set(element_ids)
        if not self.theme or not selected:
            return False
        def apply(theme: SensorTheme) -> None:
            values = [item.z_index for item in theme.elements] or [0]
            for item in theme.elements:
                if item.id not in selected:
                    continue
                if operation == "front": item.z_index = max(values) + 1
                elif operation == "back": item.z_index = min(values) - 1
                elif operation == "forward": item.z_index += 1
                elif operation == "backward": item.z_index -= 1
        return self.mutate(apply)

    def align(self, element_ids: Iterable[str], operation: str) -> bool:
        selected_ids = set(element_ids)
        selected = [item for item in self.theme.elements if item.id in selected_ids] if self.theme else []
        if len(selected) < 2:
            return False
        if operation not in {"left", "hcenter", "right", "top", "vcenter", "bottom", "distribute_h", "distribute_v"}:
            raise ThemeValidationError(f"unsupported alignment operation: {operation}")

        def apply(_theme: SensorTheme) -> None:
            left = min(item.x for item in selected); right = max(item.x + item.width for item in selected)
            top = min(item.y for item in selected); bottom = max(item.y + item.height for item in selected)
            if operation == "left":
                for item in selected: item.x = left
            elif operation == "hcenter":
                center = (left + right) / 2
                for item in selected: item.x = center - item.width / 2
            elif operation == "right":
                for item in selected: item.x = right - item.width
            elif operation == "top":
                for item in selected: item.y = top
            elif operation == "vcenter":
                center = (top + bottom) / 2
                for item in selected: item.y = center - item.height / 2
            elif operation == "bottom":
                for item in selected: item.y = bottom - item.height
            elif operation == "distribute_h":
                ordered = sorted(selected, key=lambda item: item.x)
                gap = (right - left - sum(item.width for item in ordered)) / (len(ordered) - 1)
                cursor = left
                for item in ordered: item.x, cursor = cursor, cursor + item.width + gap
            else:
                ordered = sorted(selected, key=lambda item: item.y)
                gap = (bottom - top - sum(item.height for item in ordered)) / (len(ordered) - 1)
                cursor = top
                for item in ordered: item.y, cursor = cursor, cursor + item.height + gap
        return self.mutate(apply)

    def set_flag(self, element_ids: Iterable[str], name: str, value: bool) -> bool:
        selected = set(element_ids)
        return self.mutate(lambda theme: [setattr(item, name, bool(value)) for item in theme.elements if item.id in selected])

    def change_canvas(self, preset: str, *, width: int | None = None, height: int | None = None, scale: bool = True) -> bool:
        if self.theme is None:
            return False
        if preset in DISPLAY_PRESETS:
            width, height = DISPLAY_PRESETS[preset]
        if width is None or height is None:
            raise ThemeValidationError("custom canvas requires width and height")
        old_width, old_height = self.theme.canvas.width, self.theme.canvas.height
        def apply(theme: SensorTheme) -> None:
            if scale:
                sx, sy = width / old_width, height / old_height
                for item in theme.elements:
                    item.x *= sx; item.y *= sy; item.width *= sx; item.height *= sy
                    if item.type in {"text", "sensor_value", "sensor_label", "clock", "date"}:
                        item.font_size = max(1, item.font_size * min(sx, sy))
            theme.canvas = ThemeCanvas(width, height, preset, theme.canvas.scale_mode)
        return self.mutate(apply)

    def _copy_resources(self, destination: Path) -> None:
        if self.theme is None:
            return
        references = {value for element in self.theme.elements for value in (element.asset, element.font_file) if value}
        if self.theme.background_asset: references.add(self.theme.background_asset)
        for reference in references:
            source = self.asset_root.joinpath(*reference.split("/")) if self.asset_root else None
            target = destination.joinpath(*reference.split("/"))
            if source is None or not source.is_file():
                raise ThemeValidationError(f"referenced theme resource is missing: {reference}")
            if source.resolve() == target.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def save(self) -> Path:
        if self.theme is None:
            raise ThemeValidationError("no theme is open")
        if self.built_in:
            raise ThemeValidationError("built-in themes require Save As")
        destination = self.store.user_directory / self.theme.id
        self._copy_resources(destination)
        target = self.store.save(self.theme)
        self.asset_root = destination
        self._saved_signature = _theme_signature(self.theme)
        self._saved_raw = deepcopy(self.theme.to_dict())
        self._emit_state()
        return target

    def save_as(self, name: str) -> Path:
        if self.theme is None:
            raise ThemeValidationError("no theme is open")
        identity = self.store.create(name, preset=self.theme.canvas.preset, width=self.theme.canvas.width, height=self.theme.canvas.height)
        raw = self.theme.to_dict(); raw["id"] = identity.id; raw["name"] = name
        replacement = SensorTheme.from_dict(raw)
        destination = self.store.user_directory / replacement.id
        old_theme, old_root = self.theme, self.asset_root
        self.theme = replacement
        try:
            self.asset_root = old_root
            self._copy_resources(destination)
            target = self.store.save(replacement)
        except Exception:
            self.theme, self.asset_root = old_theme, old_root
            raise
        self.asset_root = destination
        self.built_in = False
        self._history = [deepcopy(replacement.to_dict())]
        self._history_index = 0
        self._saved_signature = _theme_signature(replacement)
        self._saved_raw = deepcopy(replacement.to_dict())
        self.themeChanged.emit(replacement)
        self._emit_state()
        return target

    def duplicate_theme(self, name: str) -> Path:
        return self.save_as(name)

    def rename(self, name: str) -> SensorTheme:
        if self.theme is None or self.built_in:
            raise ThemeValidationError("only user themes can be renamed")
        renamed = self.store.rename(self.theme.id, name)
        self.load(self.store.get(renamed.id))
        return renamed

    def delete_theme(self) -> None:
        if self.theme is None:
            return
        self.store.delete(self.theme.id)

    def import_package(self, path: Path) -> SensorTheme:
        imported = self.store.import_package(path)
        self.load(self.store.get(imported.id))
        return imported

    def export_package(self, path: Path, renderer: SensorThemeRenderer | None = None) -> Path:
        if self.theme is None:
            raise ThemeValidationError("no theme is open")
        preview = (renderer or SensorThemeRenderer()).thumbnail(self.theme, SAMPLE_SENSOR_VALUES, asset_root=self.asset_root)
        return export_theme_package(self.theme, path, asset_root=self.asset_root, preview=preview)

    def import_json(self, path: Path) -> SensorTheme:
        path=Path(path)
        if not path.is_file() or path.stat().st_size>2*1024*1024:raise ThemeValidationError("layout JSON is missing or exceeds 2 MB")
        try:raw=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc:raise ThemeValidationError(f"invalid layout JSON: {exc}") from exc
        theme=SensorTheme.from_dict(raw);self.theme=theme;self.asset_root=path.parent;self.built_in=False
        snapshot=theme.to_dict();self._history=[deepcopy(snapshot)];self._history_index=0;self._saved_signature=_theme_signature(theme);self._saved_raw=deepcopy(snapshot);self.themeChanged.emit(theme);self._emit_state();return theme

    def export_json(self, path: Path) -> Path:
        if self.theme is None:
            raise ThemeValidationError("no layout is open")
        target = Path(path)
        if target.suffix.casefold() != ".json":
            target = target.with_suffix(".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._copy_resources(target.parent)
        target.write_text(json.dumps(self.theme.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def import_background(self, path: Path) -> str:
        relative=self.add_resource_file(path)
        self.mutate(lambda theme:(setattr(theme,"background_asset",relative),setattr(theme,"background_locked",True)))
        return relative


class SensorThemeElementItem(QGraphicsRectItem):
    HANDLE_SIZE = 20
    ROTATE_OFFSET = 32

    def __init__(self, element: ThemeElement, editor_scene: "SensorThemeScene") -> None:
        super().__init__(0, 0, element.width, element.height)
        self.element = element
        self.editor_scene = editor_scene
        self.active_handle: str | None = None
        self.drag_origin: tuple[QPointF, QRectF, QPointF] | None = None
        self.setPos(element.x, element.y)
        self.setZValue(element.z_index)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges | QGraphicsItem.ItemIsFocusable)
        self.setFlag(QGraphicsItem.ItemIsMovable, not element.locked)
        self.setVisible(element.visible)
        self.setToolTip("Drag to move · drag a handle to resize · top handle rotates")

    def _handles(self) -> dict[str, QRectF]:
        r, size = self.rect(), self.HANDLE_SIZE
        half = size / 2
        points = {
            "nw": r.topLeft(), "n": QPointF(r.center().x(), r.top()), "ne": r.topRight(),
            "e": QPointF(r.right(), r.center().y()), "se": r.bottomRight(),
            "s": QPointF(r.center().x(), r.bottom()), "sw": r.bottomLeft(),
            "w": QPointF(r.left(), r.center().y()),
            "rotate": QPointF(r.center().x(), r.top() - self.ROTATE_OFFSET),
        }
        return {name: QRectF(point.x() - half, point.y() - half, size, size) for name, point in points.items()}

    def boundingRect(self) -> QRectF:
        return self.rect().adjusted(-self.HANDLE_SIZE, -self.ROTATE_OFFSET - self.HANDLE_SIZE, self.HANDLE_SIZE, self.HANDLE_SIZE)

    def shape(self) -> QPainterPath:
        path=QPainterPath();path.addRect(self.boundingRect());return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        selected = self.isSelected()
        if not selected and not self.element.locked:
            return
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#6FE7FF" if selected else "#FFD166"), 3 if selected else 1, Qt.SolidLine if selected else Qt.DashLine))
        painter.drawRect(self.rect())
        if self.element.locked:
            painter.setPen(QColor("#FFD166")); painter.drawText(self.rect().adjusted(5, 5, -5, -5), Qt.AlignRight | Qt.AlignTop, "LOCKED")
        if selected and not self.element.locked:
            painter.setPen(QPen(QColor("#6FE7FF"), 2)); painter.drawLine(self.rect().center().x(), self.rect().top(), self.rect().center().x(), self.rect().top() - self.ROTATE_OFFSET)
            for name, handle in self._handles().items():
                painter.setBrush(QColor("#FFB020" if name == "rotate" else "#EAFBFF"))
                painter.setPen(QPen(QColor("#075F8B"), 1)); painter.drawEllipse(handle) if name == "rotate" else painter.drawRect(handle)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() and not self.element.locked:
            point = self.editor_scene.snap_position(self, QPointF(value))
            point.setX(max(0, min(self.editor_scene.document.theme.canvas.width - self.element.width, point.x())))
            point.setY(max(0, min(self.editor_scene.document.theme.canvas.height - self.element.height, point.y())))
            return point
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.element.x, self.element.y = round(self.pos().x(), 3), round(self.pos().y(), 3)
            self.editor_scene.mark_preview_dirty()
            self.editor_scene.document.preview_changed()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            QTimer.singleShot(0, self.editor_scene.emit_selection)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        self.editor_scene.document.begin_interaction()
        if not self.element.locked and self.isSelected():
            self.active_handle = next((name for name, area in self._handles().items() if area.contains(event.pos())), None)
        if self.active_handle:
            self.drag_origin = (event.scenePos(), QRectF(self.rect()), QPointF(self.pos()))
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self.active_handle or self.drag_origin is None:
            super().mouseMoveEvent(event); return
        start, original_rect, original_pos = self.drag_origin
        delta = event.scenePos() - start
        if self.active_handle == "rotate":
            center = self.mapToScene(original_rect.center())
            self.element.rotation = round(math.degrees(math.atan2(event.scenePos().y() - center.y(), event.scenePos().x() - center.x())) + 90, 1)
        else:
            left, top, right, bottom = 0.0, 0.0, original_rect.width(), original_rect.height()
            if "w" in self.active_handle: left = min(right - 10, delta.x())
            if "e" in self.active_handle: right = max(left + 10, original_rect.width() + delta.x())
            if "n" in self.active_handle: top = min(bottom - 10, delta.y())
            if "s" in self.active_handle: bottom = max(top + 10, original_rect.height() + delta.y())
            grid = self.editor_scene.grid_size if self.editor_scene.snap_enabled else 1
            left, top, right, bottom = (round(value / grid) * grid for value in (left, top, right, bottom))
            new_x, new_y = original_pos.x() + left, original_pos.y() + top
            max_width = self.editor_scene.document.theme.canvas.width - new_x
            max_height = self.editor_scene.document.theme.canvas.height - new_y
            width, height = max(10, min(max_width, right - left)), max(10, min(max_height, bottom - top))
            self.prepareGeometryChange(); self.setRect(0, 0, width, height); self.setPos(new_x, new_y)
            self.element.width, self.element.height = round(width, 3), round(height, 3)
        self.editor_scene.mark_preview_dirty(); self.editor_scene.document.preview_changed(); self.update(); event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.active_handle:
            self.active_handle = None; self.drag_origin = None; event.accept()
        else:
            super().mouseReleaseEvent(event)
        self.editor_scene.guides = []; self.editor_scene.update()
        self.editor_scene.document.end_interaction()


class SensorThemeScene(QGraphicsScene):
    selectionIdsChanged = Signal(object)

    def __init__(self, document: SensorThemeDocument, parent: QObject | None = None, *, now_provider: Callable[[], datetime] | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.renderer = SensorThemeRenderer()
        self.values: object = SAMPLE_SENSOR_VALUES
        self.history = SAMPLE_HISTORY
        self.now_provider = now_provider
        self.items_by_id: dict[str, SensorThemeElementItem] = {}
        self.grid_enabled = True
        self.snap_enabled = True
        self.grid_size = 40
        self.alignment_guides = True
        self.guides: list[tuple[str, float]] = []
        self._preview_cache: QImage | None = None
        self.reload()

    def reload(self, selected_ids: Iterable[str] = ()) -> None:
        selected = set(selected_ids)
        self.clear(); self.items_by_id = {}; self._preview_cache = None
        if self.document.theme is None:
            return
        canvas = self.document.theme.canvas
        self.setSceneRect(0, 0, canvas.width, canvas.height)
        for element in self.document.theme.elements:
            item = SensorThemeElementItem(element, self)
            self.addItem(item); self.items_by_id[element.id] = item
            item.setSelected(element.id in selected)
        self.invalidate(self.sceneRect(), QGraphicsScene.BackgroundLayer)

    def selected_ids(self) -> list[str]:
        return [item.element.id for item in self.selectedItems() if isinstance(item, SensorThemeElementItem)]

    def select_ids(self, element_ids: Iterable[str]) -> None:
        selected = set(element_ids)
        for element_id, item in self.items_by_id.items(): item.setSelected(element_id in selected)
        self.emit_selection()

    def emit_selection(self) -> None:
        self.selectionIdsChanged.emit(self.selected_ids())

    def mark_preview_dirty(self) -> None:
        self._preview_cache = None
        self.invalidate(self.sceneRect(), QGraphicsScene.BackgroundLayer)
        self.update()

    def set_values(self, values: object) -> None:
        self.values = values; self.mark_preview_dirty()

    def snap_position(self, item: SensorThemeElementItem, point: QPointF) -> QPointF:
        self.guides = []
        if not self.snap_enabled:
            return point
        if self.grid_enabled and self.grid_size > 1:
            point.setX(round(point.x() / self.grid_size) * self.grid_size)
            point.setY(round(point.y() / self.grid_size) * self.grid_size)
        threshold = max(3, self.grid_size * .6)
        width, height = item.element.width, item.element.height
        canvas = self.document.theme.canvas
        x_targets = [(0, "edge"), ((canvas.width - width) / 2, "center"), (canvas.width - width, "edge")]
        y_targets = [(0, "edge"), ((canvas.height - height) / 2, "center"), (canvas.height - height, "edge")]
        for other in self.items_by_id.values():
            if other is item or not other.element.visible: continue
            box = other.sceneBoundingRect()
            x_targets.extend(((box.left(), "edge"), (box.center().x() - width / 2, "center"), (box.right() - width, "edge")))
            y_targets.extend(((box.top(), "edge"), (box.center().y() - height / 2, "center"), (box.bottom() - height, "edge")))
        closest_x = min(x_targets, key=lambda target: abs(point.x() - target[0]))
        closest_y = min(y_targets, key=lambda target: abs(point.y() - target[0]))
        if abs(point.x() - closest_x[0]) <= threshold:
            point.setX(closest_x[0]); self.guides.append(("v", point.x() + width / 2 if closest_x[1] == "center" else point.x()))
        if abs(point.y() - closest_y[0]) <= threshold:
            point.setY(closest_y[0]); self.guides.append(("h", point.y() + height / 2 if closest_y[1] == "center" else point.y()))
        return point

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        if self.document.theme is None:
            return
        if self._preview_cache is None:
            try:
                image = self.renderer.render(
                    self.document.theme, self.values, history=self.history,
                    asset_root=self.document.asset_root,
                    now=self.now_provider() if self.now_provider else None,
                )
                pixmap = _image_to_pixmap(image)
                self._preview_cache = pixmap.toImage()
            except Exception as exc:
                self._preview_cache = QImage(self.document.theme.canvas.width, self.document.theme.canvas.height, QImage.Format_RGB32)
                self._preview_cache.fill(QColor("#22070B"))
                painter.drawText(self.sceneRect(), Qt.AlignCenter, f"Preview error: {exc}")
        painter.drawImage(self.sceneRect(), self._preview_cache)
        if self.grid_enabled and self.grid_size > 1:
            painter.setPen(QPen(QColor(50, 183, 232, 42), 0))
            canvas_rect = rect.intersected(self.sceneRect())
            x = math.floor(canvas_rect.left() / self.grid_size) * self.grid_size
            while x <= canvas_rect.right(): painter.drawLine(QPointF(x, canvas_rect.top()), QPointF(x, canvas_rect.bottom())); x += self.grid_size
            y = math.floor(canvas_rect.top() / self.grid_size) * self.grid_size
            while y <= canvas_rect.bottom(): painter.drawLine(QPointF(canvas_rect.left(), y), QPointF(canvas_rect.right(), y)); y += self.grid_size
        painter.setBrush(Qt.NoBrush); painter.setPen(QPen(QColor("#2BC8FF"), 3)); painter.drawRect(self.sceneRect())

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if not self.alignment_guides:
            return
        painter.setPen(QPen(QColor("#FF4FC8"), 2, Qt.DashLine))
        for orientation, position in self.guides:
            painter.drawLine(QPointF(position, 0), QPointF(position, self.sceneRect().height())) if orientation == "v" else painter.drawLine(QPointF(0, position), QPointF(self.sceneRect().width(), position))

    def keyPressEvent(self, event) -> None:
        selected = self.selected_ids()
        if event.matches(QKeySequence.Copy): self.document.copy(selected); event.accept(); return
        if event.matches(QKeySequence.Paste):
            created = self.document.paste(); QTimer.singleShot(0, lambda: self.select_ids(created)); event.accept(); return
        if event.key() == Qt.Key_Delete: self.document.delete(selected); event.accept(); return
        if event.key() == Qt.Key_D and event.modifiers() & Qt.ControlModifier:
            created = self.document.duplicate_elements(selected); QTimer.singleShot(0, lambda: self.select_ids(created)); event.accept(); return
        movement = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(event.key())
        if movement and selected:
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            self.document.begin_interaction()
            for element_id in selected:
                item = self.items_by_id.get(element_id)
                if item and not item.element.locked: item.setPos(item.pos().x() + movement[0] * step, item.pos().y() + movement[1] * step)
            self.document.end_interaction(); event.accept(); return
        super().keyPressEvent(event)


class SensorThemeCanvasView(QGraphicsView):
    elementDropped = Signal(str, object)

    def __init__(self, scene: SensorThemeScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QColor("#02060A"))
        self.setMinimumSize(520, 280)

    def fit_canvas(self) -> None:
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        self.scale(factor, factor)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        self.scene().drawBackground(painter, rect)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        self.scene().drawForeground(painter, rect)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not getattr(self, "manual_zoom", False): self.fit_canvas()

    def wheelEvent(self, event) -> None:
        self.manual_zoom = True; self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15); event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton:
            self._pan_start = event.position(); self.setCursor(Qt.ClosedHandCursor); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if hasattr(self, "_pan_start"):
            delta = event.position() - self._pan_start; self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton and hasattr(self, "_pan_start"):
            del self._pan_start; self.unsetCursor(); event.accept(); return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-oni-sensor-element"): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-oni-sensor-element"): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-oni-sensor-element"):
            kind = bytes(event.mimeData().data("application/x-oni-sensor-element")).decode("utf-8")
            point = self.mapToScene(event.position().toPoint())
            self.elementDropped.emit(kind, (point.x(), point.y())); event.acceptProposedAction(); return
        super().dropEvent(event)


class ElementPalette(QListWidget):
    addRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SingleSelection); self.setDragEnabled(True)
        for kind in sorted(ELEMENT_TYPES, key=lambda value: FRIENDLY_ELEMENT_NAMES[value]):
            item = QListWidgetItem(FRIENDLY_ELEMENT_NAMES[kind]); item.setData(Qt.UserRole, kind); self.addItem(item)
        self.itemDoubleClicked.connect(lambda item: self.addRequested.emit(item.data(Qt.UserRole)))

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None: return
        mime = QMimeData(); mime.setData("application/x-oni-sensor-element", QByteArray(item.data(Qt.UserRole).encode("utf-8")))
        drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.CopyAction)


class ThemeColorField(QWidget):
    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        self.edit = QLineEdit(); self.button = QPushButton("●"); self.button.setFixedWidth(34)
        row.addWidget(self.edit, 1); row.addWidget(self.button)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.edit.text()))
        self.button.clicked.connect(self.choose)

    def setText(self, value: str) -> None:
        self.edit.setText(str(value)); self._swatch()

    def text(self) -> str: return self.edit.text()

    def _swatch(self) -> None:
        color = QColor(self.edit.text())
        self.button.setStyleSheet(f"color: {color.name() if color.isValid() else '#ffffff'}")

    def choose(self) -> None:
        initial = QColor(self.edit.text())
        color = QColorDialog.getColor(initial if initial.isValid() else QColor("white"), self, "Choose color", QColorDialog.ShowAlphaChannel)
        if color.isValid():
            value = color.name(QColor.HexArgb) if color.alpha() < 255 else color.name()
            # QColor writes #AARRGGBB; Phase 1 uses #RRGGBBAA.
            if len(value) == 9: value = f"#{value[3:]}{value[1:3]}"
            self.setText(value); self.changed.emit(value)


class SensorThemeProperties(QScrollArea):
    propertyChanged = Signal(str, object)
    resourceRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.element: ThemeElement | None = None; self.loading = False
        self.controls: dict[str, QWidget] = {}; self.rows: dict[str, tuple[QLabel, QWidget]] = {}; self.groups: dict[str, QGroupBox] = {}; self.field_groups: dict[str, str] = {}
        body = QWidget(); outer = QVBoxLayout(body); outer.setContentsMargins(8, 8, 8, 8); outer.setSpacing(8)
        self.title = QLabel("Select an element"); self.title.setObjectName("inspectorTitle"); self.title.setWordWrap(True); outer.addWidget(self.title)
        self._group(outer, "Geometry")
        self._line("name", "Name"); self._double("x", "X", -8192, 8192); self._double("y", "Y", -8192, 8192)
        self._double("width", "Width", 1, 8192); self._double("height", "Height", 1, 8192)
        self._double("rotation", "Rotation", -3600, 3600); self._double("opacity", "Opacity", 0, 1, .05, 2)
        self._check("visible", "Visible"); self._check("locked", "Locked"); self._spin("z_index", "Layer order", -1000000, 1000000)

        self._group(outer, "Typography")
        self._line("text", "Text"); self._font("font_family", "Font"); self._resource("font_file", "Packaged font", "font")
        self._double("font_size", "Font size", 1, 512); self._spin("font_weight", "Weight", 100, 900)
        self._check("italic", "Italic"); self._combo("alignment", "Alignment", (("Left", "left"), ("Center", "center"), ("Right", "right")))
        self._combo("vertical_alignment", "Vertical align", (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")))
        self._double("letter_spacing", "Letter spacing", -50, 100, .5); self._color("text_color", "Text color")
        self._double("padding", "Padding", 0, 1000); self._color("text_outline_color", "Outline color"); self._double("text_outline_width", "Outline width", 0, 100)
        self._line("time_format", "Time format"); self._line("date_format", "Date format")

        self._group(outer, "Appearance")
        self._color("foreground_color", "Foreground"); self._color("background_color", "Background")
        self._color("border_color", "Border color"); self._double("border_width", "Border width", 0, 100)
        self._double("corner_radius", "Corner radius", 0, 4096); self._check("shadow", "Shadow")
        self._color("shadow_color", "Shadow color"); self._double("shadow_offset_x", "Shadow X", -100, 100)
        self._double("shadow_offset_y", "Shadow Y", -100, 100); self._double("shadow_blur", "Shadow blur", 0, 100)
        self._check("glow", "Glow"); self._color("glow_color", "Glow color"); self._double("glow_strength", "Glow strength", 0, 100)

        self._group(outer, "Animation")
        self._combo("animation", "Animation", (("None", "none"), ("Smooth", "smooth"), ("Fade", "fade"), ("Pulse", "pulse")))
        self._double("animation_duration", "Duration", .05, 10, .05, 2)

        self._group(outer, "Sensor")
        self._sensor_combo(); self._line("unit", "Unit"); self._spin("decimal_precision", "Decimals", 0, 8)
        self._line("prefix", "Prefix"); self._line("suffix", "Suffix"); self._line("unavailable_text", "Unavailable text")
        self._double("minimum", "Minimum", -1000000, 1000000); self._double("maximum", "Maximum", -1000000, 1000000)
        self._optional("warning_threshold", "Warning threshold"); self._optional("critical_threshold", "Critical threshold")
        self._color("value_color", "Value color"); self._color("warning_color", "Warning color"); self._color("critical_color", "Critical color")

        self._group(outer, "Gauge / Bar")
        self._double("thickness", "Thickness", 1, 1000); self._double("start_angle", "Start angle", -3600, 3600)
        self._double("end_angle", "End angle", -3600, 3600)
        self._combo("direction", "Direction", (("Clockwise", "clockwise"), ("Counterclockwise", "counterclockwise"), ("Left to right", "left_to_right"), ("Right to left", "right_to_left"), ("Bottom to top", "bottom_to_top"), ("Top to bottom", "top_to_bottom")))
        self._color("track_color", "Track color")

        self._group(outer, "Graph")
        self._double("history_duration", "History seconds", 1, 86400); self._double("line_width", "Line width", 1, 100)
        self._check("fill", "Fill graph"); self._color("fill_color", "Fill color"); self._check("smoothing", "Smooth line")
        self._check("automatic_scale", "Automatic scale"); self._double("scale_min", "Scale minimum", -1000000, 1000000)
        self._double("scale_max", "Scale maximum", -1000000, 1000000)

        self._group(outer, "Image")
        self._resource("asset", "Image asset", "image")
        self._combo("image_fit", "Fit", (("Contain", "contain"), ("Cover", "cover"), ("Stretch", "stretch"), ("Crop", "crop")))
        self._line("crop", "Crop L,T,R,B")
        outer.addStretch(); self.setWidget(body); self.setWidgetResizable(True); self.setMinimumWidth(300); self.setMaximumWidth(370)

    def _group(self, outer: QVBoxLayout, title: str) -> None:
        group = QGroupBox(title); form = QFormLayout(group); form.setContentsMargins(8, 8, 8, 8); form.setSpacing(6)
        self.groups[title] = group; self.current_group = title; self.form = form; outer.addWidget(group)

    def _row(self, name: str, label: str, widget: QWidget) -> QWidget:
        title = QLabel(label); self.form.addRow(title, widget); self.controls[name] = widget; self.rows[name] = (title, widget); self.field_groups[name] = self.current_group; return widget

    def _line(self, name: str, label: str) -> None:
        widget = self._row(name, label, QLineEdit()); widget.editingFinished.connect(lambda n=name: self._commit(n))

    def _optional(self, name: str, label: str) -> None:
        self._line(name, label); self.controls[name].setPlaceholderText("Not set")

    def _spin(self, name: str, label: str, low: int, high: int) -> None:
        widget = QSpinBox(); widget.setRange(low, high); self._row(name, label, widget); widget.editingFinished.connect(lambda n=name: self._commit(n))

    def _double(self, name: str, label: str, low: float, high: float, step: float = 1, decimals: int = 2) -> None:
        widget = QDoubleSpinBox(); widget.setRange(low, high); widget.setSingleStep(step); widget.setDecimals(decimals)
        self._row(name, label, widget); widget.editingFinished.connect(lambda n=name: self._commit(n))

    def _check(self, name: str, label: str) -> None:
        widget = QCheckBox(); self._row(name, label, widget); widget.toggled.connect(lambda _value, n=name: self._commit(n))

    def _combo(self, name: str, label: str, values: Iterable[tuple[str, str]]) -> None:
        widget = QComboBox()
        for text, value in values: widget.addItem(text, value)
        self._row(name, label, widget); widget.currentIndexChanged.connect(lambda _index, n=name: self._commit(n))

    def _font(self, name: str, label: str) -> None:
        widget = QFontComboBox(); self._row(name, label, widget); widget.currentFontChanged.connect(lambda _font, n=name: self._commit(n))

    def _color(self, name: str, label: str) -> None:
        widget = ThemeColorField(); self._row(name, label, widget); widget.changed.connect(lambda _value, n=name: self._commit(n))

    def _resource(self, name: str, label: str, kind: str) -> None:
        container = QWidget(); row = QHBoxLayout(container); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        edit = QLineEdit(); edit.setReadOnly(True); choose = QPushButton("Choose…"); choose.setToolTip("Copy a resource into this user theme")
        row.addWidget(edit, 1); row.addWidget(choose); self._row(name, label, container); container._editor = edit
        choose.clicked.connect(lambda _checked=False, resource_kind=kind: self.resourceRequested.emit(resource_kind))

    def _sensor_combo(self) -> None:
        widget = QComboBox(); current_group = None
        for binding in SUPPORTED_SENSOR_BINDINGS:
            group = binding.split(".", 1)[0].title()
            if group != current_group:
                widget.addItem(f"— {group} —", None); widget.model().item(widget.count() - 1).setEnabled(False); current_group = group
            widget.addItem(FRIENDLY_SENSOR_NAMES.get(binding, binding), binding)
        self._row("sensor_binding", "Sensor", widget); widget.currentIndexChanged.connect(lambda _index: self._commit("sensor_binding"))

    def set_element(self, element: ThemeElement | None) -> None:
        self.element = element; self.loading = True
        self.title.setText(f"{FRIENDLY_ELEMENT_NAMES[element.type]} · {element.name}" if element else "Select an element")
        applicable = applicable_element_fields(element.type) | {"name"} if element else set()
        for name, (label, container) in self.rows.items():
            shown = name in applicable; label.setVisible(shown); container.setVisible(shown)
            if not shown or element is None: continue
            value = getattr(element, name)
            control = self.controls[name]
            if hasattr(control, "_editor"): control._editor.setText(str(value))
            elif isinstance(control, ThemeColorField): control.setText(str(value))
            elif isinstance(control, QLineEdit): control.setText(json.dumps(value) if name == "crop" else "" if value is None else str(value))
            elif isinstance(control, QFontComboBox): control.setCurrentFont(QFont(str(value)))
            elif isinstance(control, QComboBox):
                index = control.findData(value); control.setCurrentIndex(index if index >= 0 else 0)
            elif isinstance(control, QCheckBox): control.setChecked(bool(value))
            else: control.setValue(value)
        for title, group in self.groups.items():
            group.setVisible(any(name in applicable and self.field_groups[name] == title for name in self.rows))
        self.loading = False

    def _value(self, name: str) -> object:
        control = self.controls[name]
        if isinstance(control, ThemeColorField): return control.text()
        if isinstance(control, QLineEdit):
            text = control.text().strip()
            if name in {"warning_threshold", "critical_threshold"}: return None if not text else float(text)
            if name == "crop": return json.loads(text)
            return text
        if isinstance(control, QFontComboBox): return control.currentFont().family()
        if isinstance(control, QComboBox): return control.currentData()
        if isinstance(control, QCheckBox): return control.isChecked()
        return control.value()

    def _commit(self, name: str) -> None:
        if self.loading or self.element is None: return
        try: self.propertyChanged.emit(name, self._value(name))
        except (ValueError, json.JSONDecodeError): self.set_element(self.element)


class SensorThemeEditorPage(QWidget):
    """Complete embedded Sensor Themes page; never touches device/session state."""

    def __init__(
        self, store: SensorThemeStore | None = None, parent: QWidget | None = None,
        *, live_value_provider: Callable[[], object] | None = None,
        apply_handler: Callable[[SensorTheme, Path | None, tuple[str, ...], int], object] | None = None,
        deployment_handler: Callable[[str, SensorTheme | None, Path | None, str], object] | None = None,
        prompt_handler: Callable[[str], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("oniSensorStudio")
        self.store = store or SensorThemeStore()
        self.document = SensorThemeDocument(self.store, self)
        self.live_value_provider = live_value_provider
        self.apply_handler = apply_handler
        self.deployment_handler = deployment_handler
        self.prompt_handler = prompt_handler
        self.now_provider = now_provider
        self._refresh_pending = False
        self._sensor_availability: dict[str, bool] = {}

        # Sensor Studio owns only editor state. DisplaySession, transport and media
        # ownership remain in the main application/runtime.
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ---- title / document state -------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("ONI SENSOR STUDIO")
        title.setObjectName("studioTitle")
        subtitle = QLabel("Design the LCD exactly as it will appear on the panel")
        subtitle.setObjectName("studioMuted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.dirty_label = QLabel("Saved")
        self.dirty_label.setObjectName("studioState")
        header.addWidget(self.dirty_label)
        root.addLayout(header)

        # ---- compact command bar ----------------------------------------------------
        command = QFrame()
        command.setObjectName("studioBar")
        command_layout = QHBoxLayout(command)
        command_layout.setContentsMargins(8, 7, 8, 7)
        command_layout.setSpacing(6)
        self.actions: dict[str, QPushButton] = {}
        for label, callback in (
            ("New", self.new_theme), ("Open", self.open_theme), ("Save", self.save),
            ("Save As", self.save_as), ("Import JSON", self.import_theme),
            ("Export JSON", self.export_theme), ("Undo", self.document.undo),
            ("Redo", self.document.redo),
        ):
            button = QPushButton(label)
            button.setObjectName("studioCommand")
            button.clicked.connect(callback)
            command_layout.addWidget(button)
            self.actions[label.replace(" JSON", "")] = button
        # Compatibility keys used by history_changed and older tests/callers.
        self.actions["Import"] = self.actions.get("Import", self.actions.get("Import JSON", button))
        self.actions["Export"] = self.actions.get("Export", self.actions.get("Export JSON", button))
        bg_button = QPushButton("Background")
        bg_button.setObjectName("studioAccent")
        bg_button.clicked.connect(self.import_background)
        command_layout.addWidget(bg_button)
        self.actions["Import Background"] = bg_button
        command_layout.addStretch(1)
        self.preset = QComboBox()
        for key, label in DISPLAY_LABELS.items():
            self.preset.addItem(label, key)
        self.preset.setMinimumWidth(225)
        command_layout.addWidget(self.preset)
        self.preview_mode = QComboBox()
        self.preview_mode.addItems(("Sample Data", "Live Sensors", "Missing Data"))
        self.preview_mode.setMinimumWidth(125)
        command_layout.addWidget(self.preview_mode)
        root.addWidget(command)

        # ---- left toolbox: only things users add/manage -----------------------------
        self.left_tabs = QTabWidget()
        self.left_tabs.setObjectName("studioLeftTabs")
        self.left_tabs.setMinimumWidth(270)
        self.left_tabs.setMaximumWidth(330)

        sensors_page = QWidget()
        sensors_layout = QVBoxLayout(sensors_page)
        sensors_layout.setContentsMargins(8, 10, 8, 8)
        sensors_layout.setSpacing(7)
        sensors_layout.addWidget(QLabel("SENSORS"))
        sensor_help = QLabel("Search a sensor, then bind it to the selected widget.")
        sensor_help.setWordWrap(True); sensor_help.setObjectName("studioMuted")
        sensors_layout.addWidget(sensor_help)
        self.sensor_search = QLineEdit(); self.sensor_search.setPlaceholderText("Search CPU, GPU, FPS, temperature…")
        self.sensor_category = QComboBox(); self.sensor_category.addItems(("All", "CPU", "GPU", "Memory", "Storage", "Network", "Cooling", "Game/FPS"))
        self.sensor_list = QListWidget(); self.sensor_list.setObjectName("studioBrowser")
        self.sensor_bind_button = QPushButton("Bind sensor to selected widget"); self.sensor_bind_button.setObjectName("studioAccent")
        self.sensor_refresh_button = QPushButton("Refresh availability")
        sensors_layout.addWidget(self.sensor_search); sensors_layout.addWidget(self.sensor_category)
        sensors_layout.addWidget(self.sensor_list, 1); sensors_layout.addWidget(self.sensor_bind_button); sensors_layout.addWidget(self.sensor_refresh_button)

        elements_page = QWidget()
        elements_layout = QVBoxLayout(elements_page); elements_layout.setContentsMargins(8, 10, 8, 8); elements_layout.setSpacing(7)
        elements_layout.addWidget(QLabel("WIDGETS"))
        widget_help = QLabel("Drag a widget onto the LCD, or double-click to add it.")
        widget_help.setWordWrap(True); widget_help.setObjectName("studioMuted"); elements_layout.addWidget(widget_help)
        self.palette = ElementPalette(); self.palette.setObjectName("studioBrowser"); elements_layout.addWidget(self.palette, 1)
        add_button = QPushButton("Add selected widget"); add_button.setObjectName("studioAccent"); add_button.clicked.connect(self.add_selected_palette); elements_layout.addWidget(add_button)

        layers_page = QWidget()
        layers_layout = QVBoxLayout(layers_page); layers_layout.setContentsMargins(8, 10, 8, 8); layers_layout.setSpacing(7)
        layers_layout.addWidget(QLabel("LAYERS"))
        self.layers = QListWidget(); self.layers.setObjectName("studioBrowser"); self.layers.setSelectionMode(QAbstractItemView.ExtendedSelection); layers_layout.addWidget(self.layers, 1)
        layer_actions = QHBoxLayout()
        for label, callback in (("Copy", self.copy_selected), ("Paste", self.paste), ("Delete", self.delete_selected)):
            b = QPushButton(label); b.clicked.connect(callback); layer_actions.addWidget(b)
        layers_layout.addLayout(layer_actions)
        order_actions = QHBoxLayout()
        for label, operation in (("Front", "front"), ("Forward", "forward"), ("Back", "back")):
            b = QPushButton(label); b.clicked.connect(lambda _checked=False, op=operation: self.reorder(op)); order_actions.addWidget(b)
        layers_layout.addLayout(order_actions)
        flags = QHBoxLayout()
        show_hide = QPushButton("Show / Hide"); show_hide.clicked.connect(self.toggle_visibility)
        lock_unlock = QPushButton("Lock / Unlock"); lock_unlock.clicked.connect(self.toggle_lock)
        flags.addWidget(show_hide); flags.addWidget(lock_unlock); layers_layout.addLayout(flags)
        align_button = QToolButton(); align_button.setText("Align / Distribute ▾"); align_button.setPopupMode(QToolButton.InstantPopup)
        align_menu = QMenu(align_button)
        for label, operation in (("Align left", "left"), ("Align centers", "hcenter"), ("Align right", "right"), ("Align top", "top"), ("Align middle", "vcenter"), ("Align bottom", "bottom"), ("Distribute horizontally", "distribute_h"), ("Distribute vertically", "distribute_v")):
            align_menu.addAction(label, lambda _checked=False, value=operation: self.align_selected(value))
        align_button.setMenu(align_menu); layers_layout.addWidget(align_button)

        themes_page = QWidget()
        themes_layout = QVBoxLayout(themes_page); themes_layout.setContentsMargins(8, 10, 8, 8); themes_layout.setSpacing(7)
        themes_layout.addWidget(QLabel("LAYOUTS"))
        self.theme_list = QListWidget(); self.theme_list.setObjectName("studioBrowser")
        self.theme_list.setViewMode(QListWidget.IconMode); self.theme_list.setResizeMode(QListWidget.Adjust); self.theme_list.setMovement(QListWidget.Static)
        self.theme_list.setIconSize(QSize(220, 56)); self.theme_list.setGridSize(QSize(240, 116)); self.theme_list.setSpacing(5); themes_layout.addWidget(self.theme_list, 1)
        theme_buttons = QHBoxLayout()
        for label, callback in (("Open", self.open_selected_browser_theme), ("Rename", self.rename_theme), ("Delete", self.delete_theme)):
            b = QPushButton(label); b.clicked.connect(callback); theme_buttons.addWidget(b)
        themes_layout.addLayout(theme_buttons)

        self.left_tabs.addTab(sensors_page, "Sensors")
        self.left_tabs.addTab(elements_page, "Widgets")
        self.left_tabs.addTab(layers_page, "Layers")
        self.left_tabs.addTab(themes_page, "Layouts")

        # ---- center: the LCD is the workspace, not a tiny thumbnail -----------------
        center = QFrame(); center.setObjectName("studioCanvasPanel")
        center_layout = QVBoxLayout(center); center_layout.setContentsMargins(10, 10, 10, 8); center_layout.setSpacing(8)
        canvas_header = QHBoxLayout()
        canvas_header.addWidget(QLabel("LCD CANVAS"))
        self.selection_status = QLabel("No selection"); self.selection_status.setObjectName("studioMuted"); canvas_header.addWidget(self.selection_status)
        canvas_header.addStretch(1)
        self.grid_toggle = QCheckBox("Grid"); self.grid_toggle.setChecked(True)
        self.snap_toggle = QCheckBox("Snap"); self.snap_toggle.setChecked(True)
        self.guides_toggle = QCheckBox("Guides"); self.guides_toggle.setChecked(True)
        self.grid_size = QSpinBox(); self.grid_size.setRange(2, 200); self.grid_size.setValue(20); self.grid_size.setSuffix(" px")
        for widget in (self.grid_toggle, self.snap_toggle, self.guides_toggle, self.grid_size): canvas_header.addWidget(widget)
        center_layout.addLayout(canvas_header)
        self.scene = SensorThemeScene(self.document, self, now_provider=now_provider)
        self.canvas = SensorThemeCanvasView(self.scene); self.canvas.setObjectName("studioCanvas")
        center_layout.addWidget(self.canvas, 1)
        canvas_footer = QHBoxLayout()
        minus = QPushButton("−"); fit = QPushButton("Fit Canvas"); plus = QPushButton("+")
        minus.clicked.connect(lambda: self.canvas.zoom(.85)); fit.clicked.connect(self.fit_canvas); plus.clicked.connect(lambda: self.canvas.zoom(1.15))
        canvas_footer.addStretch(1); canvas_footer.addWidget(minus); canvas_footer.addWidget(fit); canvas_footer.addWidget(plus)
        center_layout.addLayout(canvas_footer)

        # ---- right: context-sensitive inspector + background + deploy ---------------
        right = QFrame(); right.setObjectName("studioInspectorPanel"); right.setMinimumWidth(350); right.setMaximumWidth(430)
        right_layout = QVBoxLayout(right); right_layout.setContentsMargins(10, 10, 10, 10); right_layout.setSpacing(9)
        right_layout.addWidget(QLabel("INSPECTOR"))
        self.properties = SensorThemeProperties(); self.properties.setObjectName("studioProperties"); right_layout.addWidget(self.properties, 1)

        bg_group = QGroupBox("Background")
        bg_form = QFormLayout(bg_group)
        self.background_fit = QComboBox(); self.background_fit.addItems(("cover", "contain", "stretch", "center", "native"))
        self.background_opacity = QSpinBox(); self.background_opacity.setRange(0, 100); self.background_opacity.setValue(100); self.background_opacity.setSuffix("%")
        self.background_lock = QCheckBox("Lock background"); self.background_lock.setChecked(True)
        bg_form.addRow("Fit", self.background_fit); bg_form.addRow("Opacity", self.background_opacity); bg_form.addRow("", self.background_lock)
        right_layout.addWidget(bg_group)

        deploy_group = QGroupBox("Apply to LCD")
        deploy_form = QFormLayout(deploy_group)
        self.apply_target = QComboBox(); self.apply_target.addItem("Trofeo Vision 9.16", ("0416:5408",)); self.apply_target.addItem("Trofeo Vision 6.86", ("0416:5302",)); self.apply_target.addItem("Both displays", ("0416:5408", "0416:5302"))
        self.apply_fps = QComboBox()
        for fps in (1, 2, 5, 10, 15, 30): self.apply_fps.addItem(f"{fps} FPS", fps)
        self.apply_fps.setCurrentIndex(self.apply_fps.findData(2))
        self.apply_button = QPushButton("Apply to Display"); self.apply_button.setObjectName("studioAccent"); self.apply_button.clicked.connect(self.apply_to_display)
        self.active_status = QLabel("Not active"); self.active_status.setObjectName("studioMuted")
        deploy_form.addRow("Target", self.apply_target); deploy_form.addRow("Refresh", self.apply_fps); deploy_form.addRow(self.apply_button); deploy_form.addRow(self.active_status)
        right_layout.addWidget(deploy_group)

        self.splitter = QSplitter(Qt.Horizontal); self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.left_tabs); self.splitter.addWidget(center); self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0); self.splitter.setStretchFactor(1, 1); self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([290, 1040, 390]); root.addWidget(self.splitter, 1)

        # Local Sensor Studio styling only; the application's global QSS is untouched.
        self.setStyleSheet("""
            QWidget#oniSensorStudio { background: #030912; color: #d8e9f6; }
            QLabel#studioTitle { font-size: 20px; font-weight: 700; color: #f2fbff; }
            QLabel#studioMuted { color: #7894a8; }
            QLabel#studioState { color: #66d9ff; font-weight: 600; padding: 5px 10px; }
            QFrame#studioBar, QFrame#studioCanvasPanel, QFrame#studioInspectorPanel {
                background: #06111d; border: 1px solid #123149; border-radius: 8px;
            }
            QPushButton, QToolButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                min-height: 28px; background: #0a1b2b; border: 1px solid #1a4766; border-radius: 5px; padding: 2px 8px; color: #d9edf8;
            }
            QPushButton:hover, QToolButton:hover { border-color: #25b9ef; background: #0d2639; }
            QPushButton#studioAccent { background: #0879a8; border-color: #19bce8; color: white; font-weight: 600; }
            QTabWidget#studioLeftTabs::pane { border: 1px solid #123149; background: #06111d; }
            QTabBar::tab { background: #071522; border: 1px solid #123149; padding: 8px 10px; }
            QTabBar::tab:selected { background: #0b2940; color: #6fe7ff; border-bottom: 2px solid #21c7f3; }
            QListWidget#studioBrowser { background: #030a12; border: 1px solid #102b40; border-radius: 5px; }
            QListWidget#studioBrowser::item { padding: 6px; border-bottom: 1px solid #0b2030; }
            QListWidget#studioBrowser::item:selected { background: #0d3852; color: white; }
            QGraphicsView#studioCanvas { background: #02060b; border: 1px solid #153b55; border-radius: 6px; }
            QGroupBox { border: 1px solid #16384f; border-radius: 6px; margin-top: 10px; padding-top: 8px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #7fdfff; }
            QScrollArea#studioProperties { border: 0; background: transparent; }
        """)

        # ---- wiring -----------------------------------------------------------------
        self.palette.addRequested.connect(self.add_element); self.canvas.elementDropped.connect(self.add_element)
        self.scene.selectionIdsChanged.connect(self.selection_changed); self.layers.itemSelectionChanged.connect(self.layer_selection_changed)
        self.layers.itemDoubleClicked.connect(lambda _item: self.layer_selection_changed())
        self.properties.propertyChanged.connect(self.apply_property); self.properties.resourceRequested.connect(self.choose_resource)
        self.document.themeChanged.connect(self.queue_document_refresh); self.document.dirtyChanged.connect(self.dirty_changed); self.document.historyChanged.connect(self.history_changed)
        self.preset.currentIndexChanged.connect(self.preset_changed); self.preview_mode.currentTextChanged.connect(self.preview_mode_changed)
        self.grid_toggle.toggled.connect(self.canvas_options_changed); self.snap_toggle.toggled.connect(self.canvas_options_changed); self.guides_toggle.toggled.connect(self.canvas_options_changed); self.grid_size.valueChanged.connect(self.canvas_options_changed)
        self.theme_list.itemDoubleClicked.connect(lambda _item: self.open_selected_browser_theme())
        self.sensor_search.textChanged.connect(self.refresh_sensor_browser); self.sensor_category.currentTextChanged.connect(self.refresh_sensor_browser)
        self.sensor_refresh_button.clicked.connect(self.refresh_sensor_availability); self.sensor_bind_button.clicked.connect(self.bind_selected_sensor); self.sensor_list.itemDoubleClicked.connect(lambda _item: self.bind_selected_sensor())
        self.background_fit.currentTextChanged.connect(self.background_options_changed); self.background_opacity.valueChanged.connect(self.background_options_changed); self.background_lock.toggled.connect(self.background_options_changed)
        self.live_timer = QTimer(self); self.live_timer.setInterval(1000); self.live_timer.timeout.connect(self.refresh_live_values)
        QShortcut(QKeySequence.Undo, self, activated=self.document.undo); QShortcut(QKeySequence.Redo, self, activated=self.document.redo); QShortcut(QKeySequence.Save, self, activated=self.save)

        self.refresh_theme_browser()
        initial = next((item for item in self.store.list_builtin() if item.theme.id == "oni-cyber-blue"), None)
        if initial is None:
            available = self.store.list_builtin() + self.store.list_user(); initial = available[0] if available else None
        if initial: self.document.load(initial)
        else: self.document.new("Untitled Theme")
        self.refresh_sensor_browser()
        QTimer.singleShot(0, self.fit_canvas)

    def attach_navigation_guard(self, stack: QStackedWidget) -> None:
        self._navigation_stack = stack

    def request_leave(self) -> bool:
        """Resolve unsaved state before the page stack changes."""
        return self.confirm_unsaved("leave ONI Sensor Studio", revert_on_discard=True)

    def queue_document_refresh(self, _theme=None) -> None:
        if self._refresh_pending: return
        self._refresh_pending = True; QTimer.singleShot(0, self.refresh_document)

    def refresh_document(self) -> None:
        self._refresh_pending = False; selected = self.scene.selected_ids(); self.scene.reload(selected)
        self.refresh_layers(); self.selection_changed(selected); self._sync_preset()

    def _sync_preset(self) -> None:
        if self.document.theme is None: return
        self.preset.blockSignals(True); index = self.preset.findData(self.document.theme.canvas.preset); self.preset.setCurrentIndex(index if index >= 0 else self.preset.findData("custom")); self.preset.blockSignals(False)
        for control in (self.background_fit,self.background_opacity,self.background_lock):control.blockSignals(True)
        self.background_fit.setCurrentText(self.document.theme.background_fit);self.background_opacity.setValue(round(self.document.theme.background_opacity*100));self.background_lock.setChecked(self.document.theme.background_locked)
        for control in (self.background_fit,self.background_opacity,self.background_lock):control.blockSignals(False)

    def background_options_changed(self, _value=None) -> None:
        if self.document.theme is None:return
        fit=self.background_fit.currentText();opacity=self.background_opacity.value()/100;locked=self.background_lock.isChecked()
        self.document.mutate(lambda theme:(setattr(theme,"background_fit",fit),setattr(theme,"background_opacity",opacity),setattr(theme,"background_locked",locked)))

    def dirty_changed(self, dirty: bool) -> None:
        name = self.document.theme.name if self.document.theme else "No theme"
        self.dirty_label.setText(f"● Unsaved · {name}" if dirty else f"Saved · {name}")

    def history_changed(self, undo: bool, redo: bool) -> None:
        self.actions["Undo"].setEnabled(undo); self.actions["Redo"].setEnabled(redo)

    def selected_ids(self) -> list[str]:
        scene_ids = self.scene.selected_ids()
        return scene_ids or [item.data(Qt.UserRole) for item in self.layers.selectedItems()]

    def selection_changed(self, element_ids: Iterable[str]) -> None:
        ids = list(element_ids); element = self.document.element(ids[0]) if len(ids) == 1 else None; self.properties.set_element(element)
        self.selection_status.setText(f"X {element.x:g} · Y {element.y:g} · W {element.width:g} · H {element.height:g} · {element.sensor_binding or 'No sensor'}" if element else f"{len(ids)} selected" if ids else "No selection")
        self.layers.blockSignals(True)
        for index in range(self.layers.count()): self.layers.item(index).setSelected(self.layers.item(index).data(Qt.UserRole) in ids)
        self.layers.blockSignals(False)

    def refresh_layers(self) -> None:
        selected = set(self.scene.selected_ids()); self.layers.blockSignals(True); self.layers.clear()
        if self.document.theme:
            for element in sorted(self.document.theme.elements, key=lambda item: item.z_index, reverse=True):
                prefix = ("◉" if element.visible else "○") + (" 🔒" if element.locked else "")
                item = QListWidgetItem(f"{prefix}  {element.name}\n    {FRIENDLY_ELEMENT_NAMES[element.type]} · layer {element.z_index}")
                item.setData(Qt.UserRole, element.id); item.setToolTip("Select, reorder, show/hide or lock this layer"); self.layers.addItem(item); item.setSelected(element.id in selected)
        self.layers.blockSignals(False)

    def layer_selection_changed(self) -> None:
        ids = [item.data(Qt.UserRole) for item in self.layers.selectedItems()]
        self.scene.select_ids(ids)
        # Invisible items cannot join QGraphicsScene.selectedItems(); preserve
        # their Layers selection so users can always show them again.
        self.layers.blockSignals(True)
        for index in range(self.layers.count()): self.layers.item(index).setSelected(self.layers.item(index).data(Qt.UserRole) in ids)
        self.layers.blockSignals(False)
        if len(ids) == 1: self.properties.set_element(self.document.element(ids[0]))

    def refresh_theme_browser(self) -> None:
        current_id = self.document.theme.id if self.document.theme else None
        self.theme_list.blockSignals(True); self.theme_list.clear(); renderer = SensorThemeRenderer()
        for stored in self.store.list_builtin() + self.store.list_user():
            try:
                preview = renderer.render(stored.theme, SAMPLE_SENSOR_VALUES, history=SAMPLE_HISTORY, asset_root=stored.root, output_size=(210, 54), now=self.now_provider() if self.now_provider else None)
                icon = QIcon(_image_to_pixmap(preview))
            except Exception: icon = QIcon()
            canvas = stored.theme.canvas; origin = "Built-in" if stored.built_in else "User"
            item = QListWidgetItem(icon, f"{stored.theme.name}\n{origin} · {canvas.width}×{canvas.height}\n{stored.theme.author or 'Local theme'}")
            item.setData(Qt.UserRole, stored.theme.id); item.setData(Qt.UserRole + 1, stored.built_in); self.theme_list.addItem(item)
            if stored.theme.id == current_id: self.theme_list.setCurrentItem(item)
        self.theme_list.blockSignals(False)

    def refresh_sensor_browser(self, _value=None) -> None:
        needle=self.sensor_search.text().casefold() if hasattr(self,"sensor_search") else "";category=self.sensor_category.currentText() if hasattr(self,"sensor_category") else "All"
        self.sensor_list.clear()
        for binding,label in FRIENDLY_SENSOR_NAMES.items():
            prefix=binding.split(".",1)[0]
            group="Game/FPS" if prefix=="game" else prefix.upper() if prefix in {"cpu","gpu"} else prefix.title()
            if category!="All" and group!=category:continue
            if needle and needle not in f"{label} {binding}".casefold():continue
            availability=self._sensor_availability.get(binding)
            status="Available" if availability is True else "Unavailable" if availability is False else "Not checked"
            item=QListWidgetItem(f"{label}\n{binding} · {status}");item.setData(Qt.UserRole,binding);self.sensor_list.addItem(item)

    def refresh_sensor_availability(self) -> None:
        if self.live_value_provider is None:
            self._sensor_availability = {binding: False for binding in SUPPORTED_SENSOR_BINDINGS}
        else:
            try:
                supplied = self.live_value_provider(); values = supplied if isinstance(supplied, dict) else getattr(supplied, "values", supplied)
                resolver = SensorBindingResolver(); self._sensor_availability = {binding: resolver.resolve(binding, values).available for binding in SUPPORTED_SENSOR_BINDINGS}
            except Exception:
                self._sensor_availability = {binding: False for binding in SUPPORTED_SENSOR_BINDINGS}
        self.refresh_sensor_browser()

    def bind_selected_sensor(self) -> bool:
        item=self.sensor_list.currentItem();ids=self.selected_ids()
        if item is None or len(ids)!=1:return False
        element=self.document.element(ids[0])
        if element is None or "sensor_binding" not in applicable_element_fields(element.type):return False
        return self.document.set_property(element.id,"sensor_binding",item.data(Qt.UserRole))

    def confirm_unsaved(self, action: str, *, revert_on_discard: bool = False) -> bool:
        if not self.document.dirty: return True
        if self.prompt_handler: choice = self.prompt_handler(action)
        else:
            box = QMessageBox(QMessageBox.Warning, "Unsaved sensor theme", f"Save changes before you {action}?", parent=self)
            save = box.addButton("Save", QMessageBox.AcceptRole); discard = box.addButton("Discard", QMessageBox.DestructiveRole); cancel = box.addButton("Cancel", QMessageBox.RejectRole); box.exec()
            choice = "save" if box.clickedButton() is save else "discard" if box.clickedButton() is discard else "cancel"
        if choice == "cancel": return False
        if choice == "save": return self.save()
        if revert_on_discard and not self.document.discard_changes():
            builtins = self.store.list_builtin()
            if builtins: self.document.load(builtins[0])
        return True

    def new_theme(self) -> bool:
        if not self.confirm_unsaved("create a new theme"): return False
        name, ok = QInputDialog.getText(self, "New sensor theme", "Theme name:", text="My Sensor Theme")
        if not ok or not name.strip(): return False
        preset, ok = QInputDialog.getItem(self, "Target display", "Display:", list(DISPLAY_LABELS.values())[:2], 0, False)
        if not ok: return False
        key = next(key for key, label in DISPLAY_LABELS.items() if label == preset); self.document.new(name.strip(), key); return True

    def open_theme(self) -> bool:
        options = self.store.list_builtin() + self.store.list_user()
        labels = [f"{item.theme.name} ({'Built-in' if item.built_in else 'User'})" for item in options]
        selected, ok = QInputDialog.getItem(self, "Open sensor theme", "Theme:", labels, 0, False)
        if not ok: return False
        return self.load_theme(options[labels.index(selected)].theme.id)

    def load_theme(self, theme_id: str) -> bool:
        if not self.confirm_unsaved("open another theme"): return False
        self.document.load(self.store.get(theme_id)); return True

    def open_selected_browser_theme(self) -> bool:
        item = self.theme_list.currentItem(); return self.load_theme(item.data(Qt.UserRole)) if item else False

    def save(self) -> bool:
        previous_id = self.document.theme.id if self.document.theme else ""
        try:
            if self.document.built_in: return self.save_as()
            self.document.save(); self.refresh_theme_browser(); self._deployment_changed("saved", previous_id); return True
        except Exception as exc: QMessageBox.critical(self, "Could not save theme", str(exc)); return False

    def save_as(self) -> bool:
        current = self.document.theme.name if self.document.theme else "Theme"
        previous_id = self.document.theme.id if self.document.theme else ""
        name, ok = QInputDialog.getText(self, "Save sensor theme as", "Name:", text=f"{current} Copy" if self.document.built_in else current)
        if not ok or not name.strip(): return False
        try: self.document.save_as(name.strip()); self.refresh_theme_browser(); self._deployment_changed("saved", previous_id); return True
        except Exception as exc: QMessageBox.critical(self, "Could not save theme", str(exc)); return False

    def duplicate_theme(self) -> bool:
        current = self.document.theme.name if self.document.theme else "Theme"
        name, ok = QInputDialog.getText(self, "Duplicate sensor theme", "Copy name:", text=f"{current} Copy")
        if not ok or not name.strip(): return False
        try: self.document.duplicate_theme(name.strip()); self.refresh_theme_browser(); return True
        except Exception as exc: QMessageBox.critical(self, "Could not duplicate theme", str(exc)); return False

    def rename_theme(self) -> bool:
        if self.document.built_in: QMessageBox.information(self, "Built-in theme", "Duplicate the built-in theme before renaming it."); return False
        previous_id = self.document.theme.id
        name, ok = QInputDialog.getText(self, "Rename sensor theme", "Name:", text=self.document.theme.name)
        if not ok or not name.strip(): return False
        try: self.document.rename(name.strip()); self.refresh_theme_browser(); self._deployment_changed("saved", previous_id); return True
        except Exception as exc: QMessageBox.critical(self, "Could not rename theme", str(exc)); return False

    def delete_theme(self) -> bool:
        if self.document.built_in: QMessageBox.information(self, "Built-in theme", "Built-in themes cannot be deleted."); return False
        if QMessageBox.question(self, "Delete sensor theme", f"Delete '{self.document.theme.name}'?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return False
        deleted_id = self.document.theme.id
        try:
            self.document.delete_theme(); available = self.store.list_builtin() + self.store.list_user()
            if available: self.document.load(available[0])
            self.refresh_theme_browser(); self._deployment_changed("deleted", deleted_id); return True
        except Exception as exc: QMessageBox.critical(self, "Could not delete theme", str(exc)); return False

    def import_theme(self) -> bool:
        if not self.confirm_unsaved("import a theme"): return False
        path, _ = QFileDialog.getOpenFileName(self, "Import sensor layout", "", "ONI Layout JSON (*.json);;Oni Sensor Theme (*.oni-theme)")
        if not path: return False
        try:
            if Path(path).suffix.casefold()==".json":self.document.import_json(Path(path))
            else:self.document.import_package(Path(path))
            self.refresh_theme_browser();return True
        except Exception as exc: QMessageBox.critical(self, "Could not import theme", str(exc)); return False

    def export_theme(self) -> bool:
        if self.document.theme is None: return False
        path, selected = QFileDialog.getSaveFileName(self, "Export sensor layout", f"{self.document.theme.id}.json", "ONI Layout JSON (*.json);;Oni Sensor Theme Package (*.oni-theme)")
        if not path: return False
        try:
            if Path(path).suffix.casefold()==".oni-theme" or "Package" in selected:self.document.export_package(Path(path),self.scene.renderer)
            else:self.document.export_json(Path(path))
            return True
        except Exception as exc: QMessageBox.critical(self, "Could not export theme", str(exc)); return False

    def import_background(self) -> bool:
        path,_=QFileDialog.getOpenFileName(self,"Import dashboard background","","Images (*.png *.jpg *.jpeg *.webp)")
        if not path:return False
        try:self.document.import_background(Path(path));return True
        except Exception as exc:QMessageBox.warning(self,"Could not import background",str(exc));return False

    def apply_to_display(self) -> bool:
        """Deploy a detached in-memory snapshot without implicitly saving it."""
        if self.document.theme is None or self.apply_handler is None:
            self.active_status.setText("Display output unavailable")
            return False
        theme = SensorTheme.from_dict(deepcopy(self.document.theme.to_dict()))
        targets = tuple(self.apply_target.currentData())
        fps = int(self.apply_fps.currentData())
        try:
            result = self.apply_handler(theme, self.document.asset_root, targets, fps)
        except Exception as exc:
            self.active_status.setText(f"Apply failed · {exc}")
            return False
        self.active_status.setText(str(result) if result else f"Active · {theme.name} · {fps} FPS")
        return True

    def set_active_status(self, text: str) -> None:
        self.active_status.setText(text)

    def _deployment_changed(self, event: str, previous_id: str) -> None:
        if self.deployment_handler is None:
            return
        theme = SensorTheme.from_dict(deepcopy(self.document.theme.to_dict())) if event == "saved" and self.document.theme else None
        try:
            result = self.deployment_handler(event, theme, self.document.asset_root if theme else None, previous_id)
            if result: self.active_status.setText(str(result))
        except Exception as exc:
            self.active_status.setText(f"Saved locally · active output update failed · {exc}")

    def add_selected_palette(self) -> None:
        item = self.palette.currentItem()
        if item: self.add_element(item.data(Qt.UserRole))

    def add_element(self, element_type: str, position: object = None) -> None:
        point = tuple(position) if isinstance(position, (tuple, list)) else None
        try:
            element = self.document.add_element(element_type, point)
            QTimer.singleShot(0, lambda: self.scene.select_ids([element.id]))
        except Exception as exc: QMessageBox.critical(self, "Could not add element", str(exc))

    def delete_selected(self) -> None: self.document.delete(self.selected_ids())
    def copy_selected(self) -> None: self.document.copy(self.selected_ids())
    def paste(self) -> None:
        created = self.document.paste(); QTimer.singleShot(0, lambda: self.scene.select_ids(created))
    def reorder(self, operation: str) -> None: self.document.reorder(self.selected_ids(), operation)
    def align_selected(self, operation: str) -> None: self.document.align(self.selected_ids(), operation)

    def toggle_visibility(self) -> None:
        selected = [self.document.element(item) for item in self.selected_ids()]
        if selected: self.document.set_flag((item.id for item in selected), "visible", not all(item.visible for item in selected))

    def toggle_lock(self) -> None:
        selected = [self.document.element(item) for item in self.selected_ids()]
        if selected: self.document.set_flag((item.id for item in selected), "locked", not all(item.locked for item in selected))

    def apply_property(self, name: str, value: object) -> None:
        ids = self.selected_ids()
        if len(ids) != 1: return
        try: self.document.set_property(ids[0], name, value); QTimer.singleShot(0, lambda: self.scene.select_ids(ids))
        except Exception as exc: QMessageBox.warning(self, "Invalid property", str(exc)); self.properties.set_element(self.document.element(ids[0]))

    def choose_resource(self, kind: str) -> None:
        ids = self.selected_ids()
        if len(ids) != 1: return
        title = "Choose packaged font" if kind == "font" else "Choose theme image"
        pattern = "Fonts (*.ttf *.otf)" if kind == "font" else "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        path, _ = QFileDialog.getOpenFileName(self, title, "", pattern)
        if not path: return
        try:
            relative = self.document.add_resource_file(Path(path), font=kind == "font")
            self.document.set_property(ids[0], "font_file" if kind == "font" else "asset", relative)
            QTimer.singleShot(0, lambda: self.scene.select_ids(ids))
        except Exception as exc: QMessageBox.warning(self, "Could not add resource", str(exc))

    def preset_changed(self, _index: int) -> None:
        if self.document.theme is None: return
        preset = self.preset.currentData()
        if preset == self.document.theme.canvas.preset: return
        width = height = None
        if preset == "custom":
            width, ok = QInputDialog.getInt(self, "Custom canvas", "Width:", self.document.theme.canvas.width, 1, 8192)
            if not ok: self._sync_preset(); return
            height, ok = QInputDialog.getInt(self, "Custom canvas", "Height:", self.document.theme.canvas.height, 1, 8192)
            if not ok: self._sync_preset(); return
        box = QMessageBox(QMessageBox.Question, "Change display canvas", "Scale the current layout proportionally for the new display?", parent=self)
        scale = box.addButton("Scale layout", QMessageBox.AcceptRole); keep = box.addButton("Keep coordinates", QMessageBox.ActionRole); cancel = box.addButton("Cancel", QMessageBox.RejectRole); box.exec()
        if box.clickedButton() is cancel: self._sync_preset(); return
        try: self.document.change_canvas(preset, width=width, height=height, scale=box.clickedButton() is scale)
        except Exception as exc: QMessageBox.warning(self, "Could not change canvas", str(exc)); self._sync_preset()

    def preview_mode_changed(self, mode: str) -> None:
        self.live_timer.stop()
        if mode == "Sample Data": self.scene.set_values(SAMPLE_SENSOR_VALUES)
        elif mode == "Missing Data": self.scene.set_values({})
        else: self.refresh_live_values(); self.live_timer.start()

    def refresh_live_values(self) -> None:
        if self.live_value_provider is None: self.scene.set_values({}); return
        try:
            value = self.live_value_provider()
            self.scene.set_values(value if isinstance(value, dict) else getattr(value, "values", value))
        except Exception: self.scene.set_values({})

    def canvas_options_changed(self, _value=None) -> None:
        self.scene.grid_enabled = self.grid_toggle.isChecked(); self.scene.snap_enabled = self.snap_toggle.isChecked(); self.scene.alignment_guides = self.guides_toggle.isChecked(); self.scene.grid_size = self.grid_size.value(); self.scene.update()

    def fit_canvas(self) -> None:
        self.canvas.manual_zoom = False; self.canvas.fit_canvas()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.preview_mode.currentText() == "Live Sensors": self.live_timer.start()
        QTimer.singleShot(0, self.fit_canvas)

    def hideEvent(self, event) -> None:
        self.live_timer.stop(); super().hideEvent(event)
