"""Collect installed wheel license files for the distributable notice bundle."""

from __future__ import annotations

import importlib.metadata
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "third-party-licenses"
PACKAGES = (
    "PyInstaller", "PySide6", "PySide6_Essentials", "PySide6_Addons",
    "shiboken6", "Pillow", "psutil", "opencv-python", "numpy",
)


def main() -> int:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    for name in PACKAGES:
        distribution = importlib.metadata.distribution(name)
        target = OUTPUT / f"{name}-{distribution.version}"
        target.mkdir()
        found = 0
        for item in distribution.files or ():
            normalized = str(item).replace("\\", "/").lower()
            if not any(token in normalized for token in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(item))
            if not source.is_file():
                continue
            destination = target / source.name
            if destination.exists():
                destination = target / f"{found:02d}-{source.name}"
            shutil.copy2(source, destination)
            found += 1
        (target / "PACKAGE.txt").write_text(
            f"Name: {name}\nVersion: {distribution.version}\n"
            f"License expression: {distribution.metadata.get('License-Expression', '')}\n",
            encoding="utf-8",
        )
        if not found:
            (target / "LICENSE-NOT-PRESENT-IN-WHEEL.txt").write_text(
                "No standalone license file was present in the installed wheel. "
                "Consult THIRD_PARTY_NOTICES.md and the upstream distribution.\n",
                encoding="utf-8",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
