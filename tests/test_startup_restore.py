import json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.settings import AppSettings,DisplayProfile,SettingsStore


class StartupRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def pump(self,seconds=.08):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.app.processEvents();time.sleep(.005)
    def create_settings(self,folder,media,state="Playing",mode="media"):
        settings=AppSettings();settings.output_modes["0416:5408"]=mode;settings.profiles["Default"]["0416:5408"]=DisplayProfile(str(media),"Fill",90,"0.1",state=="Playing",4,-3,1.2,"Balanced",72,state);SettingsStore(Path(folder)/"OniThermalLcd"/"settings.json").save(settings)
    def test_static_media_and_playing_intent_restore_automatically(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            media=Path(d)/"still.png";Image.new("RGB",(32,16),"cyan").save(media);self.create_settings(d,media);window=MainWindow();self.pump()
            self.assertEqual(window.left.path,media);self.assertEqual(window.left.desired_playback_state,"Playing");self.assertTrue(window.left.playing);self.assertEqual(window.left.fps.currentText(),"Auto (Recommended)");self.assertEqual(window.left.output_rate(animated=False).fps,0.1);self.assertEqual(window.left.brightness_slider.value(),72);window.shutdown()
    def test_paused_intent_remains_paused(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            media=Path(d)/"still.png";Image.new("RGB",(32,16),"blue").save(media);self.create_settings(d,media,"Paused");window=MainWindow();self.pump();self.assertFalse(window.left.playing);self.assertEqual(window.left.desired_playback_state,"Paused");self.assertEqual(window.left.status.text(),"PAUSED");window.shutdown()
    def test_missing_media_warns_without_breaking_other_card(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            self.create_settings(d,Path(d)/"missing.png");window=MainWindow();self.pump();self.assertIsNone(window.left.path);self.assertIn("MEDIA MISSING",window.left.status.text());self.assertIsNotNone(window.right.session);window.shutdown()
    def test_preview_preferences_round_trip(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            window=MainWindow();window.left.preview_scale_slider.setValue(150);window.right.preview_scale_slider.setValue(75);window.left.advanced_toggle.setChecked(True);window.shutdown();restored=MainWindow();self.assertEqual((restored.left.preview_scale,restored.right.preview_scale),(150,75));self.assertTrue(restored.left.advanced_toggle.isChecked());restored.shutdown()
    def test_delayed_device_reconnect_resumes_saved_playing_intent(self):
        class Enabled:
            enabled=True
            def __init__(self):self.frames=[];self.frame_metrics=[]
            def __call__(self,frame):self.frames.append(frame);self.frame_metrics.append({"ack_ms":0});return frame.total_bytes
            def close(self):pass
        calls=[]
        def sender(_):
            calls.append(1);return DisabledHardwareSender() if len(calls)<=2 else Enabled()
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=sender):
            media=Path(d)/"still.png";Image.new("RGB",(32,16),"green").save(media);self.create_settings(d,media);window=MainWindow();self.pump();self.assertFalse(window.left.hardware_sender.enabled);window._resume_waiting_devices();self.pump(.2);session=window.left.session;window._resume_waiting_devices();self.assertIs(window.left.session,session);self.assertTrue(window.left.hardware_sender.enabled);self.assertGreaterEqual(window.left.session.metrics.sent,1);self.assertEqual(window.left.desired_playback_state,"Playing");window.shutdown()


if __name__=="__main__":unittest.main()
