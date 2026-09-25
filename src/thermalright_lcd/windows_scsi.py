"""Windows SCSI pass-through adapter for reference-defined USBLCD panels."""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import json,subprocess
from .subprocess_utils import hidden_subprocess_kwargs
from .devices.thermalright_reference import build_scsi_cdb,detect_model,frame_packets
from .encoder import EncodedFrame

IOCTL_SCSI_PASS_THROUGH_DIRECT=0x4D014;GENERIC_READ=0x80000000;GENERIC_WRITE=0x40000000

def enumerate_scsi_candidates(runner=subprocess.run):
    script=("Get-CimInstance Win32_DiskDrive|ForEach-Object {[ordered]@{path=$_.DeviceID;pnp=$_.PNPDeviceID;model=$_.Model;status=$_.Status}}|ConvertTo-Json -Compress")
    cp=runner(["powershell","-NoProfile","-Command",script],capture_output=True,text=True,timeout=5,**hidden_subprocess_kwargs())
    if cp.returncode:raise RuntimeError("SCSI disk enumeration failed")
    raw=json.loads(cp.stdout or "[]");raw=[raw] if isinstance(raw,dict) else raw;out=[]
    for item in raw:
        pnp=str(item.get("pnp") or "").lower();model=str(item.get("model") or "")
        vp=next((x for x in ("87cd:70db","0402:3922","0416:5406") if f"vid_{x[:4]}&pid_{x[5:]}" in pnp),None)
        if vp and "usblcd" in model.lower() and str(item.get("status") or "OK").upper()=="OK":out.append((item["path"],vp))
    return tuple(out)

class CtypesScsiApi:
    def __init__(self):
        self.k=c.WinDLL("kernel32",use_last_error=True);self.k.CreateFileW.restype=w.HANDLE
    def open(self,path):
        h=self.k.CreateFileW(path,GENERIC_READ|GENERIC_WRITE,3,None,3,0,None)
        if h==c.c_void_p(-1).value:raise OSError(c.get_last_error(),"SCSI CreateFile")
        return h
    def command(self,handle,cdb,data,direction):
        buf=c.create_string_buffer(data if direction==0 else len(data));ptr=c.addressof(buf);s=c.create_string_buffer(92)
        c.memset(s,0,92);c.c_ushort.from_buffer(s,0).value=56;s[6]=len(cdb);s[7]=32;s[8]=direction
        c.c_uint.from_buffer(s,12).value=len(data);c.c_uint.from_buffer(s,16).value=10;c.c_void_p.from_buffer(s,24).value=ptr;c.c_uint.from_buffer(s,32).value=60
        c.memmove(c.addressof(s)+36,cdb,min(20,len(cdb)));returned=w.DWORD()
        if not self.k.DeviceIoControl(handle,IOCTL_SCSI_PASS_THROUGH_DIRECT,s,92,s,92,c.byref(returned),None):raise OSError(c.get_last_error(),"SCSI pass-through")
        return bytes(buf)
    def close(self,handle):self.k.CloseHandle(handle)

class ScsiPanelConnection:
    def __init__(self,path,vid_pid,api=None,max_frame_writes=4096):self.path=path;self.vid_pid=vid_pid;self.api=api or CtypesScsiApi();self.handle=None;self.model=None;self.writes=0;self.limit=max_frame_writes
    def open(self):
        if self.handle:return self.model
        self.handle=self.api.open(self.path)
        try:
            poll=self.api.command(self.handle,build_scsi_cdb(0xF5,0xE100),bytes(0xE100),1);self.model=detect_model(self.vid_pid,"scsi",poll)
            if self.model is None:raise RuntimeError("SCSI poll did not identify one supported model")
            self.api.command(self.handle,build_scsi_cdb(0x1F5,0xE100),bytes(0xE100),0);return self.model
        except Exception:self.close();raise
    def __call__(self,frame:EncodedFrame):
        model=self.open()
        if frame.vid_pid!=model.key or frame.dimensions!=model.render_size:raise RuntimeError("SCSI frame/model mismatch")
        if self.writes+len(frame.writes)>self.limit:raise RuntimeError("SCSI write budget exceeded")
        total=0
        for packet in frame.writes:
            cdb,data=packet[:20],packet[20:];self.api.command(self.handle,cdb,data,0);self.writes+=1;total+=len(data)
        return total
    def close(self,*_):
        if self.handle:self.api.close(self.handle);self.handle=None
