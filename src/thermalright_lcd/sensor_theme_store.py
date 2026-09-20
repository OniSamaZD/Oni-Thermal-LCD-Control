"""Built-in and per-user storage for customizable sensor themes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sys

from .sensor_theme import DISPLAY_PRESETS, SensorTheme, ThemeCanvas, ThemeValidationError, validate_theme
from .sensor_theme_package import export_theme_package, import_theme_package


def default_user_theme_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OniThermalLcd" / "sensor-themes"


def default_builtin_theme_directory() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "assets" / "sensor-themes"


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:56]
    return result or "untitled-theme"


@dataclass(frozen=True, slots=True)
class StoredTheme:
    theme: SensorTheme
    root: Path
    built_in: bool


class SensorThemeStore:
    def __init__(self, user_directory: Path | None = None, builtin_directory: Path | None = None) -> None:
        self.user_directory = Path(user_directory) if user_directory is not None else default_user_theme_directory()
        self.builtin_directory = Path(builtin_directory) if builtin_directory is not None else default_builtin_theme_directory()

    @staticmethod
    def _read(path: Path) -> SensorTheme:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThemeValidationError(f"could not read sensor theme: {path.name}") from exc
        theme = SensorTheme.from_dict(raw)
        root = path.parent
        resources = {
            item.relative_to(root).as_posix()
            for directory in (root / "assets", root / "fonts")
            if directory.is_dir()
            for item in directory.rglob("*") if item.is_file()
        }
        validate_theme(theme, resources)
        return theme

    def list_builtin(self) -> list[StoredTheme]:
        if not self.builtin_directory.is_dir():
            return []
        return [StoredTheme(self._read(path), path.parent, True) for path in sorted(self.builtin_directory.glob("*/theme.json"))]

    def list_user(self) -> list[StoredTheme]:
        if not self.user_directory.is_dir():
            return []
        return [StoredTheme(self._read(path), path.parent, False) for path in sorted(self.user_directory.glob("*/theme.json")) if not path.parent.name.startswith(".import-")]

    def get(self, theme_id: str) -> StoredTheme:
        user = self.user_directory / theme_id / "theme.json"
        if user.is_file():
            return StoredTheme(self._read(user), user.parent, False)
        for stored in self.list_builtin():
            if stored.theme.id == theme_id:
                return stored
        raise KeyError(theme_id)

    def create(self, name: str, *, preset: str = "0416:5408", width: int | None = None, height: int | None = None) -> SensorTheme:
        if preset in DISPLAY_PRESETS:
            width, height = DISPLAY_PRESETS[preset]
        elif preset != "custom":
            raise ThemeValidationError(f"unknown display preset: {preset}")
        if width is None or height is None:
            raise ThemeValidationError("custom canvas requires width and height")
        base = _slug(name)
        theme_id = base
        index = 2
        existing = {item.theme.id for item in self.list_builtin() + self.list_user()}
        while theme_id in existing:
            theme_id, index = f"{base}-{index}", index + 1
        return SensorTheme(theme_id, name, ThemeCanvas(width, height, preset))

    def save(self, theme: SensorTheme) -> Path:
        destination = self.user_directory / theme.id
        destination.mkdir(parents=True, exist_ok=True)
        resources = {
            item.relative_to(destination).as_posix()
            for directory in (destination / "assets", destination / "fonts")
            if directory.is_dir()
            for item in directory.rglob("*") if item.is_file()
        }
        validate_theme(theme, resources)
        target = destination / "theme.json"
        temporary = destination / "theme.json.tmp"
        temporary.write_text(json.dumps(theme.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def duplicate(self, theme_id: str, new_name: str) -> SensorTheme:
        source = self.get(theme_id)
        duplicate = self.create(new_name, preset=source.theme.canvas.preset, width=source.theme.canvas.width, height=source.theme.canvas.height)
        raw = source.theme.to_dict()
        raw["id"], raw["name"] = duplicate.id, new_name
        duplicate = SensorTheme.from_dict(raw)
        destination = self.user_directory / duplicate.id
        destination.mkdir(parents=True, exist_ok=False)
        for folder in ("assets", "fonts"):
            source_folder = source.root / folder
            if source_folder.is_dir():
                shutil.copytree(source_folder, destination / folder)
        self.save(duplicate)
        return duplicate

    def rename(self, theme_id: str, new_name: str) -> SensorTheme:
        stored = self.get(theme_id)
        if stored.built_in:
            raise ThemeValidationError("built-in themes cannot be renamed; duplicate one first")
        raw = stored.theme.to_dict()
        raw["name"] = new_name
        renamed = SensorTheme.from_dict(raw)
        self.save(renamed)
        return renamed

    def delete(self, theme_id: str) -> None:
        stored = self.get(theme_id)
        if stored.built_in:
            raise ThemeValidationError("built-in themes cannot be deleted")
        shutil.rmtree(stored.root)

    def import_package(self, path: Path) -> SensorTheme:
        theme, _destination = import_theme_package(path, self.user_directory)
        return theme

    def export_package(self, theme_id: str, path: Path, *, preview=None) -> Path:
        stored = self.get(theme_id)
        return export_theme_package(stored.theme, path, asset_root=stored.root, preview=preview)
