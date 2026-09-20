import unittest
from pathlib import Path
from thermalright_lcd.encoder import encode_5302,encode_5408,validate_5302,validate_5408
from thermalright_lcd.jpeg_compat import compatibility_report

ROOT=Path(__file__).resolve().parents[1]

class JpegCompatibilityTests(unittest.TestCase):
    def test_5408_candidate_is_standard_baseline_and_framing_is_corrected(self):
        known=ROOT/"analysis/display_9_16/new-session-first-frame.jpg";candidate=ROOT/"captures/generated/test-media/generated_9_16.jpg"
        report=compatibility_report(known,candidate);c=report["comparison"]
        self.assertTrue(c["same_dimensions"] and c["same_baseline_mode"] and c["same_subsampling"] and c["same_huffman_tables"] and c["both_strict_decode"])
        self.assertTrue(validate_5408(encode_5408(candidate.read_bytes()))["valid"])
    def test_5302_candidate_matches_working_jpeg_structure_and_protocol(self):
        known=ROOT/"analysis/live-5302-hid-transmitted-frame.jpg";candidate=ROOT/"captures/generated/test-media/generated_6.jpg"
        report=compatibility_report(known,candidate);c=report["comparison"]
        self.assertTrue(c["same_dimensions"] and c["same_baseline_mode"] and c["same_subsampling"] and c["same_huffman_tables"])
        self.assertTrue(validate_5302(encode_5302(candidate.read_bytes()))["valid"])
