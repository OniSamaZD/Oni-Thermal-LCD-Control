from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from .capabilities import DEVICES
from .settings import DisplayProfile

FORMAT = "oni-profile"
FORMAT_VERSION = 1
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_FILES = 64
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
ALLOWED_MEMBERS = {"manifest.json", "profile.json"}


class Compatibility(str, Enum):
    EXACT = "EXACT"
    COMPATIBLE = "COMPATIBLE"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ImportedProfile:
    name: str
    source_device: str | None
    target_device: str
    compatibility: Compatibility
    profile: DisplayProfile
    monitor_layout: dict | None
    output_mode: str
    sensor_template: str
    preview_scale: int
    warnings: tuple[str, ...]


def normalize_profile_name(value: str) -> str:
    value = " ".join(str(value).strip().split())
    if not value:
        raise ValueError("profile name cannot be empty")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("profile name contains control characters")
    return value[:80]


def safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", normalize_profile_name(value)).strip(" .")
    return value or "Profile"


def device_manifest(device_id: str) -> dict:
    cap = DEVICES[device_id]
    vid, pid = device_id.split(":", 1)
    return {
        "manufacturer": "Thermalright", "model": cap.model,
        "vid": vid, "pid": pid,
        "width": cap.nominal_size[0], "height": cap.nominal_size[1],
        "encoded_width": cap.encoded_size[0], "encoded_height": cap.encoded_size[1],
    }


def classify_compatibility(source: dict | None, target_device: str) -> Compatibility:
    if not isinstance(source, dict) or target_device not in DEVICES:
        return Compatibility.UNKNOWN
    target = device_manifest(target_device)
    if all(str(source.get(key, "")).casefold() == str(target[key]).casefold()
           for key in ("vid", "pid", "model", "width", "height")):
        return Compatibility.EXACT
    try:
        same_size = (int(source["width"]), int(source["height"])) == (target["width"], target["height"])
    except (KeyError, TypeError, ValueError):
        return Compatibility.UNKNOWN
    return Compatibility.COMPATIBLE if same_size else Compatibility.MISMATCH


