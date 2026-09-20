from __future__ import annotations

from enum import Enum
from pathlib import Path


class MediaKind(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    GIF = "gif"


PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
GIF_EXTENSIONS = frozenset({".gif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"})
SUPPORTED_MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | GIF_EXTENSIONS | VIDEO_EXTENSIONS


def detect_media_kind(path: str | Path) -> MediaKind | None:
    """Classify every supported media entry point with one deterministic rule.

    WebP is inspected only when the file exists, because that container can be
    static or animated. All entry points still use this one helper.
    """
    suffix = Path(path).suffix.casefold()
    if suffix in GIF_EXTENSIONS:
        return MediaKind.GIF
    if suffix in VIDEO_EXTENSIONS:
        return MediaKind.VIDEO
    if suffix == ".webp" and Path(path).is_file():
        try:
            from PIL import Image
            with Image.open(path) as image:
                return MediaKind.GIF if bool(getattr(image, "is_animated", False)) else MediaKind.PHOTO
        except (OSError, ValueError):
            return None
    if suffix in PHOTO_EXTENSIONS:
        return MediaKind.PHOTO
    return None


def media_filter(kind: MediaKind | None = None) -> str:
    if kind is MediaKind.PHOTO:
        return "Photos (*.jpg *.jpeg *.png *.webp)"
    if kind is MediaKind.GIF:
        return "Animated GIF (*.gif)"
    if kind is MediaKind.VIDEO:
        return "Videos (*.mp4 *.webm *.mkv *.mov *.avi *.m4v)"
    return "Images and media (*.jpg *.jpeg *.png *.webp *.gif *.mp4 *.webm *.mkv *.mov *.avi *.m4v)"
