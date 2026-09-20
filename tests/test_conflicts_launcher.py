import unittest
from pathlib import Path
from unittest.mock import patch
from thermalright_lcd.conflicts import thermalright_processes

ROOT=Path(__file__).resolve().parents[1]

class ConflictAndLauncherTests(unittest.TestCase):
    @patch("thermalright_lcd.conflicts.subprocess.run")
    def test_trcc_conflict_detection(self,run):
        run.return_value.stdout='[{"ProcessName":"TRCC","Id":42,"Path":"C:/TRCC.exe"}]'
        self.assertEqual(thermalright_processes()[0]["ProcessName"],"TRCC")
    def test_launcher_pins_working_gui_runtime_and_safe_smoke_mode(self):
        text=(ROOT/"run-gui.bat").read_text(encoding="utf-8")
        self.assertIn("py -3.12",text);self.assertIn("ONI_LCD_GUI_SMOKE_TEST",text);self.assertNotIn("--send",text)
