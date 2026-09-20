import logging,tempfile,unittest
from pathlib import Path
from thermalright_lcd.logging_setup import configure_logging

class LoggingTests(unittest.TestCase):
    def test_bounded_rotating_log(self):
        with tempfile.TemporaryDirectory() as d:
            root=logging.getLogger("thermalright_lcd");old=list(root.handlers);root.handlers.clear()
            try:
                path=configure_logging(Path(d));logging.getLogger("thermalright_lcd.test").info("safe event");root.handlers[0].flush()
                self.assertTrue(path.is_file());self.assertLessEqual(root.handlers[0].maxBytes,1_000_000);self.assertNotIn("payload",path.read_text())
            finally:
                for h in root.handlers:h.close()
                root.handlers[:]=old
