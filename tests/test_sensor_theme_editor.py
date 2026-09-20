from __future__ import annotations

import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.sensor_theme import ELEMENT_TYPES
from thermalright_lcd.sensor_theme_editor import (
    SAMPLE_SENSOR_VALUES, SensorThemeDocument, SensorThemeEditorPage,
)
from thermalright_lcd.sensor_theme_store import SensorThemeStore


ROOT = Path(__file__).resolve().parents[1]


class SensorThemeDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = SensorThemeStore(Path(self.temp.name) / "user", ROOT / "assets" / "sensor-themes")
        self.document = SensorThemeDocument(self.store)
        self.document.load(self.store.get("oni-cyber-blue"))

    def test_builtin_theme_loads_and_cannot_be_overwritten(self):
        self.assertTrue(self.document.built_in); self.assertEqual(self.document.theme.name, "ONI Cyber Blue")
        with self.assertRaisesRegex(ValueError, "Save As"):
            self.document.save()

    def test_duplicate_builtin_creates_editable_user_theme(self):
        target = self.document.duplicate_theme("My ONI Copy")
        self.assertTrue(target.is_file()); self.assertFalse(self.document.built_in)
        self.assertEqual(self.store.get(self.document.theme.id).theme.name, "My ONI Copy")

    def test_user_theme_save_and_roundtrip_after_edits(self):
        self.document.new("Editable", preset="custom", width=800, height=300)
        element = self.document.add_element("sensor_value", (120, 80))
        self.document.set_property(element.id, "sensor_binding", "gpu.temperature")
        self.document.set_property(element.id, "text_color", "#FF00AA")
        self.document.save()
        loaded = self.store.get(self.document.theme.id).theme
        self.assertEqual(loaded.elements[0].sensor_binding, "gpu.temperature")
        self.assertEqual(loaded.elements[0].text_color, "#FF00AA")

    def test_dirty_add_delete_and_discard(self):
        self.assertFalse(self.document.dirty)
        element = self.document.add_element("text"); self.assertTrue(self.document.dirty)
        self.document.delete([element.id]); self.assertEqual(len(self.document.theme.elements), 11)
        self.assertTrue(self.document.discard_changes()); self.assertFalse(self.document.dirty)

    def test_every_phase_one_element_type_can_be_added(self):
        self.document.new("All Elements")
        created = {self.document.add_element(kind).type for kind in ELEMENT_TYPES}
        self.assertEqual(created, ELEMENT_TYPES)

    def test_move_and_resize_are_single_undoable_interaction(self):
        element = self.document.theme.elements[0]; original = (element.x, element.y, element.width, element.height)
        self.document.begin_interaction(); element.x += 40; element.y += 15; element.width += 25; element.height += 10
        self.assertTrue(self.document.end_interaction()); self.assertTrue(self.document.can_undo)
        self.document.undo(); restored = self.document.element(element.id)
        self.assertEqual((restored.x, restored.y, restored.width, restored.height), original)
        self.document.redo(); changed = self.document.element(element.id)
        self.assertEqual((changed.x, changed.y), (original[0] + 40, original[1] + 15))

    def test_property_sensor_z_lock_and_visibility_edits(self):
        element = self.document.theme.elements[0]
        self.document.set_property(element.id, "rotation", 22.5)
        sensor = self.document.add_element("sensor_value")
        self.document.set_property(sensor.id, "sensor_binding", "gpu.power")
        self.document.reorder([sensor.id], "front"); self.document.set_flag([sensor.id], "locked", True); self.document.set_flag([sensor.id], "visible", False)
        edited = self.document.element(sensor.id)
        self.assertEqual(edited.sensor_binding, "gpu.power"); self.assertTrue(edited.locked); self.assertFalse(edited.visible)
        self.assertEqual(edited.z_index, max(item.z_index for item in self.document.theme.elements))

    def test_copy_paste_duplicate_and_delete(self):
        source = self.document.theme.elements[0]; self.document.copy([source.id]); pasted = self.document.paste()
        self.assertEqual(len(pasted), 1); self.assertNotEqual(pasted[0], source.id)
        duplicated = self.document.duplicate_elements(pasted); self.assertEqual(len(duplicated), 1)
        self.document.delete(duplicated); self.assertIsNone(self.document.element(duplicated[0]))

    def test_import_export_integration_with_preview(self):
        self.document.save_as("Package Source")
        package = self.document.export_package(Path(self.temp.name) / "shared.oni-theme")
        imported = self.document.import_package(package)
        self.assertNotEqual(imported.id, "package-source"); self.assertEqual(imported.name, "Package Source (2)")

    def test_display_preset_switch_scales_without_destroying_layout(self):
        before = self.document.theme.elements[0].to_dict(); self.document.change_canvas("0416:5302", scale=True)
        after = self.document.theme.elements[0]
        self.assertEqual((self.document.theme.canvas.width, self.document.theme.canvas.height), (1280, 480))
        self.assertAlmostEqual(after.x, before["x"] * 1280 / 1920)
        self.document.undo(); self.assertEqual(self.document.theme.canvas.preset, "0416:5408")

    def test_image_asset_is_copied_and_survives_save(self):
        source = Path(self.temp.name) / "picture.png"; Image.new("RGB", (40, 30), "cyan").save(source)
        self.document.new("Images"); element = self.document.add_element("image")
        relative = self.document.add_resource_file(source); self.document.set_property(element.id, "asset", relative); self.document.save()
        stored = self.store.get(self.document.theme.id)
        self.assertTrue((stored.root / relative).is_file()); self.assertEqual(stored.theme.elements[0].asset, relative)


class SensorThemeEditorWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = SensorThemeStore(Path(self.temp.name) / "user", ROOT / "assets" / "sensor-themes")
        self.page = SensorThemeEditorPage(self.store, prompt_handler=lambda _action: "discard")
        self.page.resize(1500, 850); self.page.show(); self.app.processEvents()
        self.addCleanup(self.page.close)

    def test_editor_opens_with_required_panels_and_toolbar(self):
        self.assertEqual(self.page.document.theme.id, "oni-cyber-blue")
        self.assertEqual([self.page.left_tabs.tabText(index) for index in range(3)], ["Themes", "Elements", "Layers"])
        self.assertTrue({"New", "Open", "Save", "Save As", "Duplicate", "Import", "Export", "Undo", "Redo"}.issubset(self.page.actions))
        self.assertGreater(self.page.canvas.width(), 500); self.assertGreater(self.page.properties.width(), 280)

    def test_theme_browser_shows_builtin_metadata_and_thumbnails(self):
        self.assertEqual(self.page.theme_list.count(), 4)
        first = self.page.theme_list.item(0)
        self.assertIn("Built-in", first.text()); self.assertFalse(first.icon().isNull())

    def test_palette_layers_and_selection_handles(self):
        self.assertEqual(self.page.palette.count(), len(ELEMENT_TYPES))
        first_id = self.page.document.theme.elements[0].id; self.page.scene.select_ids([first_id]); self.app.processEvents()
        item = self.page.scene.items_by_id[first_id]
        self.assertEqual(len(item._handles()), 9); self.assertIs(self.page.properties.element, item.element)
        self.assertEqual(self.page.layers.count(), len(self.page.document.theme.elements))

    def test_canvas_drag_and_resize_each_create_one_history_entry(self):
        element_id = self.page.document.theme.elements[0].id; self.page.scene.select_ids([element_id]); self.app.processEvents()
        item = self.page.scene.items_by_id[element_id]; history = len(self.page.document._history)
        start = self.page.canvas.mapFromScene(item.sceneBoundingRect().center()); end = start + QPoint(55, 25)
        QTest.mousePress(self.page.canvas.viewport(), Qt.LeftButton, pos=start); QTest.mouseMove(self.page.canvas.viewport(), end, 50); QTest.mouseMove(self.page.canvas.viewport(), end + QPoint(10, 5), 50); QTest.mouseRelease(self.page.canvas.viewport(), Qt.LeftButton, pos=end + QPoint(10, 5)); self.app.processEvents()
        self.assertEqual(len(self.page.document._history), history + 1)
        item = self.page.scene.items_by_id[element_id]; history = len(self.page.document._history)
        handle = self.page.canvas.mapFromScene(item.mapToScene(item._handles()["se"].center())); end = handle + QPoint(35, 25)
        QTest.mousePress(self.page.canvas.viewport(), Qt.LeftButton, pos=handle); QTest.mouseMove(self.page.canvas.viewport(), end, 50); QTest.mouseRelease(self.page.canvas.viewport(), Qt.LeftButton, pos=end); self.app.processEvents()
        self.assertEqual(len(self.page.document._history), history + 1)

    def test_canvas_keeps_selected_display_aspect_ratio(self):
        mapped = self.page.canvas.mapFromScene(self.page.scene.sceneRect()).boundingRect()
        self.assertAlmostEqual(mapped.width() / mapped.height(), 1920 / 462, delta=.03)

    def test_property_edit_refreshes_production_renderer_preview(self):
        element_id = self.page.document.theme.elements[0].id; self.page.scene.select_ids([element_id]); self.app.processEvents()
        before = self.page.scene.renderer.render_count
        self.page.apply_property("text", "VISUAL EDIT"); self.app.processEvents(); self.page.scene._preview_cache = None
        pixmap = self.page.canvas.grab(); self.app.processEvents()
        self.assertEqual(self.page.document.element(element_id).text, "VISUAL EDIT")
        self.assertGreater(self.page.scene.renderer.render_count, before); self.assertFalse(pixmap.isNull())

    def test_dirty_prompt_cancel_and_discard(self):
        original = self.page.document.theme.id; self.page.document.add_element("text")
        self.page.prompt_handler = lambda _action: "cancel"
        self.assertFalse(self.page.load_theme("minimal-dark")); self.assertEqual(self.page.document.theme.id, original)
        self.page.prompt_handler = lambda _action: "discard"
        self.assertTrue(self.page.load_theme("minimal-dark")); self.assertEqual(self.page.document.theme.id, "minimal-dark")

    def test_dirty_navigation_cancel_keeps_editor_open(self):
        stack = QStackedWidget(); other = QWidget(); stack.addWidget(other); stack.addWidget(self.page); self.page.attach_navigation_guard(stack)
        stack.setCurrentWidget(self.page); self.app.processEvents(); self.page.document.add_element("text"); self.page.prompt_handler = lambda _action: "cancel"
        stack.setCurrentWidget(other); self.app.processEvents()
        self.assertIs(stack.currentWidget(), self.page)

    def test_undo_redo_buttons_follow_history(self):
        self.page.document.add_element("clock"); self.app.processEvents()
        self.assertTrue(self.page.actions["Undo"].isEnabled()); self.page.document.undo(); self.app.processEvents()
        self.assertTrue(self.page.actions["Redo"].isEnabled()); self.page.document.redo(); self.app.processEvents()

    def test_hidden_layer_can_be_selected_and_shown_again(self):
        element_id = self.page.document.theme.elements[0].id; self.page.scene.select_ids([element_id]); self.page.toggle_visibility(); self.app.processEvents()
        self.assertFalse(self.page.document.element(element_id).visible)
        layer = next(self.page.layers.item(index) for index in range(self.page.layers.count()) if self.page.layers.item(index).data(Qt.UserRole) == element_id)
        self.page.layers.setCurrentItem(layer); layer.setSelected(True); self.page.layer_selection_changed(); self.page.toggle_visibility(); self.app.processEvents()
        self.assertTrue(self.page.document.element(element_id).visible)

    def test_missing_and_live_preview_modes_are_read_only(self):
        calls = []
        self.page.live_value_provider = lambda: calls.append(True) or SAMPLE_SENSOR_VALUES
        self.page.preview_mode.setCurrentText("Missing Data"); self.assertEqual(self.page.scene.values, {})
        self.page.preview_mode.setCurrentText("Live Sensors"); self.app.processEvents()
        self.assertTrue(calls); self.assertEqual(self.page.scene.values, SAMPLE_SENSOR_VALUES)

    def test_editor_module_has_no_transport_or_session_dependency(self):
        import thermalright_lcd.sensor_theme_editor as module
        source = inspect.getsource(module)
        for forbidden in ("DisplaySession", "build_gui_sender", "windows_usb", "session.stop", "session.reset"):
            self.assertNotIn(forbidden, source)

    def test_main_window_sensor_page_replacement_preserves_sessions(self):
        from thermalright_lcd.gui import MainWindow
        with patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}), patch("thermalright_lcd.gui.build_gui_sender", side_effect=lambda _device: DisabledHardwareSender()):
            window = MainWindow(); sessions = (window.left.session, window.right.session)
            window.open_theme_gallery(); self.app.processEvents()
            self.assertIs(window.pages.currentWidget(), window.sensor_theme_editor)
            self.assertEqual((window.left.session, window.right.session), sessions)
            window.shutdown()


if __name__ == "__main__":
    unittest.main()
