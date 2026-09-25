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
from thermalright_lcd.sensor_theme_store import SensorThemeStore
from thermalright_lcd.settings import AppSettings, DisplayProfile, SettingsStore

ROOT = Path(__file__).resolve().parents[1]


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

    def test_animation_uses_bounded_runtime_fps_without_per_widget_timer(self):
        animated = make_theme(static=True); animated.elements[0].animation = "pulse"; animated.elements[0].animation_duration = 1
        runtime = SensorThemeOutputRuntime(clock=lambda: 0); state = runtime.apply("0416:5408", animated, fps=2)
        first = runtime.render_due("0416:5408", {}, monotonic_now=0, wall_time=datetime(2026, 1, 1, 0, 0, 0)); first.close()
        self.assertIsNone(runtime.render_due("0416:5408", {}, monotonic_now=.25, wall_time=datetime(2026, 1, 1, 0, 0, 0, 250000)))
        second = runtime.render_due("0416:5408", {}, monotonic_now=.5, wall_time=datetime(2026, 1, 1, 0, 0, 0, 500000)); second.close()
        self.assertEqual((state.render_count, state.skipped_count), (2, 1))


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
            self.assertIs(page.parent(), window.sensor_theme_workspace.stack); self.assertIs(window.sensor_theme_workspace.parent(), window.pages); self.assertFalse(page.isWindow())
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

    def test_sensor_media_publishes_precomposed_overlay_in_one_mode_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); media = Path(folder) / "atomic.png"; Image.new("RGB", (64, 32), "navy").save(media)
            card = window.left; card.load(media)
            layout = MonitorLayout("Atomic", card.device_id, 1920, 462, elements=[MonitorElement("label + value", 10, 10, sensor_id="cpu.usage")])
            original = window.set_output_mode; transitions = []
            def transition(device_id, mode, stop_previous=True):
                transitions.append((OutputMode(mode), card._sensor_overlay is not None))
                return original(device_id, mode, stop_previous)
            with patch.object(window, "set_output_mode", side_effect=transition):
                self.assertTrue(window.start_monitor_overlay(card.device_id, layout))
            self.assertEqual(transitions, [(OutputMode.MEDIA_WITH_SENSOR_OVERLAY, True)])
            self.assertEqual(card.output_ownership.lease().mode, OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
            self.assertEqual(card.path, media)

    def test_sensor_media_is_a_visible_first_class_independent_output_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); media = Path(folder) / "still.png"; Image.new("RGB", (64, 32), "navy").save(media)
            window.left.load(media); window.right.load(media)
            for card in (window.left, window.right):
                self.assertIn(OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value, card.output_segments)
                self.assertGreaterEqual(card.output_selector.findData(OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value), 0)
                layout = MonitorLayout("User Overlay", card.device_id, *card.size_target, elements=[MonitorElement("label + value", 10, 10, sensor_id="cpu.usage")])
                window.settings.monitor_layout_library.setdefault(card.device_id, {})[layout.name] = layout.to_dict()
                window._refresh_monitor_template_options(card); card.monitor_template.setCurrentText(layout.name)
            left_session, right_session = window.left.session, window.right.session
            window.left.set_output_mode_val(OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value); self.pump()
            self.assertEqual(window.left.output_ownership.lease().mode, OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
            self.assertEqual(window.right.output_ownership.lease().mode, OutputMode.STOPPED)
            self.assertIs(window.left.session, left_session); self.assertIs(window.right.session, right_session)
            window.left.set_output_mode_val(OutputMode.MEDIA.value); self.pump()
            self.assertEqual(window.left.path, media); self.assertEqual(window.left.output_ownership.lease().mode, OutputMode.MEDIA)

    def test_output_controls_are_readable_and_two_display_transition_matrix_preserves_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); media = Path(folder) / "matrix.png"; Image.new("RGB", (64, 32), "navy").save(media)
            sessions = tuple(card.session for card in window.cards)
            for card in window.cards:
                card.load(media)
                self.assertEqual([card.output_segments[key].text() for key in (OutputMode.MEDIA.value, OutputMode.HARDWARE_MONITOR.value, OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value, OutputMode.STOPPED.value)], ["Media", "Sensor Theme", "Sensor + Media", "OFF"])
                for button in card.output_segments.values():
                    self.assertGreaterEqual(button.minimumWidth(), button.sizeHint().width())
            for _cycle in range(6):
                for card in window.cards:
                    window.apply_sensor_theme(make_theme(f"matrix-{_cycle}"), None, (card.device_id,), 1)
                    window.set_output_mode(card.device_id, OutputMode.MEDIA)
                    layout = MonitorLayout("Matrix", card.device_id, *card.pipeline.TARGETS[card.device_id], elements=[MonitorElement("label + value", 10, 10, sensor_id="cpu.usage")])
                    self.assertTrue(window.start_monitor_overlay(card.device_id, layout))
                    window.set_output_mode(card.device_id, OutputMode.MEDIA)
            self.assertEqual(tuple(card.session for card in window.cards), sessions)

    def test_sensor_to_photo_video_gif_replaces_preview_without_transform_input(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV unavailable")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); photo=root/"photo.png"; gif=root/"clip.gif"; video=root/"clip.avi"
            Image.new("RGB",(32,16),"red").save(photo)
            frames=[Image.new("RGB",(32,16),color) for color in ("green","blue")];frames[0].save(gif,save_all=True,append_images=frames[1:],duration=80,loop=0)
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*"MJPG"),5,(32,16))
            if not writer.isOpened():self.skipTest("MJPG writer unavailable")
            writer.write(np.full((16,32,3),(255,0,0),dtype=np.uint8));writer.release()
            window=self.window(folder);card=window.left;card.set_preview_enabled(True)
            for path in (photo,video,gif):
                self.assertTrue(card.load(path))
                window.apply_sensor_theme(make_theme("transition-theme"),None,(card.device_id,),1);theme_key=card.preview.pixmap().cacheKey()
                card.set_output_mode_val(OutputMode.MEDIA.value)
                self.assertNotEqual(card.preview.pixmap().cacheKey(),theme_key,path.name)
                self.assertEqual(card.path,path)
                card.stop(coordinated=True)

    def test_deleted_active_theme_stays_live_but_missing_restart_stops_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self.window(folder); window.apply_sensor_theme(make_theme("deleted-theme"), None, ("0416:5408",), 2); state = window.sensor_theme_runtime.state("0416:5408")
            window.sensor_theme_document_changed("deleted", None, None, "deleted-theme")
            self.assertIs(window.sensor_theme_runtime.state("0416:5408"), state)
            window.shutdown(); self.app.processEvents()
            restored = self.window(folder); self.pump()
            self.assertIsNone(getattr(restored, "sensor_theme_runtime", None)); self.assertEqual(restored.settings.output_modes["0416:5408"], OutputMode.STOPPED.value)
            self.assertIn("SENSOR THEME MISSING", restored.left.status.text())

    def test_saved_user_theme_restores_per_display(self):
        with tempfile.TemporaryDirectory() as folder:
            before = set(QApplication.topLevelWidgets())
            theme_store = SensorThemeStore(Path(folder) / "OniThermalLcd" / "sensor-themes", ROOT / "assets" / "sensor-themes"); theme_store.save(make_theme("restore-theme"))
            settings = AppSettings()
            for device_id, fps in (("0416:5408", 2), ("0416:5302", 5)):
                settings.output_modes[device_id] = OutputMode.HARDWARE_MONITOR.value; settings.sensor_theme_ids[device_id] = "restore-theme"; settings.sensor_theme_fps[device_id] = fps
                settings.profiles["Default"][device_id] = DisplayProfile(desired_playback_state="Playing", output_mode=OutputMode.HARDWARE_MONITOR.value)
            SettingsStore(Path(folder) / "OniThermalLcd" / "settings.json").save(settings)
            window = self.window(folder); self.pump()
            self.assertEqual((window.sensor_theme_runtime.state("0416:5408").theme.id, window.sensor_theme_runtime.state("0416:5408").fps), ("restore-theme", 2))
            self.assertEqual((window.sensor_theme_runtime.state("0416:5302").theme.id, window.sensor_theme_runtime.state("0416:5302").fps), ("restore-theme", 5))
            unexpected = [widget for widget in set(QApplication.topLevelWidgets()) - before if widget not in {window, window.tray_menu} and widget.parent() is None]
            self.assertFalse(unexpected, [(type(widget).__name__, widget.windowTitle()) for widget in unexpected])

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
