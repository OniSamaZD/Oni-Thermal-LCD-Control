from __future__ import annotations

import json
import shutil
import zipfile
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from .settings import AppSettings, DisplayProfile

FORMAT = "oni-thermal-theme"
VERSION = 1
MAX_PACKAGE_BYTES=128*1024*1024
MAX_MEMBER_BYTES=32*1024*1024
MAX_MANIFEST_BYTES=4*1024*1024
MAX_MEMBERS=512
SAFE_ASSET_SUFFIXES={".png",".jpg",".jpeg",".webp",".gif",".mp4",".webm",".mkv",".mov",".avi",".m4v"}


def export_theme(path: Path, settings: AppSettings, *, include_media: bool = False) -> Path:
    """Write a versioned, portable profile package without touching devices."""
    path = Path(path)
    media: dict[str, str] = {}
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "active_profile": settings.active_profile,
        "profiles": {
            name: {device: asdict(profile) for device, profile in devices.items()}
            for name, devices in settings.profiles.items()
        },
        "monitor_layouts": deepcopy(settings.monitor_layouts),
        "media_included": bool(include_media),
    }
    if include_media:
        for devices in manifest["profiles"].values():
            for profile in devices.values():
                source = Path(profile.get("media", ""))
                if source.is_file():
                    archive_name = f"media/{len(media):04d}-{source.name}"
                    media[str(source)] = archive_name
                    profile["media"] = archive_name
    assets: dict[str, str] = {}
    def include_asset(raw: dict, key: str) -> None:
        value=raw.get(key,"")
        source=Path(value) if value else None
        if source:
            if not source.is_file():raise ValueError(f"referenced theme asset does not exist: {value}")
            if source.suffix.casefold() not in SAFE_ASSET_SUFFIXES:raise ValueError(f"unsupported theme asset: {source.name}")
            archive_name=assets.get(str(source))
            if archive_name is None:
                archive_name=f"assets/{len(assets):04d}-{source.name}";assets[str(source)]=archive_name
            raw[key]=archive_name
    for layouts in manifest["monitor_layouts"].values():
        if not isinstance(layouts,dict):continue
        for layout in layouts.values():
            if not isinstance(layout,dict):continue
            include_asset(layout,"background_image")
            for element in layout.get("elements",[]):
                if isinstance(element,dict):include_asset(element,"image")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest, indent=2))
        for source, archive_name in media.items():
            package.write(source, archive_name)
        for source, archive_name in assets.items():
            package.write(source, archive_name)
    return path


def import_theme(path: Path, media_directory: Path | None = None) -> tuple[dict, list[str]]:
    """Validate and read a package. Returns data plus compatibility warnings."""
    path=Path(path)
    if path.stat().st_size>MAX_PACKAGE_BYTES:raise ValueError("theme package is too large")
    with zipfile.ZipFile(path, "r") as package:
        infos=package.infolist()
        if len(infos)>MAX_MEMBERS:raise ValueError("theme package contains too many files")
        total=0
        for info in infos:
            member=PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts or "\\" in info.filename:raise ValueError("unsafe theme package path")
            if info.file_size>MAX_MEMBER_BYTES:raise ValueError("theme package member is too large")
            total+=info.file_size
            if total>MAX_PACKAGE_BYTES:raise ValueError("theme package expands beyond its size limit")
            if info.filename!="manifest.json" and (not member.parts or member.parts[0] not in {"media","assets"} or member.suffix.casefold() not in SAFE_ASSET_SUFFIXES):raise ValueError("unsupported theme package member")
        names = set(package.namelist())
        if "manifest.json" not in names:
            raise ValueError("theme package has no manifest")
        manifest_info=package.getinfo("manifest.json")
        if manifest_info.file_size>MAX_MANIFEST_BYTES:raise ValueError("theme manifest is too large")
        data = json.loads(package.read("manifest.json"))
        if data.get("format") != FORMAT or data.get("version") != VERSION:
            raise ValueError("unsupported theme package format/version")
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            raise ValueError("theme profiles are malformed")
        warnings: list[str] = []
        layouts=data.get("monitor_layouts",{})
        if not isinstance(layouts,dict):raise ValueError("theme layouts are malformed")
        def validate_asset_reference(raw:dict,key:str)->None:
            value=raw.get(key,"")
            if not value:return
            if not isinstance(value,str):raise ValueError("theme asset reference is malformed")
            member=PurePosixPath(value)
            if member.is_absolute() or Path(value).is_absolute() or ".." in member.parts or "\\" in value:raise ValueError("unsafe theme asset reference")
            if not value.startswith("assets/") or value not in names:raise ValueError("referenced theme asset is missing")
        for profile_layouts in layouts.values():
            if not isinstance(profile_layouts,dict):raise ValueError("theme profile layouts are malformed")
            for layout in profile_layouts.values():
                if not isinstance(layout,dict):raise ValueError("theme layout is malformed")
                validate_asset_reference(layout,"background_image")
                for element in layout.get("elements",[]):
                    if not isinstance(element,dict):raise ValueError("theme element is malformed")
                    validate_asset_reference(element,"image")
        expected = {"0416:5408", "0416:5302"}
        for profile_name, devices in profiles.items():
            if not isinstance(devices, dict):
                raise ValueError(f"profile {profile_name!r} is malformed")
            unknown = set(devices) - expected
            if unknown:
                warnings.append(f"{profile_name}: unsupported display identities: {', '.join(sorted(unknown))}")
            for device, raw in devices.items():
                if device in expected:
                    DisplayProfile(**raw)  # schema validation
        if data.get("media_included") and media_directory:
            media_directory = Path(media_directory)
            media_directory.mkdir(parents=True, exist_ok=True)
            for devices in profiles.values():
                for raw in devices.values():
                    member = raw.get("media", "")
                    if member.startswith("media/") and member in names:
                        destination = media_directory / Path(member).name
                        with package.open(member) as src, destination.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        raw["media"] = str(destination)
        if media_directory:
            asset_directory=Path(media_directory)/"theme-assets";asset_directory.mkdir(parents=True,exist_ok=True)
            extracted: dict[str,str]={}
            def extract_asset(raw:dict,key:str)->None:
                member=raw.get(key,"")
                if not isinstance(member,str) or not member.startswith("assets/") or member not in names:return
                destination=asset_directory/Path(member).name
                if member not in extracted:
                    with package.open(member) as src,destination.open("wb") as dst:shutil.copyfileobj(src,dst)
                    extracted[member]=str(destination)
                raw[key]=extracted[member]
            if isinstance(layouts,dict):
                for profile_layouts in layouts.values():
                    if not isinstance(profile_layouts,dict):continue
                    for layout in profile_layouts.values():
                        if not isinstance(layout,dict):continue
                        extract_asset(layout,"background_image")
                        for element in layout.get("elements",[]):
                            if isinstance(element,dict):extract_asset(element,"image")
        return data, warnings


def merge_theme(settings: AppSettings, data: dict) -> None:
    for name, devices in data["profiles"].items():
        settings.profiles[name] = {
            device: DisplayProfile(**raw)
            for device, raw in devices.items()
            if device in {"0416:5408", "0416:5302"}
        }
    settings.monitor_layouts.update(data.get("monitor_layouts", {}))
