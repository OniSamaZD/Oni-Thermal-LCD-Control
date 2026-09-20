from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import thermalright_lcd.gui as gui
from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.hardware_monitor import templates
from thermalright_lcd.monitor_designer import HardwareMonitorDesigner, ThemeGalleryDialog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--preview-scale", type=int, default=100)
    parser.add_argument("--monitor-edit", action="store_true")
    parser.add_argument("--collapsed-sidebar", action="store_true")
    parser.add_argument("--surface", choices=("home","gallery","designer"), default="home")
    parser.add_argument("--theme", default="Oni Crimson")
    args = parser.parse_args()
    args.output = args.output.resolve()

    os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="oni-ui-capture-")
    os.environ["ONI_LCD_INSTANCE_NAME"] = f"OniUiCapture-{os.getpid()}"
    gui.build_gui_sender = lambda _device_id: DisabledHardwareSender("screenshot capture")
    # Screenshot validation is intentionally read-only with respect to the
    # user's real Oni settings/profile store.
    gui.SettingsStore.save = lambda self, _settings: None
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(gui.STYLE)
    window = gui.MainWindow()
    window.resize(args.width, args.height)
    if args.collapsed_sidebar:window.set_sidebar_expanded(False,save=False)
    for card in (window.left, window.right):
        card.preview_scale_slider.setValue(args.preview_scale)
    if args.monitor_edit:
        card = window.left
        card.monitor_template.setCurrentText("Gaming Dashboard")
        card.quick_edit.setChecked(True)
        editor = card.home_quick_editor
        if editor.layout.elements:
            selected_id = editor.layout.elements[0].id
            editor.scene.items_by_id[selected_id].setSelected(True)
            editor.select_element(selected_id)
        if hasattr(card, "context_tabs"):
            card.context_tabs.setCurrentWidget(card.monitor_tab)
    window.show()
    app.processEvents()
    window.display_splitter.setSizes([1, 1])
    for _ in range(3):
        app.processEvents()
    surface=window
    if args.surface=="gallery":surface=ThemeGalleryDialog(window.settings,window.store,window);surface.resize(args.width,args.height);surface.show()
    elif args.surface=="designer":
        window.settings.monitor_layouts.setdefault(window.settings.active_profile,{})["0416:5408"]=templates("0416:5408")[args.theme].to_dict();surface=HardwareMonitorDesigner(window.settings,window.store,window);surface.resize(args.width,args.height);surface.show()
        if surface.layout.elements:surface.scene.items_by_id[surface.layout.elements[0].id].setSelected(True);surface.select_element(surface.layout.elements[0].id)
    for _ in range(4):app.processEvents()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not surface.grab().save(str(args.output), "PNG"):
        raise RuntimeError(f"could not save {args.output}")
    if surface is not window:surface.close()
    window.shutdown()


if __name__ == "__main__":
    main()
