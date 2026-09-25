"""Capture deterministic Phase 2 Sensor Theme editor acceptance screenshots."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import thermalright_lcd.gui as gui
from thermalright_lcd.device_connection import DisabledHardwareSender


def capture(window, editor, target: Path, selected_id: str | None = None) -> None:
    QApplication.processEvents(); QApplication.processEvents()
    editor.scene.mark_preview_dirty(); editor.refresh_theme_browser(); editor.fit_canvas()
    if editor.document.theme.elements:
        editor.scene.select_ids([selected_id or editor.document.theme.elements[0].id])
    QApplication.processEvents(); QApplication.processEvents()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(target), "PNG"):
        raise RuntimeError(f"could not save {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("temp/sensor-theme-editor-screenshots"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="oni-theme-editor-") as local_data:
        os.environ["LOCALAPPDATA"] = local_data
        gui.build_gui_sender = lambda _device_id: DisabledHardwareSender("editor screenshot")
        app = QApplication.instance() or QApplication([]); app.setStyleSheet(gui.STYLE); app.setQuitOnLastWindowClosed(False)
        window = gui.MainWindow(); window.resize(1600, 960); window.show(); window.open_theme_gallery(); app.processEvents()
        editor = window.sensor_theme_editor
        fixed_now = lambda: datetime(2026, 9, 20, 9, 28, 3)
        editor.now_provider = fixed_now; editor.scene.now_provider = fixed_now
        capture(window, editor, args.output / "blank-theme-editor.png")
        editor.document.save_as("Custom ONI Layout")
        added = editor.document.add_element("text", (760, 360)); editor.document.set_property(added.id, "text", "CUSTOM LAYOUT")
        editor.document.set_property(added.id, "text_color", "#FFB020"); editor.document.set_property(added.id, "font_size", 26)
        capture(window, editor, args.output / "custom-modified-editor.png", added.id)
        window._force_exit = True; window.shutdown(); window.close(); QTimer.singleShot(0, app.quit); app.processEvents()
    print(f"Captured 2 editor screenshots in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
