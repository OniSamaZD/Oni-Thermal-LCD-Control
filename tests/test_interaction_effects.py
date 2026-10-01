import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton

    from thermalright_lcd.device_connection import DisabledHardwareSender
    from thermalright_lcd.gui import MainWindow, STYLE
    from thermalright_lcd.interaction_effects import interaction_stylesheet
    from thermalright_lcd.settings import AppSettings, SettingsStore

    HAS_QT = True
except ImportError:
    HAS_QT = False


class EffectsSettingsTests(unittest.TestCase):
    def test_fresh_and_older_settings_default_effects_on(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertTrue(SettingsStore(path).load().effects_enabled)
            path.write_text('{"performance_mode":"Normal"}', encoding="utf-8")
            self.assertTrue(SettingsStore(path).load().effects_enabled)

    def test_effects_setting_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder) / "settings.json")
            store.save(AppSettings(effects_enabled=False))
            self.assertFalse(store.load().effects_enabled)

    def test_both_policies_keep_accessible_state_feedback(self):
        for enabled in (True, False):
            qss = interaction_stylesheet(enabled)
            self.assertIn("QPushButton:focus", qss)
            self.assertIn("QPushButton:pressed", qss)
            self.assertIn("QPushButton:disabled", qss)
            self.assertIn("QCheckBox:checked", qss)
            self.assertIn("QAbstractItemView::item:selected", qss)


@unittest.skipUnless(HAS_QT, "PySide6 unavailable")
class EffectsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([]); cls.previous_stylesheet = cls.app.styleSheet(); cls.previous_effects = cls.app.property("oniEffectsEnabled"); cls.app.setStyleSheet(STYLE); cls.app.setProperty("oniEffectsEnabled", None)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.previous_stylesheet); cls.app.setProperty("oniEffectsEnabled", cls.previous_effects)

    def _window(self, folder):
        environment = patch.dict(os.environ, {"LOCALAPPDATA": folder})
        sender = patch("thermalright_lcd.gui.build_gui_sender", side_effect=lambda _: DisabledHardwareSender())
        environment.start(); sender.start()
        self.addCleanup(environment.stop); self.addCleanup(sender.stop)
        window = MainWindow(); self.addCleanup(window.shutdown)
        return window

    def test_immediate_toggle_persists_without_timers_or_geometry_change(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder); window.show(); self.app.processEvents()
            geometry = window.geometry(); timers = len(window.findChildren(QTimer))
            window.settings_page.effects.setCurrentIndex(1); self.app.processEvents()
            self.assertFalse(window.settings.effects_enabled)
            self.assertFalse(self.app.property("oniEffectsEnabled"))
            self.assertFalse(SettingsStore(window.store.path).load().effects_enabled)
            self.assertEqual(window.geometry(), geometry)
            self.assertEqual(len(window.findChildren(QTimer)), timers)
            window.settings_page.effects.setCurrentIndex(0); self.app.processEvents()
            self.assertTrue(window.settings.effects_enabled)
            self.assertTrue(self.app.property("oniEffectsEnabled"))
            self.assertEqual(len(window.findChildren(QTimer)), timers)

    def test_repeated_toggle_does_not_duplicate_business_callbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder); button = QPushButton("Action", window); calls = []
            button.clicked.connect(lambda: calls.append(True))
            timers = len(window.findChildren(QTimer))
            for _ in range(3):
                window.set_effects_enabled(False); window.set_effects_enabled(True)
            button.click()
            self.assertEqual(calls, [True])
            self.assertEqual(len(window.findChildren(QTimer)), timers)
            self.assertTrue(self.app.styleSheet().startswith(STYLE))

    def test_keyboard_focus_remains_visible_with_effects_off(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder); window.show(); window.select_page(6, open_dialog=False); window.set_effects_enabled(False); self.app.processEvents()
            first = window.settings_page.effects; second = window.settings_page.close_behavior
            first.setFocus(); self.app.processEvents(); self.assertTrue(first.hasFocus())
            QTest.keyClick(first, Qt.Key_Tab); self.app.processEvents()
            self.assertTrue(second.hasFocus() or window.focusWidget() is not None)
            QTest.keyClick(window.focusWidget(), Qt.Key_Backtab); self.app.processEvents(); self.assertIsNotNone(window.focusWidget())
            button = QPushButton("Keyboard action", window.settings_page); calls = []; button.clicked.connect(lambda: calls.append(True)); button.show(); button.setFocus(); self.app.processEvents()
            QTest.keyClick(button, Qt.Key_Space); self.assertEqual(calls, [True])
            self.assertIn("QComboBox:focus", self.app.styleSheet())
