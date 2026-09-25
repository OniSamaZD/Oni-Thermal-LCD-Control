from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import tempfile
import time
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
        self.document.new("Editor Fixture"); self.document.add_element("sensor_value"); self.document.save()

    def test_new_theme_is_blank_before_user_adds_content(self):
        blank = SensorThemeDocument(self.store); blank.new("Blank")
        self.assertFalse(blank.built_in); self.assertEqual(blank.theme.elements, [])

    def test_duplicate_user_theme_creates_editable_user_theme(self):
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
        self.document.delete([element.id]); self.assertEqual(len(self.document.theme.elements), 1)
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

    def test_alignment_uses_exact_canvas_coordinates(self):
        self.document.new("Alignment", preset="custom", width=800, height=300)
        first = self.document.add_element("text", (10, 20)); second = self.document.add_element("text", (310, 90))
        self.document.set_property(first.id, "width", 100); self.document.set_property(second.id, "width", 200)
        self.assertTrue(self.document.align([first.id, second.id], "left"))
        self.assertEqual((self.document.element(first.id).x, self.document.element(second.id).x), (10, 10))
        self.assertTrue(self.document.align([first.id, second.id], "vcenter"))
        self.assertEqual(self.document.element(first.id).y, self.document.element(second.id).y)

    def test_external_json_and_background_round_trip_preserves_exact_pixels(self):
        for preset, dimensions in (("0416:5302", (1280, 480)), ("0416:5408", (1920, 462))):
            with self.subTest(preset=preset):
                self.document.new(f"Exact {preset}", preset=preset)
                widget = self.document.add_element("sensor_label_value", (105, 82))
                for name, value in (("width", 321), ("height", 77), ("sensor_binding", "gpu.temperature")):
                    self.document.set_property(widget.id, name, value)
                background = Path(self.temp.name) / f"{preset.replace(':', '-')}.png"
                Image.new("RGB", dimensions, "#071522").save(background)
                self.document.import_background(background)
                exported = self.document.export_json(Path(self.temp.name) / f"{preset}.json")
                loaded = SensorThemeDocument(self.store); loaded.import_json(exported)
                restored = loaded.element(widget.id)
                self.assertEqual((loaded.theme.canvas.width, loaded.theme.canvas.height), dimensions)
                self.assertEqual((restored.x, restored.y, restored.width, restored.height), (105, 82, 321, 77))
                self.assertEqual(restored.sensor_binding, "gpu.temperature")
                self.assertTrue(loaded.theme.background_asset.startswith("assets/"))

    def test_external_json_import_is_bounded_and_rejects_unknown_code_fields(self):
        oversized = Path(self.temp.name) / "oversized.json"; oversized.write_bytes(b" " * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "2 MB"):
            self.document.import_json(oversized)
        malicious = Path(self.temp.name) / "malicious.json"
        raw = self.document.theme.to_dict(); raw["python"] = "__import__('os').system('echo unsafe')"
        malicious.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown theme properties"):
            self.document.import_json(malicious)

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
        fixture = SensorThemeDocument(self.store); fixture.new("Editor Fixture"); fixture.add_element("sensor_value"); fixture.save()
        self.page = SensorThemeEditorPage(self.store, prompt_handler=lambda _action: "discard")
        self.page.resize(1500, 850); self.page.show(); self.app.processEvents()
        self.addCleanup(self.page.close)

    def test_editor_opens_with_required_panels_and_toolbar(self):
        self.assertEqual(self.page.document.theme.id, "editor-fixture")
        self.assertEqual([self.page.left_tabs.tabText(index) for index in range(4)], ["Sensors", "Widgets", "Layers", "Layouts"])
        self.assertTrue({"New", "Open", "Save", "Save As", "Import", "Export", "Undo", "Redo"}.issubset(self.page.actions))
        self.assertGreater(self.page.canvas.width(), 500); self.assertGreater(self.page.properties.width(), 280)

    def test_theme_browser_shows_builtin_metadata_and_thumbnails(self):
        self.assertEqual(self.page.theme_list.count(), 1)
        first = self.page.theme_list.item(0)
        self.assertIn("User", first.text()); self.assertFalse(first.icon().isNull())

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

    def test_canvas_edit_does_not_refresh_layout_thumbnails_or_refit_canvas(self):
        element_id = self.page.document.theme.elements[0].id
        with patch.object(self.page, "refresh_theme_browser") as thumbnails, patch.object(self.page, "fit_canvas") as fit:
            self.page.document.set_property(element_id, "x", 123)
            self.app.processEvents()
        thumbnails.assert_not_called(); fit.assert_not_called()

    def test_dirty_prompt_cancel_and_discard(self):
        alternate = self.store.create("Alternate"); self.store.save(alternate)
        original = self.page.document.theme.id; self.page.document.add_element("text")
        self.page.prompt_handler = lambda _action: "cancel"
        self.assertFalse(self.page.load_theme("alternate")); self.assertEqual(self.page.document.theme.id, original)
        self.page.prompt_handler = lambda _action: "discard"
        self.assertTrue(self.page.load_theme("alternate")); self.assertEqual(self.page.document.theme.id, "alternate")

    def test_dirty_navigation_is_resolved_before_page_stack_changes(self):
        stack = QStackedWidget(); other = QWidget(); stack.addWidget(other); stack.addWidget(self.page); self.page.attach_navigation_guard(stack)
        stack.setCurrentWidget(self.page); self.app.processEvents(); self.page.document.add_element("text"); self.page.prompt_handler = lambda _action: "cancel"
        self.assertFalse(self.page.request_leave());self.assertIs(stack.currentWidget(),self.page)
        self.page.prompt_handler=lambda _action:"discard";self.assertTrue(self.page.request_leave());stack.setCurrentWidget(other);self.assertIs(stack.currentWidget(),other)

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

    def test_sensor_browser_search_category_and_real_availability(self):
        self.page.live_value_provider = lambda: {"cpu.usage": 42}
        self.page.refresh_sensor_availability(); self.page.sensor_search.setText("CPU Usage")
        self.assertEqual(self.page.sensor_list.count(), 1)
        self.assertIn("Available", self.page.sensor_list.item(0).text())
        self.page.sensor_search.clear(); self.page.sensor_category.setCurrentText("GPU")
        self.assertGreater(self.page.sensor_list.count(), 1)
        self.assertTrue(all("gpu." in self.page.sensor_list.item(index).text().casefold() for index in range(self.page.sensor_list.count())))

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
            self.assertIs(window.pages.currentWidget(), window.sensor_theme_workspace)
            self.assertIs(window.sensor_theme_workspace.stack.currentWidget(), window.sensor_theme_workspace.browser)
            self.assertTrue(window.open_sensor_studio()); self.app.processEvents()
            self.assertIs(window.sensor_theme_workspace.stack.currentWidget(), window.sensor_theme_editor)
            self.assertEqual((window.left.session, window.right.session), sessions)
            window.shutdown()

    def test_repeated_edit_home_save_discard_cancel_is_non_reentrant_and_preserves_runtime(self):
        from thermalright_lcd.gui import MainWindow
        with patch.dict(os.environ,{"LOCALAPPDATA":self.temp.name}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _device:DisabledHardwareSender()):
            window=MainWindow();sessions=tuple(card.session for card in window.cards);window.open_theme_gallery();page=window.sensor_theme_editor
            page.document.new("Navigation Stress","0416:5302");page.document.save();window.apply_sensor_theme(page.document.theme,page.document.asset_root,tuple(card.device_id for card in window.cards),1)
            legitimate={window,window.tray_menu};before=set(QApplication.topLevelWidgets());started=time.monotonic()
            for cycle in range(18):
                self.assertTrue(window.open_sensor_studio(page.document.theme.id));page.document.add_element("text")
                if cycle%3==0:
                    page.prompt_handler=lambda _action:"cancel";self.assertFalse(window.select_page(0));self.assertIs(window.pages.currentWidget(),window.sensor_theme_workspace);self.assertIs(window.sensor_theme_workspace.stack.currentWidget(),page)
                    page.prompt_handler=lambda _action:"discard";self.assertTrue(window.select_page(0))
                elif cycle%3==1:
                    page.prompt_handler=lambda _action:"discard";self.assertTrue(window.select_page(0))
                else:
                    self.assertTrue(page.save());page.prompt_handler=lambda _action:"cancel";self.assertTrue(window.select_page(0))
                self.app.processEvents();self.assertEqual(tuple(card.session for card in window.cards),sessions)
            self.assertLess(time.monotonic()-started,8)
            unexpected=[widget for widget in set(QApplication.topLevelWidgets())-before if widget not in legitimate and widget.parent() is None]
            self.assertFalse(unexpected,[(type(widget).__name__,widget.windowTitle()) for widget in unexpected]);window.shutdown()


if __name__ == "__main__":
    unittest.main()
