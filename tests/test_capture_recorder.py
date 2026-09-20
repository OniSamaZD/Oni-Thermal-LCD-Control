import subprocess
import tempfile
import unittest
from pathlib import Path

from thermalright_lcd.capture_recorder import (CaptureValidationError,RecorderElevationError,
    RecorderStartupError,UsbPcapRecorder,validate_capture)


class FakeProcess:
    def __init__(self,early=False,timeout=False):
        self.returncode=1 if early else None;self.timeout=timeout;self.signals=[];self.terminated=False;self.killed=False
    def poll(self):return self.returncode
    def send_signal(self,value):self.signals.append(value)
    def wait(self,timeout=None):
        if self.timeout and not self.terminated:raise subprocess.TimeoutExpired("x",timeout)
        self.returncode=0;return 0
    def terminate(self):self.terminated=True;self.returncode=0
    def kill(self):self.killed=True;self.returncode=-9


class RecorderTests(unittest.TestCase):
    def make(self,d,process=None,popen_error=None):
        exe=Path(d)/"USBPcapCMD.exe";exe.write_bytes(b"x")
        process=process or FakeProcess()
        def popen(*a,**k):
            if popen_error:raise popen_error
            return process
        return UsbPcapRecorder(exe,popen,lambda _:None),process
    def test_successful_start_and_clean_stop(self):
        with tempfile.TemporaryDirectory() as d:
            r,p=self.make(d);cmd=r.start("USBPcap3",Path(d)/"x.pcap",startup_wait=0);r.run_for(0);r.stop()
            self.assertIn(r"\\.\USBPcap3",cmd);self.assertTrue(p.signals);self.assertEqual(p.returncode,0)
    def test_startup_failure(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.make(d,popen_error=OSError("no"))
            with self.assertRaises(RecorderStartupError):r.start("USBPcap3",Path(d)/"x.pcap",startup_wait=0)
    def test_elevation_failure(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.make(d)
            with self.assertRaises(RecorderElevationError):r.start("USBPcap3",Path(d)/"x.pcap",elevated=True)
    def test_bad_controller(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.make(d)
            with self.assertRaises(RecorderStartupError):r.start("bad",Path(d)/"x.pcap")
    def test_invalid_output_path(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.make(d)
            with self.assertRaises(RecorderStartupError):r.start("USBPcap3",Path(d)/"missing"/"x.pcap")
    def test_early_process_exit(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.make(d,FakeProcess(early=True))
            with self.assertRaises(RecorderStartupError):r.start("USBPcap3",Path(d)/"x.pcap",startup_wait=0)
    def test_timeout_stop_terminates(self):
        with tempfile.TemporaryDirectory() as d:
            r,p=self.make(d,FakeProcess(timeout=True));r.start("USBPcap3",Path(d)/"x.pcap",startup_wait=0);r.stop(.01)
            self.assertTrue(p.terminated)
    def test_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r,_=self.make(d);out=Path(d)/"x.pcap";out.write_bytes(b"old")
            with self.assertRaises(RecorderStartupError):r.start("USBPcap3",out)
    def test_capture_validation_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.pcap";p.write_bytes(b"broken")
            with self.assertRaises(CaptureValidationError):validate_capture(p)

if __name__=="__main__":unittest.main()
