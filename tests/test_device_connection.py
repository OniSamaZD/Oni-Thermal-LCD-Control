import unittest
import sys
from unittest.mock import patch
from pathlib import Path

from thermalright_lcd.device_connection import GeneratedFrameConnection, build_gui_sender, application_root
from thermalright_lcd.encoder import encode_5302, encode_5408
from thermalright_lcd.live_state import DryRunUsbTransport, SafetyError, expected_identity, load_sequence
from thermalright_lcd.replay import load_allowlist


ROOT=Path(__file__).resolve().parents[1]
SESSION=ROOT/"analysis/session-report.json"
FILES={"0416:5408":ROOT/"analysis/pid5408-new-session-first-frame.json",
       "0416:5302":ROOT/"analysis/pid5302-same-session-first-frame.json"}
JPEGS={"0416:5408":ROOT/"captures/generated/test-media/dual-generated-pid5408.jpg",
       "0416:5302":ROOT/"captures/generated/test-media/dual-generated-pid5302.jpg"}


class GeneratedConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.targets={x["vid_pid"]:x for x in load_allowlist(ROOT/"config/device-allowlist.json")["devices"]}

    def encoded(self,pid):
        data=JPEGS[pid].read_bytes();return encode_5408(data) if pid.endswith("5408") else encode_5302(data)

    def test_frozen_application_root_uses_meipass(self):
        with patch.object(sys,"frozen",True,create=True),patch.object(sys,"_MEIPASS",str(ROOT),create=True):
            self.assertEqual(application_root(),ROOT)

    def test_independent_generated_lifecycles_and_ack_policy(self):
        for pid in FILES:
            target=self.targets[pid];seq=load_sequence(SESSION,FILES[pid],pid,require_same_session=True)
            responses=[seq["ready"]]+([seq["ack"]] if seq["ack"] else [])
            tr=DryRunUsbTransport(expected_identity(target),responses)
            sender=GeneratedFrameConnection(target,seq,tr,conflict_supplier=lambda:[]);frame=self.encoded(pid)
            self.assertEqual(sender(frame),frame.total_bytes);self.assertEqual(sender.frames,1)
            self.assertEqual(sender.acks,1 if pid.endswith("5408") else 0)
            sender.close();self.assertTrue(tr.closed)

    def test_opt_in_connection_trace_records_open_ready_frame_ack_and_close(self):
        pid="0416:5408";target=self.targets[pid];seq=load_sequence(SESSION,FILES[pid],pid,require_same_session=True)
        tr=DryRunUsbTransport(expected_identity(target),[seq["ready"],seq["ack"]]);events=[]
        sender=GeneratedFrameConnection(target,seq,tr,conflict_supplier=lambda:[],trace_hook=lambda event,**fields:events.append((event,fields)))
        sender(self.encoded(pid));sender.close();names=[event for event,_ in events]
        self.assertIn("device_discovered",names);self.assertIn("readiness_validated",names)
        self.assertIn("frame_ack_validated",names);self.assertIn("frame_write_complete",names);self.assertIn("device_close_complete",names)

    def test_wrong_device_frame_fails_before_open(self):
        target=self.targets["0416:5408"];seq=load_sequence(SESSION,FILES["0416:5408"],"0416:5408",require_same_session=True)
        tr=DryRunUsbTransport(expected_identity(target),[seq["ready"]]);sender=GeneratedFrameConnection(target,seq,tr,conflict_supplier=lambda:[])
        with self.assertRaises(SafetyError):sender(self.encoded("0416:5302"))
        self.assertFalse(tr.opened)

    def test_gui_generated_media_gate_is_enabled_without_opening_device(self):
        for pid in FILES:
            sender=build_gui_sender(pid,ROOT);self.assertTrue(sender.enabled);self.assertFalse(sender._opened)
    def test_send_failure_closes_handle_without_retry(self):
        pid="0416:5408";target=self.targets[pid];seq=load_sequence(SESSION,FILES[pid],pid,require_same_session=True)
        tr=DryRunUsbTransport(expected_identity(target),[seq["ready"]],{"disconnect":1})
        sender=GeneratedFrameConnection(target,seq,tr,conflict_supplier=lambda:[])
        with self.assertRaises(Exception):sender(self.encoded(pid))
        self.assertTrue(tr.closed);self.assertFalse(tr.opened);self.assertEqual(len(tr.writes),1)
