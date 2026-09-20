import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.gui import DisplayCard,MainWindow,MEDIA,media_dialog_start_directory
from thermalright_lcd.media_types import MediaKind,media_filter
from thermalright_lcd.settings import AppSettings,SettingsStore


class MediaChooserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def card(self,provider=lambda:"",selected=None):
        return DisplayCard("test",(1280,480),"0416:5302",hardware_sender=DisabledHardwareSender(),media_directory_provider=provider,media_directory_selected=selected)

    def test_first_use_prefers_downloads_and_never_process_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            downloads=Path(d)/"Downloads";downloads.mkdir()
            with patch.object(QStandardPaths,"writableLocation",side_effect=lambda loc:str(downloads) if loc==QStandardPaths.DownloadLocation else ""):
                with patch("thermalright_lcd.gui.Path.cwd",return_value=Path("C:/Windows/System32")):
                    self.assertEqual(media_dialog_start_directory(),str(downloads))

    def test_valid_last_directory_is_respected(self):
        with tempfile.TemporaryDirectory() as d:self.assertEqual(media_dialog_start_directory(d),d)

    def test_missing_or_disconnected_directory_uses_known_folder(self):
        with tempfile.TemporaryDirectory() as d:
            fallback=Path(d)/"Pictures";fallback.mkdir()
            with patch.object(QStandardPaths,"writableLocation",side_effect=lambda loc:str(fallback) if loc==QStandardPaths.PicturesLocation else ""):
                self.assertEqual(media_dialog_start_directory("Z:/unplugged/media"),str(fallback))

    def test_system_directory_is_rejected_and_managed_fallback_is_created(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"SystemRoot":"C:/Windows"}):
            managed=Path(d)/"OniThermalLcd"/"media"
            with patch.object(QStandardPaths,"writableLocation",return_value="C:/Windows/System32"):
                self.assertEqual(media_dialog_start_directory("C:/Windows/System32",managed),str(managed));self.assertTrue(managed.is_dir())

    def test_cancel_does_not_update_directory(self):
        updates=[];card=self.card(lambda:"D:/Media",updates.append)
        with patch("thermalright_lcd.gui.QFileDialog.getOpenFileName",return_value=("","")) as dialog:card.choose()
        self.assertEqual(updates,[]);self.assertEqual(dialog.call_args.args[2],"D:/Media");card.shutdown()

    def test_successful_selection_updates_parent_and_preserves_filter(self):
        with tempfile.TemporaryDirectory() as d:
            selected=Path(d)/"wallpaper.png";selected.write_bytes(b"not decoded by mocked load");updates=[];card=self.card(lambda:d,updates.append)
            with patch.object(card,"load",return_value=True),patch("thermalright_lcd.gui.QFileDialog.getOpenFileName",return_value=(str(selected),MEDIA)) as dialog:card.choose()
            self.assertEqual(updates,[selected.parent]);self.assertEqual(dialog.call_args.args[3],media_filter(MediaKind.PHOTO));card.shutdown()

    def test_failed_load_does_not_update_directory(self):
        updates=[];card=self.card(lambda:"",updates.append)
        with patch.object(card,"load",return_value=False),patch("thermalright_lcd.gui.QFileDialog.getOpenFileName",return_value=("C:/bad.exe","")):card.choose()
        self.assertEqual(updates,[]);card.shutdown()

    def test_settings_reload_preserves_global_directory(self):
        with tempfile.TemporaryDirectory() as d:
            media=Path(d)/"media";media.mkdir();store=SettingsStore(Path(d)/"settings.json");settings=AppSettings(last_media_directory=str(media));store.save(settings)
            self.assertEqual(store.load().last_media_directory,str(media))

    def test_both_cards_share_one_persisted_directory(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            chosen=Path(d)/"Wallpapers";chosen.mkdir();window=MainWindow();self.assertTrue(window._remember_media_directory(chosen))
            self.assertEqual(window.left.media_directory_provider(),str(chosen));self.assertEqual(window.right.media_directory_provider(),str(chosen));window.shutdown()
            self.assertEqual(SettingsStore(Path(d)/"OniThermalLcd"/"settings.json").load().last_media_directory,str(chosen))

    def test_supported_filter_extensions_are_unchanged(self):
        for extension in ("*.jpg","*.jpeg","*.png","*.webp","*.gif","*.mp4","*.webm","*.mkv","*.mov","*.avi","*.m4v"):
            self.assertIn(extension,MEDIA)


if __name__=="__main__":unittest.main()
