import json
import tempfile
import unittest
from pathlib import Path

from thermalright_lcd.replay import SafetyError, dry_run_session
from thermalright_lcd.session import session_report

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "captures/generated/session_close_reopen_20260825.pcapng"
SESSION = ROOT / "analysis/session-report.json"
TRANSACTIONS = ROOT / "analysis/transactions.json"
ALLOWLIST = ROOT / "config/device-allowlist.json"


class SessionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = session_report(CAPTURE)

    def test_5408_open_ack_types_and_mapping(self):
        d = self.report["devices"]["0416:5408"]
        self.assertEqual((d["target"]["interface"], d["target"]["out"], d["target"]["in"]), (0, 0x09, 0x81))
        self.assertEqual(d["control_transfer_count"], 0)
        self.assertEqual(d["response_count"], d["frame_count"] + 1)
        self.assertEqual(d["unique_response_payloads"], 2)

    def test_5302_open_response_and_mapping(self):
        d = self.report["devices"]["0416:5302"]
        self.assertEqual((d["target"]["interface"], d["target"]["out"], d["target"]["in"]), (1, 0x02, 0x83))
        self.assertEqual(d["control_transfer_count"], 0)
        self.assertEqual(d["response_count"], 1)

    def test_full_dry_runs(self):
        for target in ("0416:5408", "0416:5302"):
            r = dry_run_session(SESSION, TRANSACTIONS, ALLOWLIST, target)
            self.assertFalse(r["usb_opened"])
            self.assertFalse(r["usb_written"])
            self.assertEqual(len(r["initialization_sequence"]), 1)
            self.assertEqual(r["termination_sequence"]["transfers"], [])

    def test_reject_wrong_interface_endpoint_and_malformed(self):
        allow = json.loads(ALLOWLIST.read_text())
        session = json.loads(SESSION.read_text())
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            for field, value in (("interface", 9), ("endpoint", "0x7f")):
                broken = json.loads(json.dumps(allow)); broken["devices"][0][field] = value
                p = td / f"{field}.json"; p.write_text(json.dumps(broken))
                with self.assertRaises(SafetyError):
                    dry_run_session(SESSION, TRANSACTIONS, p, "0416:5408")
            session["devices"]["0416:5408"]["events"] = []
            p = td / "session.json"; p.write_text(json.dumps(session))
            with self.assertRaises(SafetyError):
                dry_run_session(p, TRANSACTIONS, ALLOWLIST, "0416:5408")

