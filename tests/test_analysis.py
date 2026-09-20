import tempfile
import unittest
from pathlib import Path

from thermalright_lcd.analyzer import find_jpegs, jpeg_dimensions


class AnalysisTests(unittest.TestCase):
    def test_find_jpegs_respects_boundaries(self):
        stream = b"head\xff\xd8abc\xff\xd9tail\xff\xd8x\xff\xd9"
        self.assertEqual(find_jpegs(stream), [(4, 11), (15, 20)])

    def test_no_incomplete_jpeg(self):
        self.assertEqual(find_jpegs(b"\xff\xd8unfinished"), [])

    def test_dimensions_baseline_jpeg(self):
        jpeg = b"\xff\xd8\xff\xc0\x00\x11\x08\x01\xe0\x03\x20" + b"\x00" * 10 + b"\xff\xd9"
        self.assertEqual(jpeg_dimensions(jpeg), (800, 480))


if __name__ == "__main__":
    unittest.main()
