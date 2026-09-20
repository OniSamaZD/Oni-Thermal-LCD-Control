from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class RecorderError(RuntimeError): pass
class RecorderStartupError(RecorderError): pass
class RecorderElevationError(RecorderError): pass
class CaptureValidationError(RecorderError): pass


@dataclass(frozen=True)
class CaptureValidation:
    path: str
    packets: int
    duration_seconds: float
    file_type: str
    encapsulation: str
    sha256: str


def _value(text:str,label:str)->str:
    match=re.search(rf"(?mi)^\s*{re.escape(label)}:\s*(.+?)\s*$",text)
    if not match:raise CaptureValidationError(f"capinfos missing {label}")
    return match.group(1).strip()


def validate_capture(path:Path,capinfos:str=r"C:\Program Files\Wireshark\capinfos.exe",
                     tshark:str=r"C:\Program Files\Wireshark\tshark.exe",minimum_packets:int=31)->CaptureValidation:
    if not path.is_file() or path.stat().st_size<=24:raise CaptureValidationError("capture file missing or empty")
    info=subprocess.run([capinfos,"-c","-u","-t","-E","-H",str(path)],capture_output=True,text=True,timeout=15)
    if info.returncode:raise CaptureValidationError("capinfos rejected capture: "+info.stderr.strip())
    packets=int(_value(info.stdout,"Number of packets").replace(",",""))
    duration=float(_value(info.stdout,"Capture duration").split()[0].replace(",","."))
    file_type=_value(info.stdout,"File type")
    encapsulation=_value(info.stdout,"File encapsulation")
    if packets<minimum_packets:raise CaptureValidationError(f"packet count {packets} < {minimum_packets}")
    if duration<=0:raise CaptureValidationError("capture duration is not positive")
    if "usb" not in encapsulation.lower() or "usbpcap" not in encapsulation.lower():raise CaptureValidationError("not USBPcap encapsulation")
    probe=subprocess.run([tshark,"-r",str(path),"-c","1","-T","fields","-e","frame.number"],capture_output=True,text=True,timeout=15)
    if probe.returncode or probe.stdout.strip()!="1":raise CaptureValidationError("tshark could not read capture cleanly")
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    return CaptureValidation(str(path),packets,duration,file_type,encapsulation,digest)


class UsbPcapRecorder:
    def __init__(self,executable:Path=Path(r"C:\Program Files\USBPcap\USBPcapCMD.exe"),
                 popen:Callable= subprocess.Popen,sleep:Callable=time.sleep):
        self.executable=executable;self.popen=popen;self.sleep=sleep;self.process=None
        self.stdout_handle=None;self.stderr_handle=None;self.command=[];self.controller=None;self.output=None

    def start(self,controller:str,output:Path,elevated:bool=False,startup_wait:float=1.0):
        if not re.fullmatch(r"USBPcap[1-9][0-9]*",controller):raise RecorderStartupError("invalid USBPcap controller")
        if elevated:raise RecorderElevationError("detached elevation cannot preserve a reliable recorder process handle")
        if not self.executable.is_file():raise RecorderStartupError("USBPcapCMD not found")
        output=output.resolve()
        if not output.parent.is_dir():raise RecorderStartupError("capture output directory does not exist")
        if output.exists():raise RecorderStartupError("capture output already exists")
        self.controller=controller;self.output=output
        stdout_path=output.with_suffix(output.suffix+".stdout.log");stderr_path=output.with_suffix(output.suffix+".stderr.log")
        self.stdout_handle=stdout_path.open("wb");self.stderr_handle=stderr_path.open("wb")
        self.command=[str(self.executable),"-d",rf"\\.\{controller}","-o",str(output),"--inject-descriptors","-A"]
        flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
        try:self.process=self.popen(self.command,stdin=subprocess.DEVNULL,stdout=self.stdout_handle,stderr=self.stderr_handle,creationflags=flags)
        except OSError as exc:
            self._close_logs();raise RecorderStartupError(f"recorder launch failed: {exc}") from exc
        self.sleep(startup_wait)
        if self.process.poll() is not None:
            code=self.process.returncode;self._close_logs()
            raise RecorderStartupError(f"USBPcapCMD exited during startup with code {code}")
        return self.command

    def run_for(self,duration_seconds:float):
        if self.process is None:raise RecorderStartupError("recorder was not started")
        deadline=time.monotonic()+duration_seconds
        while time.monotonic()<deadline:
            if self.process.poll() is not None:raise RecorderStartupError(f"USBPcapCMD exited early with code {self.process.returncode}")
            self.sleep(min(.1,max(0,deadline-time.monotonic())))

    def stop(self,timeout_seconds:float=5.0):
        if self.process is None:return
        if self.process.poll() is None:
            try:self.process.send_signal(getattr(signal,"CTRL_BREAK_EVENT",signal.SIGTERM));self.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:self.process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=timeout_seconds)
        self._close_logs()

    def _close_logs(self):
        for handle in (self.stdout_handle,self.stderr_handle):
            if handle and not handle.closed:handle.flush();handle.close()


