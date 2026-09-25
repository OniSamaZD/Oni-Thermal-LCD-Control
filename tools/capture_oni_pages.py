"""Capture deterministic screenshots of the real integrated ONI application pages."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import thermalright_lcd.gui as gui
from thermalright_lcd.device_connection import DisabledHardwareSender


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns): app.processEvents()


def capture(window, app, target: Path) -> None:
    settle(app); target.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(target), "PNG"): raise RuntimeError(f"could not save {target}")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, default=Path("temp/oni-page-qa")); parser.add_argument("--width", type=int, default=1920); parser.add_argument("--height", type=int, default=1080); args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="oni-pages-") as local_data:
        os.environ["LOCALAPPDATA"] = local_data; gui.build_gui_sender = lambda _device_id: DisabledHardwareSender("page capture")
        app = QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False); app.setStyleSheet(gui.STYLE)
        window = gui.MainWindow(); window.resize(args.width, args.height); window.show(); settle(app)
        names = ("home", "media-library", "sensor-themes", "profiles", "hardware-monitor", "performance", "settings", "diagnostics")
        for index, name in enumerate(names): window.select_page(index, open_dialog=False); settle(app); capture(window, app, args.output / f"{name}-{args.width}x{args.height}.png")
        window.open_sensor_studio(); settle(app); capture(window, app, args.output / f"sensor-studio-{args.width}x{args.height}.png")
        window._force_exit = True; window.shutdown(); window.close(); settle(app)
    print(f"Captured {len(names) + 1} pages in {args.output.resolve()}"); return 0


if __name__ == "__main__": raise SystemExit(main())
