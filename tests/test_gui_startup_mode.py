import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "src" / "thermalright_lcd" / "gui.py"


class GuiStartupModeTests(unittest.TestCase):
    def test_manual_launch_is_not_hidden_by_saved_startup_preference(self):
        source = GUI.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertNotIn("if self.settings.start_minimized:QTimer.singleShot(0,self.hide)", source)
        self.assertIn('"--start-minimized" in sys.argv', source)
        self.assertIn('"--start-to-tray" in sys.argv', source)

    def test_smoke_hold_is_bounded_and_clean(self):
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("ONI_LCD_GUI_SMOKE_HOLD_MS", source)
        self.assertIn("QTimer.singleShot(hold_ms,w.exit_application)", source)
