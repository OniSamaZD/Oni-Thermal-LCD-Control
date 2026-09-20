import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PerformanceTests(unittest.TestCase):
    def test_import_is_lazy(self):
        code = "import sys; import thermalright_lcd.performance; print(int(any(x in sys.modules for x in ('PySide6','PIL','cv2'))))"
        result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "0")

    def test_growth_calculation(self):
        from thermalright_lcd.performance import ProcessSample, _linear_growth_mb_per_minute
        rows = [ProcessSample(0, 10, 20, 30, 0, 1, 1), ProcessSample(30, 11, 22, 32, 0, 1, 1)]
        self.assertAlmostEqual(_linear_growth_mb_per_minute(rows, "working_set_mb"), 2)
        self.assertAlmostEqual(_linear_growth_mb_per_minute(rows, "private_bytes_mb"), 4)

    def test_offscreen_worker_never_writes_usb_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"profile.json"
            result = subprocess.run([
                sys.executable, "-m", "thermalright_lcd.performance", "--worker", "idle_disconnected",
                "--duration", ".25", "--interval", ".05", "--output", str(output)],
                text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(data["live_usb_permitted"])
            self.assertEqual(data["usb_writes"], 0)
            self.assertGreaterEqual(data["sample_count"], 2)
            self.assertEqual(data["max_queue_depth"], 0)
            self.assertEqual(data["short_leak_check"]["status"], "PASS_NO_OBVIOUS_GROWTH")
            # Native codec/runtime helper threads may retire during the sample;
            # cleanup must not leave additional threads, but a lower count is
            # not a leak or failure.
            self.assertLessEqual(data["post_cleanup_threads"], data["threads"]["start"])


if __name__ == "__main__": unittest.main()
