from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.hardware_monitor import MonitorElement, MonitorLayout
from thermalright_lcd.output_mode import OutputMode
from thermalright_lcd.sensor_theme import SensorTheme, ThemeCanvas, ThemeElement
from thermalright_lcd.sensor_theme_runtime import MAX_HISTORY_SAMPLES, SensorThemeOutputRuntime
from thermalright_lcd.settings import AppSettings, DisplayProfile, SettingsStore


def make_theme(theme_id="runtime-theme", *, binding="cpu.usage", graph=False, static=False):
    if static:
        elements = [ThemeElement("title", "Title", "text", 10, 10, 180, 40, text="ONI")]
    else:
        kind = "line_graph" if graph else "sensor_value"
        elements = [ThemeElement("value", "Value", kind, 10, 10, 240, 80, sensor_binding=binding, history_duration=1)]
    return SensorTheme(theme_id, theme_id.replace("-", " ").title(), ThemeCanvas(320, 120), elements)


class SensorThemeRuntimeTests(unittest.TestCase):
    def test_displays_are_independent_and_render_exact_sizes(self):
        runtime = SensorThemeOutputRuntime(clock=lambda: 0)
        runtime.apply("0416:5408", make_theme("wide"), fps=2)
        runtime.apply("0416:5302", make_theme("small", binding="gpu.usage"), fps=5)
        wide = runtime.render_due("0416:5408", {"cpu.usage": 42}, monotonic_now=0)
        small = runtime.render_due("0416:5302", {"gpu.usage": 73}, monotonic_now=0)
        self.assertEqual(wide.size, (1920, 462)); self.assertEqual(small.size, (1280, 480))
        wide.close(); small.close()
        runtime.stop("0416:5408")
        self.assertIsNone(runtime.state("0416:5408")); self.assertIsNotNone(runtime.state("0416:5302"))

    def test_fps_cap_static_skip_and_inactive_output(self):
        runtime = SensorThemeOutputRuntime(clock=lambda: 0)
        self.assertIsNone(runtime.render_due("0416:5408", {}, monotonic_now=0))
        state = runtime.apply("0416:5408", make_theme(static=True), fps=1)
        image = runtime.render_due("0416:5408", {}, monotonic_now=0); image.close()
        self.assertIsNone(runtime.render_due("0416:5408", {}, monotonic_now=.5))
        self.assertIsNone(runtime.render_due("0416:5408", {}, monotonic_now=1))
        self.assertEqual(state.render_count, 1); self.assertFalse(runtime.needs_updates("0416:5408"))
        with self.assertRaises(ValueError): runtime.apply("0416:5408", make_theme(), fps=60)

    def test_live_refresh_missing_fallback_and_bounded_graph_history(self):
        runtime = SensorThemeOutputRuntime(clock=lambda: 0)
        state = runtime.apply("0416:5302", make_theme(graph=True), fps=30)
        first = runtime.render_due("0416:5302", {}, monotonic_now=0, wall_time=datetime(2026, 1, 1)); first.close()
        for index in range(1, 181):
            image = runtime.render_due("0416:5302", {"cpu.usage": index % 100}, monotonic_now=index / 30)
            if image: image.close()
        self.assertLessEqual(len(state.history["cpu.usage"]), 32)
        self.assertLessEqual(len(state.history["cpu.usage"]), MAX_HISTORY_SAMPLES)
        self.assertGreater(state.render_count, 2); self.assertEqual(state.error_count, 0)

    def test_renderer_failure_is_contained(self):
        runtime = SensorThemeOutputRuntime(clock=lambda: 0); state = runtime.apply("0416:5408", make_theme(), fps=2)
        state.renderer.render = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed"))
        self.assertIsNone(runtime.render_due("0416:5408", {"cpu.usage": 1}, monotonic_now=0))
        self.assertEqual(state.error_count, 1); self.assertIn("render failed", state.last_error)


class SensorThemeOutputIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def pump(self, seconds=.08):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents(); time.sleep(.005)

    def window(self, folder):
        stack = patch.dict(os.environ, {"LOCALAPPDATA": folder}); sender = patch("thermalright_lcd.gui.build_gui_sender", side_effect=lambda _device: DisabledHardwareSender())
        stack.start(); sender.start(); self.addCleanup(sender.stop); self.addCleanup(stack.stop)
        window = MainWindow(); self.addCleanup(window.shutdown); return window

    def test_unsaved_editor_apply_and_save_refresh_same_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); sessions = (window.left.session, window.right.session); window.open_theme_gallery(); page = window.sensor_theme_editor
            self.assertIs(page.parent(), window.pages); self.assertFalse(page.isWindow())
            page.document.new("Live Draft"); element = page.document.add_element("text"); page.document.set_property(element.id, "text", "BEFORE")
            self.assertTrue(page.apply_to_display()); state = window.sensor_theme_runtime.state("0416:5408")
            self.assertEqual(state.theme.elements[0].text, "BEFORE"); self.assertTrue(page.document.dirty)
            page.document.set_property(element.id, "text", "AFTER"); self.assertTrue(page.save()); updated = window.sensor_theme_runtime.state("0416:5408")
            self.assertEqual(updated.theme.elements[0].text, "AFTER"); self.assertEqual((window.left.session, window.right.session), sessions)

    def test_dual_apply_switch_to_media_and_overlay_preserve_media(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); media = Path(folder) / "still.png"; Image.new("RGB", (64, 32), "navy").save(media)
            window.left.load(media); sessions = (window.left.session, window.right.session)
            window.apply_sensor_theme(make_theme(), None, ("0416:5408", "0416:5302"), 2)
            self.assertEqual(set(window.sensor_theme_runtime.active_device_ids), {"0416:5408", "0416:5302"}); self.assertEqual(window.left.path, media)
            window.set_output_mode("0416:5408", OutputMode.MEDIA); self.assertEqual(window.left.path, media); self.assertIsNone(window.sensor_theme_runtime.state("0416:5408")); self.assertIsNotNone(window.sensor_theme_runtime.state("0416:5302"))
            layout = MonitorLayout("Overlay", "0416:5408", 1920, 462, elements=[MonitorElement("label + value", 10, 10, sensor_id="cpu.usage")])
            self.assertTrue(window.start_monitor_overlay("0416:5408", layout)); self.assertEqual(window.left.path, media)
            self.assertEqual(window.settings.output_modes["0416:5408"], OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value)
            self.assertEqual((window.left.session, window.right.session), sessions)

    def test_deleted_active_theme_stays_live_but_missing_restart_stops_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); window.apply_sensor_theme(make_theme("deleted-theme"), None, ("0416:5408",), 2); state = window.sensor_theme_runtime.state("0416:5408")
            window.sensor_theme_document_changed("deleted", None, None, "deleted-theme")
            self.assertIs(window.sensor_theme_runtime.state("0416:5408"), state)
            window.shutdown(); self.app.processEvents()
            restored = self.window(folder); self.pump()
            self.assertIsNone(getattr(restored, "sensor_theme_runtime", None)); self.assertEqual(restored.settings.output_modes["0416:5408"], OutputMode.STOPPED.value)
            self.assertIn("SENSOR THEME MISSING", restored.left.status.text())

    def test_saved_builtin_theme_restores_per_display(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = AppSettings(); settings.output_modes["0416:5302"] = OutputMode.HARDWARE_MONITOR.value; settings.sensor_theme_ids["0416:5302"] = "minimal-dark"; settings.sensor_theme_fps["0416:5302"] = 5
            settings.profiles["Default"]["0416:5302"] = DisplayProfile(desired_playback_state="Playing", output_mode=OutputMode.HARDWARE_MONITOR.value)
            SettingsStore(Path(folder) / "OniThermalLcd" / "settings.json").save(settings)
            window = self.window(folder); self.pump(); state = window.sensor_theme_runtime.state("0416:5302")
            self.assertEqual((state.theme.id, state.fps), ("minimal-dark", 5)); self.assertIsNone(window.sensor_theme_runtime.state("0416:5408"))

    def test_named_monitor_layout_appears_on_home_and_uses_existing_session(self):
        with tempfile.TemporaryDirectory() as folder:
            layout = MonitorLayout("Desk Stats", "0416:5408", 1920, 462, elements=[MonitorElement("clock", 20, 20)])
            settings = AppSettings(); settings.monitor_layout_library = {"0416:5408": {"Desk Stats": layout.to_dict()}}; settings.monitor_templates["0416:5408"] = "Desk Stats"
            SettingsStore(Path(folder) / "OniThermalLcd" / "settings.json").save(settings)
            window = self.window(folder); self.pump(); session = window.left.session
            self.assertGreaterEqual(window.left.monitor_template.findText("Desk Stats"), 0); window.start_monitor_layout("0416:5408", window._monitor_layout_by_name("0416:5408", "Desk Stats"))
            self.assertIs(window.left.session, session); self.assertEqual(window.monitor_layouts_active["0416:5408"][0].name, "Desk Stats")

    def test_sensor_media_overlay_restores_without_losing_media(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "restore.png"; Image.new("RGB", (80, 40), "purple").save(media)
            layout = MonitorLayout("Overlay", "0416:5408", 1920, 462, elements=[MonitorElement("label + value", 20, 20, sensor_id="cpu.usage")])
            settings = AppSettings(); settings.output_modes["0416:5408"] = OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value; settings.monitor_layouts = {"Default": {"0416:5408": layout.to_dict()}}
            settings.profiles["Default"]["0416:5408"] = DisplayProfile(str(media), desired_playback_state="Playing", output_mode=OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value)
            SettingsStore(Path(folder) / "OniThermalLcd" / "settings.json").save(settings)
            window = self.window(folder); self.pump()
            self.assertEqual(window.left.path, media); self.assertIn("0416:5408", window.monitor_layouts_active)
            self.assertEqual(window.left.output_ownership.lease().mode, OutputMode.MEDIA_WITH_SENSOR_OVERLAY)


if __name__ == "__main__":
    unittest.main()