def _safe_member(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise ValueError(f"unsafe archive member: {name!r}")
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts or member.parts[0].endswith(":"):
        raise ValueError(f"unsafe archive member: {name!r}")
    return member


def _validated_infos(package: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = package.infolist()
    if len(infos) > MAX_FILES:
        raise ValueError("profile package contains too many files")
    total = 0
    result = {}
    for info in infos:
        member = _safe_member(info.filename)
        if (
            not info.is_dir()
            and info.filename not in ALLOWED_MEMBERS
            and (
                not member.parts
                or member.parts[0] != "assets"
                or member.suffix.casefold() not in MEDIA_EXTENSIONS
            )
        ):
            raise ValueError(f"unsupported archive member: {info.filename}")
        if info.file_size > MAX_FILE_BYTES:
            raise ValueError(f"profile asset is too large: {info.filename}")
        total += info.file_size
        if total > MAX_PACKAGE_BYTES:
            raise ValueError("profile package is too large")
        result[info.filename] = info
    return result


def export_profile(path: Path, name: str, device_id: str, profile: DisplayProfile, *,
                   monitor_layout: dict | None = None, output_mode: str = "media",
                   sensor_template: str = "", preview_scale: int = 100,
                   created_with: str = "Oni Thermal LCD Control") -> Path:
    name = normalize_profile_name(name)
    if device_id not in DEVICES:
        raise ValueError(f"unsupported profile device: {device_id}")
    path = Path(path)
    if path.suffix.casefold() != ".oniprofile":
        path = path.with_suffix(".oniprofile")
    profile_data = asdict(profile)
    assets: list[tuple[Path, str]] = []
    monitor_layout = copy.deepcopy(monitor_layout)
    source = Path(profile.media) if profile.media else None
    if source and source.is_file():
        if source.suffix.casefold() not in MEDIA_EXTENSIONS:
            raise ValueError(f"unsupported profile media: {source.suffix}")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("profile media exceeds the single-file limit")
        archive_name = f"assets/media{source.suffix.casefold()}"
        assets.append((source, archive_name)); profile_data["media"] = archive_name
    elif profile_data.get("media"):
        profile_data["media"] = ""
    if (
        isinstance(monitor_layout, dict)
        and monitor_layout.get("background_source") == "custom_image"
        and monitor_layout.get("background_image")
    ):
        background = Path(monitor_layout["background_image"])
        if background.is_file() and background.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}:
            if background.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("profile background exceeds the single-file limit")
            member = f"assets/background{background.suffix.casefold()}"
            assets.append((background, member))
            monitor_layout["background_image"] = member
        else:
            monitor_layout["background_image"] = ""
    if sum(source.stat().st_size for source, _ in assets) > MAX_PACKAGE_BYTES:
        raise ValueError("profile assets exceed the package limit")
    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION,
        "profile_name": name, "created_with": created_with,
        "device": device_manifest(device_id),
    }
    payload = {
        "profile": profile_data, "monitor_layout": monitor_layout,
        "output_mode": str(output_mode), "sensor_template": str(sensor_template),
        "preview_scale": max(50, min(200, int(preview_scale))),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        package.writestr("profile.json", json.dumps(payload, ensure_ascii=False, indent=2))
        for source, member in assets:
            package.write(source, member)
    return path


def import_profile(path: Path, asset_root: Path, target_device: str) -> ImportedProfile:
    path, asset_root = Path(path), Path(asset_root)
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("profile package is too large")
    warnings: list[str] = []
    with zipfile.ZipFile(path, "r") as package:
        infos = _validated_infos(package)
        if "manifest.json" not in infos or "profile.json" not in infos:
            raise ValueError("profile package is missing manifest.json or profile.json")
        try:
            manifest = json.loads(package.read("manifest.json"))
            payload = json.loads(package.read("profile.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("profile package contains invalid JSON") from exc
        if manifest.get("format") != FORMAT:
            raise ValueError("invalid profile package format")
        version = manifest.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported profile format version: {version}")
        if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
            raise ValueError("profile.json has an invalid schema")
        name = normalize_profile_name(manifest.get("profile_name", ""))
        raw = dict(payload["profile"])
        profile = DisplayProfile(**raw)
        source_device = None
        source_meta = manifest.get("device")
        if isinstance(source_meta, dict) and source_meta.get("vid") and source_meta.get("pid"):
            source_device = f"{source_meta['vid']}:{source_meta['pid']}".casefold()
        compatibility = classify_compatibility(source_meta, target_device)
        member = profile.media
        if member:
            safe = _safe_member(member)
            if safe.suffix.casefold() not in MEDIA_EXTENSIONS:
                raise ValueError("profile references an unsupported media extension")
            if member not in infos:
                warnings.append("Packaged media is missing; the profile was imported without media.")
                profile.media = ""
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                destination_dir = asset_root / f"{safe_filename(name)}-{digest}"
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = destination_dir / f"media{safe.suffix.casefold()}"
                with package.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                profile.media = str(destination)
        output_mode = str(payload.get("output_mode", profile.output_mode or "media"))
        sensor_template = str(payload.get("sensor_template", profile.sensor_template or ""))
        preview_scale = max(50, min(200, int(payload.get("preview_scale", profile.preview_scale))))
        profile.output_mode = output_mode
        profile.sensor_template = sensor_template
        profile.preview_scale = preview_scale
        layout = payload.get("monitor_layout")
        if layout is not None and not isinstance(layout, dict):
            raise ValueError("monitor layout must be an object or null")
        if isinstance(layout, dict) and layout.get("background_image"):
            background_member = layout["background_image"]
            safe_background = _safe_member(background_member)
            if safe_background.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise ValueError("profile references an unsupported background extension")
            if background_member not in infos:
                warnings.append("Packaged layout background is missing; the profile was imported without it.")
                layout["background_image"] = ""
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                destination_dir = asset_root / f"{safe_filename(name)}-{digest}"
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = destination_dir / f"background{safe_background.suffix.casefold()}"
                with package.open(background_member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                layout["background_image"] = str(destination)
        if compatibility is Compatibility.MISMATCH:
            warnings.append("The source and selected displays have different resolutions or aspect ratios; crop, zoom, positioning and sensor layout may require adjustment.")
        elif compatibility is Compatibility.UNKNOWN:
            warnings.append("The source device metadata is incomplete; compatibility is unknown.")
        return ImportedProfile(
            name, source_device, target_device, compatibility, profile, layout,
            output_mode, sensor_template, preview_scale, tuple(warnings),
        )
