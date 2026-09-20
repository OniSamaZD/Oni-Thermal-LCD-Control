"""Secure import/export for data-only ``.oni-theme`` packages."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4
import zipfile

from PIL import Image

from .sensor_theme import SensorTheme, ThemeValidationError, validate_theme


MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_THEME_JSON_BYTES = 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 128
MAX_IMAGE_PIXELS = 20_000_000
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
FONT_SUFFIXES = {".ttf", ".otf"}


@dataclass(frozen=True, slots=True)
class ThemePackage:
    theme: SensorTheme
    resources: dict[str, bytes]
    preview: bytes | None = None


def _validate_member_name(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if not name or member.is_absolute() or ".." in member.parts or "\\" in name or ":" in name:
        raise ThemeValidationError(f"unsafe theme package path: {name}")
    return member


def _validate_image(name: str, payload: bytes) -> None:
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise ThemeValidationError(f"invalid image asset: {name}") from exc
    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
        raise ThemeValidationError(f"image asset has unreasonable dimensions: {name}")


def read_theme_package(path: Path) -> ThemePackage:
    path = Path(path)
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise ThemeValidationError("theme package is not a valid ZIP archive")
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ThemeValidationError("theme package is too large")
    try:
        with zipfile.ZipFile(path, "r") as package:
            infos = package.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ThemeValidationError("theme package contains too many members")
            names = [info.filename for info in infos if not info.is_dir()]
            normalized_names = [_validate_member_name(name).as_posix().casefold() for name in names]
            if len(normalized_names) != len(set(normalized_names)):
                raise ThemeValidationError("theme package contains duplicate members")
            expanded = 0
            resources: dict[str, bytes] = {}
            theme_payload: bytes | None = None
            preview: bytes | None = None
            for info in infos:
                member = _validate_member_name(info.filename)
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise ThemeValidationError("encrypted theme members are not supported")
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ThemeValidationError(f"theme package member is too large: {info.filename}")
                if info.file_size > 1024 * 1024 and info.file_size > max(1, info.compress_size) * 200:
                    raise ThemeValidationError("theme package has an unreasonable compression ratio")
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise ThemeValidationError("theme package expands beyond its size limit")
                payload = package.read(info)
                if info.filename == "theme.json":
                    if info.file_size > MAX_THEME_JSON_BYTES:
                        raise ThemeValidationError("theme.json is too large")
                    theme_payload = payload
                elif info.filename == "preview.png":
                    _validate_image(info.filename, payload)
                    preview = payload
                elif member.parts[0] == "assets" and member.suffix.casefold() in ASSET_SUFFIXES:
                    _validate_image(info.filename, payload)
                    resources[info.filename] = payload
                elif member.parts[0] == "fonts" and member.suffix.casefold() in FONT_SUFFIXES:
                    resources[info.filename] = payload
                else:
                    raise ThemeValidationError(f"unsupported theme package member: {info.filename}")
            if theme_payload is None:
                raise ThemeValidationError("theme package has no theme.json")
            try:
                raw = json.loads(theme_payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                raise ThemeValidationError("theme.json is malformed") from exc
            theme = SensorTheme.from_dict(raw)
            validate_theme(theme, resources)
            return ThemePackage(theme, resources, preview)
    except zipfile.BadZipFile as exc:
        raise ThemeValidationError("theme package is corrupt") from exc


def export_theme_package(
    theme: SensorTheme,
    path: Path,
    *,
    asset_root: Path | None = None,
    preview: Image.Image | Path | None = None,
) -> Path:
    path = Path(path)
    if path.suffix.casefold() != ".oni-theme":
        path = path.with_suffix(".oni-theme")
    asset_root = Path(asset_root) if asset_root is not None else None
    references = {resource for element in theme.elements for resource in (element.asset, element.font_file) if resource}
    validate_theme(theme, references)
    resources: dict[str, bytes] = {}
    for reference in sorted(references):
        if asset_root is None:
            raise ThemeValidationError(f"asset_root is required for {reference}")
        source = asset_root.joinpath(*reference.split("/"))
        if not source.is_file():
            raise ThemeValidationError(f"referenced theme resource is missing: {reference}")
        if source.stat().st_size > MAX_MEMBER_BYTES:
            raise ThemeValidationError(f"theme resource is too large: {reference}")
        payload = source.read_bytes()
        if PurePosixPath(reference).parts[0] == "assets":
            _validate_image(reference, payload)
        resources[reference] = payload
    preview_payload: bytes | None = None
    if isinstance(preview, Image.Image):
        output = BytesIO()
        preview.save(output, "PNG")
        preview_payload = output.getvalue()
    elif preview is not None:
        preview_payload = Path(preview).read_bytes()
        _validate_image("preview.png", preview_payload)
    theme_payload = json.dumps(theme.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
    if len(theme_payload) > MAX_THEME_JSON_BYTES:
        raise ThemeValidationError("theme.json is too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        package.writestr("theme.json", theme_payload)
        if preview_payload is not None:
            package.writestr("preview.png", preview_payload)
        for name, payload in resources.items():
            package.writestr(name, payload)
    # Read the produced package through the same untrusted-input boundary.
    read_theme_package(path)
    return path


def import_theme_package(path: Path, user_theme_directory: Path) -> tuple[SensorTheme, Path]:
    package = read_theme_package(path)
    root = Path(user_theme_directory)
    root.mkdir(parents=True, exist_ok=True)
    theme_id = package.theme.id
    destination = root / theme_id
    if destination.exists():
        index = 2
        while (root / f"{theme_id}-{index}").exists():
            index += 1
        theme_id = f"{theme_id}-{index}"
        raw = package.theme.to_dict()
        raw["id"] = theme_id
        raw["name"] = f"{package.theme.name} ({index})"
        package = ThemePackage(SensorTheme.from_dict(raw), package.resources, package.preview)
        destination = root / theme_id
    staging = root / f".import-{uuid4().hex}"
    try:
        staging.mkdir(parents=False)
        (staging / "theme.json").write_text(json.dumps(package.theme.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        if package.preview is not None:
            (staging / "preview.png").write_bytes(package.preview)
        for name, payload in package.resources.items():
            target = staging.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return package.theme, destination
