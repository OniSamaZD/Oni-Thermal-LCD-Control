import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.settings import AppSettings, SettingsStore
from thermalright_lcd.single_instance import SingleInstance


class TrayExitInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,{"LOCALAPPDATA":temp.name});env.start();self.addCleanup(env.stop)
        sender=patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _id:DisabledHardwareSender());sender.start();self.addCleanup(sender.stop)
        window=MainWindow();self.addCleanup(lambda:window.shutdown());return window

    def test_close_defaults_to_same_hidden_window_and_one_tray(self):
        window=self.make_window();window.show();self.app.processEvents();tray=window.tray
        timer_ids=tuple(id(x) for x in window.findChildren(QTimer))
        for _ in range(8):
            window.close();self.app.processEvents();self.assertFalse(window.isVisible());self.assertFalse(window.left.timer.isActive());self.assertTrue(window.tray.isVisible())
            window.restore_window();self.app.processEvents();self.assertTrue(window.isVisible());self.assertIs(window.tray,tray)
        self.assertEqual(timer_ids,tuple(id(x) for x in window.findChildren(QTimer)))

    def test_exit_behavior_and_explicit_exit_cleanup(self):
        window=self.make_window();window.settings.close_button_behavior="exit_application";window.show();window.close();self.app.processEvents()
        self.assertTrue(window._shutdown_done);self.assertFalse(window.tray.isVisible())
        for card in (window.left,window.right):
            self.assertFalse(card.timer.isActive());self.assertIsNone(card.scheduler);self.assertIsNone(card.session._thread);self.assertEqual(len(card.session.queue),0);self.assertEqual(card.pipeline.cache_entries,0);self.assertEqual(card.bridge.pending,0)

    def test_diagnostics_are_on_demand_and_bounded(self):
        window=self.make_window();data=window.runtime_diagnostics()
        self.assertEqual(data["pid"],os.getpid());self.assertEqual(data["decoded_queue_sizes"],[0,0]);self.assertEqual(data["transport_queue_sizes"],[0,0]);self.assertEqual(data["active_playback_workers"],0);self.assertEqual(data["active_display_sessions"],0);self.assertEqual(data["retained_full_resolution_frames"],0)

    def test_close_setting_default_and_legacy_migration(self):
        self.assertEqual(AppSettings().close_button_behavior,"minimize_to_tray")
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"settings.json";path.write_text(json.dumps({"close_to_tray":False}),encoding="utf-8")
            loaded=SettingsStore(path).load();self.assertEqual(loaded.close_button_behavior,"minimize_to_tray");self.assertTrue(loaded.close_to_tray)

    def test_second_instance_notifies_primary(self):
        name=f"oni-test-{uuid.uuid4()}";first=SingleInstance(name);second=SingleInstance(name);activated=[];first.activationRequested.connect(lambda:activated.append(True))
        self.assertTrue(first.acquire_or_notify());self.assertFalse(second.acquire_or_notify())
        limit=time.monotonic()+1
        while not activated and time.monotonic()<limit:self.app.processEvents();time.sleep(.01)
        self.assertEqual(activated,[True]);first.close();second.close()


if __name__ == "__main__":unittest.main()
