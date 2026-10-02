import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from thermalright_lcd.settings import AppSettings, SettingsStore
from thermalright_lcd.themes import (
    DEFAULT_THEME, REQUIRED_TOKEN_NAMES, THEMES, THEME_NAMES,
    compile_theme_stylesheet, normalize_theme_name, sensor_studio_stylesheet,
    theme_tokens, validate_theme,
)


class ThemeContractTests(unittest.TestCase):
    def test_exact_six_themes_and_complete_semantic_contract(self):
        self.assertEqual(THEME_NAMES, ("ONI Blue", "Crimson", "Cyberpunk", "Neon Purple", "Emerald", "Monochrome"))
        self.assertEqual(len(THEMES), 6)
        for name in THEME_NAMES:
            theme = theme_tokens(name); self.assertTrue(validate_theme(theme)); self.assertEqual(theme.name, name)
            self.assertTrue(all(getattr(theme, token) for token in REQUIRED_TOKEN_NAMES))

    def test_invalid_theme_falls_back_and_blue_preserves_baseline(self):
        baseline = "QWidget { background:#050611; color:#f2f1ff; border:1px solid #6847ee; }"
        self.assertEqual(normalize_theme_name("broken"), DEFAULT_THEME)
        self.assertEqual(compile_theme_stylesheet(baseline, "broken"), baseline)
        self.assertEqual(compile_theme_stylesheet(baseline, "ONI Blue"), baseline)

    def test_palettes_recolor_accent_but_keep_status_roles_distinct(self):
        baseline = "QWidget{color:#6847ee} QLabel{color:#20df7a} QFrame{color:#ff5d6c}"
        for name in THEME_NAMES[1:]:
            result = compile_theme_stylesheet(baseline, name); tokens = theme_tokens(name)
            self.assertNotIn("#6847ee", result.lower()); self.assertIn(tokens.success, result); self.assertIn(tokens.error, result)
            self.assertNotEqual(tokens.accent, tokens.success); self.assertNotEqual(tokens.accent, tokens.error)
            self.assertNotEqual(sensor_studio_stylesheet(name), sensor_studio_stylesheet(DEFAULT_THEME))

    def test_theme_setting_default_migration_validation_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"; store = SettingsStore(path)
            self.assertEqual(store.load().theme_name, DEFAULT_THEME)
            path.write_text('{"theme_name":"not-a-theme"}', encoding="utf-8"); self.assertEqual(store.load().theme_name, DEFAULT_THEME)
            value = AppSettings(theme_name="Emerald"); store.save(value); self.assertEqual(store.load().theme_name, "Emerald")


try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from thermalright_lcd.device_connection import DisabledHardwareSender
    from thermalright_lcd.gui import MainWindow, STYLE
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 unavailable")
class ThemeRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.old_style = cls.app.styleSheet(); cls.old_theme = cls.app.property("oniThemeName"); cls.old_effects = cls.app.property("oniEffectsEnabled"); cls.app.setStyleSheet(STYLE); cls.app.setProperty("oniThemeName", None); cls.app.setProperty("oniEffectsEnabled", None)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.old_style); cls.app.setProperty("oniThemeName", cls.old_theme); cls.app.setProperty("oniEffectsEnabled", cls.old_effects)

    def _window(self, folder, settings=None):
        if settings is not None: SettingsStore(Path(folder) / "OniThermalLcd" / "settings.json").save(settings)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": folder}); sender = patch("thermalright_lcd.gui.build_gui_sender", side_effect=lambda _: DisabledHardwareSender())
        environment.start(); sender.start(); self.addCleanup(environment.stop); self.addCleanup(sender.stop)
        window = MainWindow()
        def cleanup(): window.shutdown()
        self.addCleanup(cleanup); return window

    def test_startup_restore_runtime_switching_and_settings_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder, AppSettings(theme_name="Crimson")); window.show(); self.app.processEvents()
            self.assertEqual(window.settings.theme_name, "Crimson"); self.assertEqual(self.app.property("oniThemeName"), "Crimson"); self.assertEqual(window.settings_page.theme.currentText(), "Crimson")
            window.settings_page.theme.setCurrentText("Emerald"); self.app.processEvents()
            self.assertEqual(window.settings.theme_name, "Emerald"); self.assertEqual(SettingsStore(window.store.path).load().theme_name, "Emerald")
            window.shutdown(); restored = self._window(folder); restored.show(); self.app.processEvents()
            self.assertEqual(restored.settings.theme_name, "Emerald"); self.assertEqual(self.app.property("oniThemeName"), "Emerald"); self.assertEqual(restored.settings_page.theme.currentText(), "Emerald")

    def test_every_runtime_theme_replaces_blue_control_accent(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder); window.show(); self.app.processEvents()
            for name in THEME_NAMES[1:]:
                window.set_theme(name); self.app.processEvents(); stylesheet = self.app.styleSheet().lower()
                self.assertEqual(self.app.property("oniThemeName"), name)
                self.assertNotIn("#6847ee", stylesheet); self.assertIn(theme_tokens(name).accent_hover, stylesheet)

    def test_repeated_switching_with_effects_does_not_change_runtime_ownership_or_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder); window.show(); self.app.processEvents(); geometry = window.geometry(); timers = len(window.findChildren(QTimer)); sessions = tuple(card.session for card in window.cards); widgets = len(window.findChildren(QWidget))
            for enabled in (True, False):
                window.set_effects_enabled(enabled)
                for _ in range(3):
                    for name in THEME_NAMES: window.set_theme(name)
            self.app.processEvents()
            self.assertEqual(window.geometry(), geometry); self.assertEqual(len(window.findChildren(QTimer)), timers); self.assertEqual(tuple(card.session for card in window.cards), sessions); self.assertEqual(len(window.findChildren(QWidget)), widgets)
            self.assertEqual(self.app.property("oniThemeName"), "Monochrome"); self.assertFalse(self.app.property("oniEffectsEnabled"))

    def test_switching_theme_does_not_mutate_media_or_output_state(self):
        with tempfile.TemporaryDirectory() as folder:
            window = self._window(folder); states = [(card.path, card.size_target, card.session, card.output_ownership.lease().mode) for card in window.cards]
            for name in THEME_NAMES: window.set_theme(name)
            self.assertEqual([(card.path, card.size_target, card.session, card.output_ownership.lease().mode) for card in window.cards], states)
