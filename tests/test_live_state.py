import json
import unittest
from dataclasses import replace
from pathlib import Path

from thermalright_lcd.live_state import (DryRunUsbTransport, LiveReplayMachine, State,
    PersistentReplayMachine,expected_identity, load_sequence, preflight, validate_ready)
from thermalright_lcd.replay import load_allowlist, SafetyError

ROOT=Path(__file__).resolve().parents[1]
ALLOW=ROOT/"config/device-allowlist.json"; SESSION=ROOT/"analysis/session-report.json"
TX=ROOT/"analysis/transactions.json"; INV=ROOT/"analysis/device_inventory.json"


class LiveStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.allow=load_allowlist(ALLOW)
    def target(self,pid): return next(x for x in self.allow["devices"] if x["vid_pid"]==pid)
    def run_case(self,pid="0416:5408",identity=None,responses=None,faults=None,seq_mut=None):
        target=self.target(pid); seq=load_sequence(SESSION,TX,pid)
        if seq_mut: seq_mut(seq)
        if responses is None: responses=[seq["ready"]]+([seq["ack"]] if seq["ack"] else [])
        tr=DryRunUsbTransport(identity or expected_identity(target),responses,faults)
        return LiveReplayMachine(target,seq,tr).run(),tr,seq
    def assert_failed_stopped(self,result,tr):
        self.assertIn(result["final_state"],(State.ERROR.value,State.ABORTED.value)); count=len(tr.writes)
        self.assertEqual(count,result["writes"])

    def test_happy_paths_and_clean_close(self):
        for pid,writes in (("0416:5408",78),("0416:5302",337)):
            r,t,_=self.run_case(pid); self.assertTrue(r["success"]); self.assertEqual(r["final_state"],"CLOSED")
            self.assertEqual(r["writes"],writes); self.assertTrue(t.closed); self.assertFalse(r["usb_hardware_opened"]); self.assertFalse(r["usb_hardware_written"])
            self.assertEqual([e["to"] for e in r["events"]][-2:],["CLOSING","CLOSED"])

    def test_identity_mapping_rejections(self):
        base=expected_identity(self.target("0416:5408"))
        changes={"vid_pid":"0416:9999","stable_instance_id":"USB\\WRONG","container_id":"{WRONG}",
                 "interface":9,"out_endpoint":"0x08","in_endpoint":"0x82","transfer_type":"interrupt","driver":"HIDUSB"}
        for field,value in changes.items():
            with self.subTest(field=field):
                r,t,_=self.run_case(identity=replace(base,**{field:value})); self.assert_failed_stopped(r,t); self.assertEqual(r["writes"],0)

    def test_readiness_failures(self):
        for responses,faults in (([],None),(None,{"read_timeout":True}),(None,{"disconnect_read":True}),
                                 (None,{"short_read":True}),([b"bad"],None)):
            r,t,_=self.run_case(responses=responses,faults=faults); self.assert_failed_stopped(r,t); self.assertEqual(r["writes"],1)
        def corrupt(s): s["ready"]=s["ready"][:24]+b"\x00\x00"+s["ready"][26:]
        r,t,_=self.run_case(seq_mut=corrupt); self.assert_failed_stopped(r,t)

    def test_short_init_disconnect_and_stall(self):
        for faults in ({"short_write":0},{"disconnect":0},{"stall":0},{"timeout":True}):
            r,t,_=self.run_case(faults=faults); self.assert_failed_stopped(r,t); self.assertLessEqual(r["writes"],1)

    def test_frame_interruptions_and_short_write(self):
        for faults in ({"disconnect":4},{"stall":4},{"reenumerate":4},{"short_write":4},{"reenumerate_revalidate":True}):
            r,t,_=self.run_case(faults=faults); self.assert_failed_stopped(r,t); self.assertLess(r["writes"],78)

    def test_5408_ack_failures_and_duplicates(self):
        seq=load_sequence(SESSION,TX,"0416:5408")
        for responses,faults in (([seq["ready"]],None),([seq["ready"],b"bad"],None),
                                 ([seq["ready"],seq["ack"]],{"pending_at":1})):
            r,t,_=self.run_case(responses=responses,faults=faults); self.assert_failed_stopped(r,t); self.assertEqual(r["writes"],78)

    def test_unexpected_input_before_frame(self):
        r,t,_=self.run_case(faults={"pending_at":0}); self.assert_failed_stopped(r,t); self.assertEqual(r["writes"],1)

    def test_5302_identity_and_unexpected_postframe_response(self):
        seq=load_sequence(SESSION,TX,"0416:5302"); bad=bytearray(seq["ready"]); bad[20:27]=b"WRONG!!"
        r,t,_=self.run_case("0416:5302",responses=[bytes(bad)]); self.assert_failed_stopped(r,t); self.assertEqual(r["writes"],1)
        r,t,_=self.run_case("0416:5302",faults={"pending_at":1}); self.assert_failed_stopped(r,t); self.assertEqual(r["writes"],337)

    def test_close_timeout(self):
        r,t,_=self.run_case(faults={"close_timeout":True}); self.assert_failed_stopped(r,t)

    def test_validators_and_preflight(self):
        for pid in ("0416:5408","0416:5302"):
            seq=load_sequence(SESSION,TX,pid); self.assertTrue(validate_ready(pid,seq["ready"],seq["ready"]))
            p=preflight(ALLOW,SESSION,TX,pid,INV); self.assertTrue(p["live_preconditions_pass"]); self.assertFalse(p["endpoints_opened"]); self.assertFalse(p["usb_written"])

    def test_live_sequence_rejects_cross_session_frame(self):
        with self.assertRaisesRegex(SafetyError,"cross-session mode mixing"):
            load_sequence(SESSION,TX,"0416:5408",require_same_session=True)

    def test_same_session_type01_sequence(self):
        p=ROOT/"analysis/pid5408-new-session-first-frame.json"
        s=load_sequence(SESSION,p,"0416:5408",require_same_session=True)
        self.assertEqual(s["id"],"0416:5408/pid5408-new-session-first-frame-transaction-1")
        self.assertEqual(s["frame"][0][:16].hex(),"01ff18aa0200f0010161010000000000")
        self.assertEqual((len(s["frame"]),sum(map(len,s["frame"]))),(45,182272))
        self.assertAlmostEqual(s["ready_to_frame_delay_ms"],7630.77,places=1)

    def test_persistent_hold_adds_no_writes_and_revalidates(self):
        target=self.target("0416:5408");seq=load_sequence(SESSION,TX,"0416:5408")
        tr=DryRunUsbTransport(expected_identity(target),[seq["ready"],seq["ack"]]);slept=[]
        result=LiveReplayMachine(target,seq,tr,hold_open_ms=15000,sleeper=slept.append).run()
        self.assertTrue(result["success"]);self.assertEqual(slept,[15.0]);self.assertEqual(result["writes"],78)
        hold=next(e for e in result["events"] if e["to"]=="HOLDING")
        self.assertEqual((hold["hold_open_ms"],hold["additional_writes"]),(15000,0))
    def test_bounded_repeated_frame_sessions_are_offline_and_exact(self):
        for pid,frames,expected_writes in (("0416:5408",3,1+3*77),("0416:5302",3,1+3*336)):
            target=self.target(pid);seq=load_sequence(SESSION,TX,pid);responses=[seq["ready"]]+([seq["ack"]]*frames if seq["ack"] else [])
            tr=DryRunUsbTransport(expected_identity(target),responses);clock=[0.0]
            def now():clock[0]+=.001;return clock[0]
            result=PersistentReplayMachine(target,seq,tr,frames,.01,clock=now,sleeper=lambda s:clock.__setitem__(0,clock[0]+s)).run()
            self.assertTrue(result["success"]);self.assertEqual(result["completed_frames"],3);self.assertEqual(result["writes"],expected_writes)
            self.assertFalse(result["usb_hardware_opened"]);self.assertFalse(result["usb_hardware_written"])
    def test_persistent_5408_missing_ack_fails_closed_without_retry(self):
        target=self.target("0416:5408");seq=load_sequence(SESSION,TX,"0416:5408")
        tr=DryRunUsbTransport(expected_identity(target),[seq["ready"],seq["ack"]])
        result=PersistentReplayMachine(target,seq,tr,2,.01,sleeper=lambda _:None).run()
        self.assertFalse(result["success"]);self.assertEqual((result["transmitted_frames"],result["accepted_frames"]),(2,1));self.assertEqual(result["writes"],1+2*77)
    def test_persistent_duration_is_hard_and_pnp_revalidation_is_not_per_frame(self):
        target=self.target("0416:5302");seq=load_sequence(SESSION,TX,"0416:5302");tr=DryRunUsbTransport(expected_identity(target),[seq["ready"]]);clock=[0.0]
        def now():return clock[0]
        def send_time(_):clock[0]+=.085
        revalidations=[0];original=tr.revalidate
        def revalidate(expected):revalidations[0]+=1;return original(expected)
        tr.revalidate=revalidate
        result=PersistentReplayMachine(target,seq,tr,351,1/30,clock=now,sleeper=send_time,duration_seconds=.3).run()
        self.assertTrue(result["success"]);self.assertLessEqual(result["transmitted_frames"],10);self.assertLess(result["transmitted_frames"],351)
        self.assertEqual(revalidations,[2])
