"""Safe Windows serial discovery and bounded transport for supported panels."""
from __future__ import annotations
from dataclasses import dataclass
import re

from .live_state import DeviceDisconnected, SafetyError, TransportError

@dataclass(frozen=True, slots=True)
class SerialCandidate:
    port: str
    instance_id: str
    vid_pid: str

def enumerate_serial_candidates(registry=None) -> tuple[SerialCandidate,...]:
    if registry is not None:return tuple(registry())
    try:import winreg
    except ImportError:return ()
    found=[];root=r"SYSTEM\CurrentControlSet\Enum\USB"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,root) as usb:
            for i in range(winreg.QueryInfoKey(usb)[0]):
                family=winreg.EnumKey(usb,i);match=re.fullmatch(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})",family,re.I)
                if not match:continue
                vid_pid=f"{match.group(1)}:{match.group(2)}".lower()
                if vid_pid not in {"33c3:7788","33c3:f101"}:continue
                with winreg.OpenKey(usb,family) as devices:
                    for j in range(winreg.QueryInfoKey(devices)[0]):
                        instance=winreg.EnumKey(devices,j)
                        try:
                            with winreg.OpenKey(devices,instance+r"\Device Parameters") as params:port=str(winreg.QueryValueEx(params,"PortName")[0])
                            if re.fullmatch(r"COM\d+",port,re.I):found.append(SerialCandidate(port,f"USB\\{family}\\{instance}",vid_pid))
                        except OSError:continue
    except OSError:return ()
    return tuple(found)

class PySerialIo:
    def __init__(self,port:str,baud:int,*,timeout:float=2.0,open_delay:float=0.0,serial_factory=None):
        self.port=port;self.baud=baud;self.timeout=timeout;self.open_delay=open_delay;self.factory=serial_factory;self.handle=None
    def open(self):
        if self.handle is not None:return
        try:
            factory=self.factory
            if factory is None:
                import serial
                factory=serial.Serial
            self.handle=factory(self.port,self.baud,timeout=self.timeout,write_timeout=5,dsrdtr=False,rtscts=False)
            self.handle.dtr=True;self.handle.rts=True
            if self.open_delay:
                import time;time.sleep(self.open_delay)
        except Exception as exc:raise DeviceDisconnected(f"cannot open supported panel on {self.port}: {exc}") from exc
    def write(self,data:bytes)->int:
        if self.handle is None:raise TransportError("serial panel is not open")
        count=self.handle.write(data)
        if count!=len(data):raise TransportError(f"short serial write {count}/{len(data)}")
        return count
    def read_until_quiet(self,maximum=65536)->bytes:
        if self.handle is None:raise TransportError("serial panel is not open")
        first=self.handle.read(1)
        if not first:return b""
        import time
        result=bytearray(first);quiet_since=time.monotonic();deadline=quiet_since+.3
        while len(result)<maximum and time.monotonic()<deadline:
            waiting=int(getattr(self.handle,"in_waiting",0))
            if not waiting:
                if time.monotonic()-quiet_since>=.03:break
                time.sleep(.005);continue
            result.extend(self.handle.read(min(waiting,maximum-len(result))))
            quiet_since=time.monotonic()
        return bytes(result)
    def close(self):
        handle,self.handle=self.handle,None
        if handle is not None:handle.close()
