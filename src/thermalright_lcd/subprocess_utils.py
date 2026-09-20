from __future__ import annotations

import os
import subprocess


def hidden_subprocess_kwargs(platform: str | None = None) -> dict:
    """Scoped flags for GUI-owned commands; never patches subprocess globally."""
    platform = os.name if platform is None else platform
    if platform != "nt": return {}
    startup = subprocess.STARTUPINFO();startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
    return {"creationflags":subprocess.CREATE_NO_WINDOW,"startupinfo":startup}
