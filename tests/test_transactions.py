import json
import tempfile
import unittest
from pathlib import Path

from thermalright_lcd.replay import SafetyError, dry_run
from thermalright_lcd.transactions import isolate, write_transactions

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "captures/originals/deneme_lcd_9_166.pcapng"
ALLOWLIST = ROOT / "config/device-allowlist.json"


class TransactionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = isolate(CAPTURE)

    def test_5408_transactions_and_ack(self):
        dev = self.report["devices"]["0416:5408"]
        self.assertEqual(len(dev["transactions"]), 20)
        self.assertTrue(dev["response_summary"]["one_per_complete_frame"])
        self.assertTrue(self.report["analysis"]["0416:5408"]["chunk_index_rule_all"])
        self.assertTrue(self.report["analysis"]["0416:5408"]["declared_length_matches_all"])

    def test_5302_header_fields(self):
        dev = self.report["devices"]["0416:5302"]
        self.assertEqual(len(dev["transactions"]), 43)
        self.assertTrue(self.report["analysis"]["0416:5302"]["dimensions_all_1280x480"])
        self.assertEqual(self.report["analysis"]["0416:5302"]["jpeg_length_mismatches"], 2)

    def test_dry_run_and_wrong_device_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            tx = Path(d) / "transactions.json"
            write_transactions(CAPTURE, tx)
            result = dry_run(tx, ALLOWLIST, "0416:5408", 1)
            self.assertFalse(result["usb_opened"])
            self.assertFalse(result["usb_written"])
            self.assertEqual(result["frame_transfer_count"], 77)
            with self.assertRaises(SafetyError):
                dry_run(tx, ALLOWLIST, "0416:9999", 1)