def capture_selftest(controller:str,duration:int,output:Path)->dict:
    if duration<10:raise RecorderError("self-test duration must be at least 10 seconds")
    if not re.fullmatch(r"USBPcap[1-9][0-9]*",controller):raise RecorderStartupError("invalid USBPcap controller")
    output=output.resolve();capture_duration=duration+2
    tshark=Path(r"C:\Program Files\Wireshark\tshark.exe")
    listing=subprocess.run([str(tshark),"-D"],capture_output=True,text=True,timeout=10)
    if listing.returncode or not re.search(rf"(?mi)^\d+\..*\({re.escape(controller)}\)\s*$",listing.stdout+listing.stderr):
        raise RecorderStartupError(f"controller {controller} not enumerated by tshark")
    command=[str(tshark),"-i",controller,"-a",f"duration:{capture_duration}","-w",str(output)]
    stdout=output.with_suffix(output.suffix+".stdout.log").open("wb");stderr=output.with_suffix(output.suffix+".stderr.log").open("wb")
    started=time.time();host=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
    time.sleep(1)
    if host.poll() is not None:
        stdout.close();stderr.close();raise RecorderStartupError(f"tshark/USBPcap exited during startup: {host.returncode}")
    from .windows_hid import read_only_hid_report_scan
    time.sleep(duration/2)
    probe=read_only_hid_report_scan(0x373e,0x0050)
    remaining=max(0,duration-(time.time()-started));time.sleep(remaining)
    try:host.wait(timeout=15)
    except subprocess.TimeoutExpired:host.terminate();host.wait(5);raise RecorderError("tshark failed automatic duration stop")
    finally:stdout.flush();stderr.flush();stdout.close();stderr.close()
    if host.returncode:raise RecorderError(f"tshark/USBPcap failed: {host.returncode}")
    validation=validate_capture(output)
    return {"mode":"recorder-only","controller":controller,"frontend":"tshark USBPcap extcap","command":command,"requested_duration_seconds":duration,
            "wall_duration_seconds":time.time()-started,"capture":validation.__dict__,
            "read_only_probe":probe,"thermalright_device_opened_for_writing":False,
            "usb_writes":0,"replay_state_machine_run":False}


def compare_pid5302_hid_replay(capture:Path,session_file:Path,transaction_file:Path,output:Path)->dict:
    """Automated byte/timing comparison for a recorded PID 5302 HID replay."""
    from .live_state import load_sequence
    sequence=load_sequence(session_file,transaction_file,"0416:5302",1,require_same_session=True)
    tshark=r"C:\Program Files\Wireshark\tshark.exe"
    fields=["frame.number","frame.time_epoch","frame.interface_name","usb.bus_id","usb.device_address","usb.endpoint_address","usbhid.data"]
    command=[tshark,"-r",str(capture),"-Y","usbhid.data","-T","fields"]
    for field in fields:command.extend(["-e",field])
    cp=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if cp.returncode:raise CaptureValidationError("tshark HID extraction failed: "+cp.stderr.strip())
    rows=[]
    for line in cp.stdout.splitlines():
        parts=line.split("\t")
        if len(parts)!=len(fields) or not parts[-1]:continue
        try:data=bytes.fromhex(parts[-1].replace(":",""))
        except ValueError:continue
        rows.append({"frame":int(parts[0]),"timestamp":float(parts[1]),"interface":parts[2],"bus":parts[3],"device":parts[4],"endpoint":parts[5].lower(),"data":data})
    init=next((r for r in rows if r["endpoint"]=="0x02" and r["data"]==sequence["init"]),None)
    if not init:raise CaptureValidationError("exact PID 5302 initialization not found")
    target=[r for r in rows if r["bus"]==init["bus"] and r["device"]==init["device"] and r["timestamp"]>=init["timestamp"]]
    ready=next((r for r in target if r["endpoint"]=="0x83"),None)
    outs=[r for r in target if r["endpoint"]=="0x02"]
    observed_frame=[r["data"] for r in outs[1:1+len(sequence["frame"])]]
    extra_out=outs[1+len(sequence["frame"]):]
    extra_in=[r for r in target if r["endpoint"]=="0x83" and (not ready or r["frame"]!=ready["frame"])]
    frame_start=outs[1]["timestamp"] if len(outs)>1 else None;frame_end=outs[len(sequence["frame"])]["timestamp"] if len(outs)>len(sequence["frame"])-1 else None
    stderr_path=Path(str(capture)+".stderr.log");stderr=stderr_path.read_text(encoding="utf-8",errors="replace") if stderr_path.exists() else ""
    report={"capture":str(capture.resolve()),"capture_sha256":hashlib.sha256(capture.read_bytes()).hexdigest(),
            "sequence_id":sequence["id"],"interface_name":init["interface"],"bus_id":int(init["bus"]),"device_address":int(init["device"]),
            "initialization":{"frame":init["frame"],"exact_match":True,"bytes":len(init["data"])},
            "readiness":{"frame":ready["frame"] if ready else None,"exact_match":bool(ready and ready["data"]==sequence["ready"]),"bytes":len(ready["data"]) if ready else 0},
            "frame":{"expected_writes":len(sequence["frame"]),"observed_writes":len(observed_frame),
                     "expected_bytes":sum(map(len,sequence["frame"])),"observed_bytes":sum(map(len,observed_frame)),
                     "all_payloads_exact":observed_frame==sequence["frame"],"sha256":hashlib.sha256(b"".join(observed_frame)).hexdigest(),
                     "ready_to_frame_ms":(frame_start-ready["timestamp"])*1000 if ready and frame_start else None,
                     "duration_ms":(frame_end-frame_start)*1000 if frame_start and frame_end else None},
            "responses":{"extra_in_count":len(extra_in),"frame_ack_expected":False},"extra_out_count":len(extra_out),
            "recorder_warning":stderr.strip(),"target_transaction_complete_despite_global_drop":bool(observed_frame==sequence["frame"] and ready and ready["data"]==sequence["ready"]),
            "pass":bool(ready and ready["data"]==sequence["ready"] and observed_frame==sequence["frame"] and not extra_out and not extra_in)}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report
