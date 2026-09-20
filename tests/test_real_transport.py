import unittest
from dataclasses import replace
from pathlib import Path

from thermalright_lcd.live_state import (DeviceDisconnected, RealUsbTransport, SafetyError,
    TransportError, expected_identity, load_sequence, require_live_authorization)
from thermalright_lcd.replay import load_allowlist
from thermalright_lcd.windows_usb import FILE_FLAG_OVERLAPPED

ROOT=Path(__file__).resolve().parents[1]; ALLOW=ROOT/"config/device-allowlist.json"


class MockApi:
    def __init__(self): self.calls=[]; self.fail=None; self.short_write=False; self.short_read=False; self.bad_pipe=False
    def create_file(self,p,t): self.calls.append(("open",p)); self._f("open"); return 10
    def winusb_initialize(self,h): self._f("initialize"); return 20
    def query_pipe(self,u,i,e):
        self._f("query"); return {"endpoint":e+1 if self.bad_pipe else e,"type":2,"maximum_packet_size":512}
    def set_timeout(self,*a): self._f("timeout")
    def write_pipe(self,u,e,d): self._f("write"); return len(d)-1 if self.short_write else len(d)
    def read_pipe(self,u,e,n): self._f("read"); return bytes(n-1 if self.short_read else n)
    def abort_pipe(self,*a): self._f("abort")
    def reset_pipe(self,*a): self.calls.append(("reset",a[-1]));self._f("reset")
    def free(self,*a): self.calls.append(("free",))
    def close_handle(self,*a): self.calls.append(("close",))
    def _f(self,name):
        if self.fail==name: raise TransportError(name+" failure")


class RealTransportBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.target=load_allowlist(ALLOW)["devices"][0]
    def make(self,identity=None,api=None):
        ident=identity or expected_identity(self.target); api=api or MockApi()
        return RealUsbTransport(self.target,lambda:ident,api,78,317440),api,ident
    def test_open_and_cleanup(self):
        self.assertEqual(FILE_FLAG_OVERLAPPED,0x40000000)
        tr,api,_=self.make(); tr.discover(); tr.open(1000); tr.close(1000)
        self.assertTrue(tr.hardware_ever_opened); self.assertEqual(tr.hardware_write_calls,0)
        self.assertEqual(tr.pipe_reset_count,2);self.assertIn(("reset",0x09),api.calls);self.assertIn(("reset",0x81),api.calls)
        self.assertIn(("free",),api.calls); self.assertIn(("close",),api.calls)
    def test_open_failures_and_endpoint_mismatch(self):
        for failure in ("open","initialize","query"):
            api=MockApi(); api.fail=failure; tr,_,_=self.make(api=api); tr.discover()
            with self.assertRaises(TransportError): tr.open(1000)
        api=MockApi(); api.bad_pipe=True; tr,_,_=self.make(api=api); tr.discover()
        with self.assertRaises(SafetyError): tr.open(1000)
    def test_path_identity_driver_and_capacity_rejected(self):
        base=expected_identity(self.target)
        for change in ({"device_path":"wrong"},{"stable_instance_id":"wrong"},{"container_id":"wrong"},
                       {"driver":"HIDUSB"},{"maximum_transfer_size":1}):
            tr,_,_=self.make(replace(base,**change))
            actual=tr.discover()
            from thermalright_lcd.live_state import validate_identity
            with self.assertRaises(SafetyError): validate_identity(actual,base)
    def test_short_io_and_close_failure(self):
        api=MockApi(); tr,_,_=self.make(api=api); tr.discover(); tr.open(1000)
        api.short_write=True
        with self.assertRaises(TransportError): tr.write("0x09",b"123",100)
        api.short_write=False; api.short_read=True
        with self.assertRaises(TransportError): tr.read("0x81",3,100)
        api.fail="abort"
        with self.assertRaises(TransportError): tr.close(100)
    def test_disconnect_and_reenumeration(self):
        base=expected_identity(self.target); current=[base]
        tr=RealUsbTransport(self.target,lambda:current[0],MockApi(),78,317440); tr.discover(); tr.open(100)
        current[0]=replace(base,generation="new")
        with self.assertRaises(Exception): tr.revalidate(base)
    def test_hard_write_budget(self):
        tr,_,_=self.make(); tr.write_budget_count=1; tr.write_budget_bytes=3; tr.discover(); tr.open(100)
        self.assertEqual(tr.write("0x09",b"123",100),3)
        with self.assertRaises(SafetyError): tr.write("0x09",b"1",100)


class AuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target=load_allowlist(ALLOW)["devices"][0]; cls.seq="0416:5408/capture-transaction-1"
    def auth(self,**kw):
        args=dict(supplied_stable_id=self.target["stable_instance_id"],supplied_sequence=self.seq,
                  expected_sequence=self.seq,send=True,acknowledged=True,confirmation="SEND EXACT CAPTURED FRAME")
        args.update(kw); return require_live_authorization(self.target,**args)
    def test_allow_live_false(self):
        target=dict(self.target); target["allowLiveReplay"]=False
        with self.assertRaisesRegex(SafetyError,"allowLiveReplay=false"):
            require_live_authorization(target,target["stable_instance_id"],self.seq,self.seq,True,True,"SEND EXACT CAPTURED FRAME")
    def test_each_gate_missing_or_wrong(self):
        cases=({"send":False},{"acknowledged":False},{"supplied_stable_id":"wrong"},
               {"supplied_sequence":"wrong"},{"confirmation":"yes"})
        for case in cases:
            with self.subTest(case=case), self.assertRaises(SafetyError): self.auth(**case)
    def test_all_gates_when_explicitly_enabled_copy(self):
        target=dict(self.target); target["allowLiveReplay"]=True
        require_live_authorization(target,target["stable_instance_id"],self.seq,self.seq,True,True,"SEND EXACT CAPTURED FRAME")
