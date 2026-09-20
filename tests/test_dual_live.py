import unittest
from pathlib import Path
from thermalright_lcd.dual_live import run_dual_persistence
from thermalright_lcd.live_state import DryRunUsbTransport,expected_identity,load_sequence
from thermalright_lcd.persistence import POLICIES
from thermalright_lcd.replay import load_allowlist

ROOT=Path(__file__).resolve().parents[1]

class DualPersistenceTests(unittest.TestCase):
    def test_independent_dual_workers_overlap_and_never_open_hardware(self):
        targets={x["vid_pid"]:x for x in load_allowlist(ROOT/"config/device-allowlist.json")["devices"]};specs={}
        files={"0416:5302":ROOT/"analysis/pid5302-same-session-first-frame.json","0416:5408":ROOT/"analysis/pid5408-new-session-first-frame.json"}
        for pid in files:
            seq=load_sequence(ROOT/"analysis/session-report.json",files[pid],pid,require_same_session=True);responses=[seq["ready"]]+([seq["ack"]]*2 if seq["ack"] else [])
            specs[pid]={"target":targets[pid],"sequence":seq,"transport":DryRunUsbTransport(expected_identity(targets[pid]),responses),"plan":{"frame_count_hard_max":2},"policy":POLICIES[pid]}
        result=run_dual_persistence(specs,.05);self.assertTrue(result["success"]);self.assertTrue(result["combined"]["both_started"]);self.assertGreater(result["combined"]["simultaneous_active_seconds"],0)
        self.assertTrue(result["combined"]["all_handles_closed"]);self.assertTrue(all(not x["usb_hardware_written"] for x in result["devices"].values()))
    def test_generated_sequences_run_independently_with_device_specific_ack(self):
        targets={x["vid_pid"]:x for x in load_allowlist(ROOT/"config/device-allowlist.json")["devices"]};specs={}
        files={"0416:5302":ROOT/"analysis/pid5302-dual-generated-test.json","0416:5408":ROOT/"analysis/pid5408-dual-generated-test.json"}
        for pid in files:
            seq=load_sequence(ROOT/"analysis/session-report.json",files[pid],pid,require_same_session=True);responses=[seq["ready"]]+([seq["ack"]]*2 if seq["ack"] else [])
            specs[pid]={"target":targets[pid],"sequence":seq,"transport":DryRunUsbTransport(expected_identity(targets[pid]),responses),"plan":{"frame_count_hard_max":2},"policy":POLICIES[pid]}
        result=run_dual_persistence(specs,.4);self.assertTrue(result["success"])
        self.assertEqual(result["devices"]["0416:5408"]["ack_count"],2);self.assertEqual(result["devices"]["0416:5302"]["ack_count"],0)
        self.assertTrue(result["combined"]["all_handles_closed"]);self.assertEqual(result["combined"]["automatic_retries"],0)
