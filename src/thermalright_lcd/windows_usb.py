from __future__ import annotations

import ctypes
from copy import deepcopy
import json
import subprocess
from .subprocess_utils import hidden_subprocess_kwargs
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

from .live_state import (DeviceDisconnected, TransportError, TransportStall,
                         TransportTimeout, DeviceIdentity, SafetyError,
                         expected_identity, validate_identity)


ERROR_SEM_TIMEOUT=121; ERROR_GEN_FAILURE=31; ERROR_DEVICE_NOT_CONNECTED=1167
ERROR_OPERATION_ABORTED=995; INVALID_HANDLE_VALUE=ctypes.c_void_p(-1).value
FILE_FLAG_OVERLAPPED=0x40000000
ERROR_IO_PENDING=997; WAIT_OBJECT_0=0; WAIT_TIMEOUT=258

class _OVERLAPPED(ctypes.Structure):
    _fields_=[("Internal",ctypes.c_size_t),("InternalHigh",ctypes.c_size_t),("Offset",wintypes.DWORD),("OffsetHigh",wintypes.DWORD),("hEvent",wintypes.HANDLE)]


class WindowsUsbApi(Protocol):
    def create_file(self,path:str,timeout_ms:int): ...
    def winusb_initialize(self,handle): ...
    def query_pipe(self,usb_handle,interface:int,endpoint:int): ...
    def set_timeout(self,usb_handle,endpoint:int,timeout_ms:int): ...
    def write_pipe(self,usb_handle,endpoint:int,data:bytes): ...
    def read_pipe(self,usb_handle,endpoint:int,length:int): ...
    def abort_pipe(self,usb_handle,endpoint:int): ...
    def reset_pipe(self,usb_handle,endpoint:int): ...
    def free(self,usb_handle): ...
    def close_handle(self,handle): ...


def classify_win_error(code:int,operation:str):
    if code==ERROR_SEM_TIMEOUT: return TransportTimeout(f"{operation} timeout")
    if code==ERROR_DEVICE_NOT_CONNECTED: return DeviceDisconnected(f"{operation}: device disconnected")
    if code in (ERROR_GEN_FAILURE,): return TransportStall(f"{operation}: endpoint stall/general failure")
    return TransportError(f"{operation} failed with Windows error {code}")


class CtypesWinUsbApi:
    """Thin synchronous WinUSB boundary. No object construction opens a device."""
    def __init__(self):
        if not hasattr(ctypes,"WinDLL"): raise OSError("WinUSB transport requires Windows")
        self.k=ctypes.WinDLL("kernel32",use_last_error=True); self.w=ctypes.WinDLL("winusb",use_last_error=True)
        self.k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        self.k.CreateFileW.restype=wintypes.HANDLE
        self.k.CloseHandle.argtypes=[wintypes.HANDLE]; self.k.CloseHandle.restype=wintypes.BOOL
        self.k.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR];self.k.CreateEventW.restype=wintypes.HANDLE
        self.k.ResetEvent.argtypes=[wintypes.HANDLE];self.k.ResetEvent.restype=wintypes.BOOL
        self.k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];self.k.WaitForSingleObject.restype=wintypes.DWORD
        self.k.CancelIoEx.argtypes=[wintypes.HANDLE,ctypes.POINTER(_OVERLAPPED)];self.k.CancelIoEx.restype=wintypes.BOOL
        self.w.WinUsb_Initialize.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_void_p)]
        self.w.WinUsb_Initialize.restype=wintypes.BOOL
        self.w.WinUsb_WritePipe.argtypes=[ctypes.c_void_p,ctypes.c_ubyte,ctypes.c_void_p,wintypes.ULONG,ctypes.POINTER(wintypes.ULONG),ctypes.POINTER(_OVERLAPPED)];self.w.WinUsb_WritePipe.restype=wintypes.BOOL
        self.w.WinUsb_ReadPipe.argtypes=[ctypes.c_void_p,ctypes.c_ubyte,ctypes.c_void_p,wintypes.ULONG,ctypes.POINTER(wintypes.ULONG),ctypes.POINTER(_OVERLAPPED)];self.w.WinUsb_ReadPipe.restype=wintypes.BOOL
        self.w.WinUsb_GetOverlappedResult.argtypes=[ctypes.c_void_p,ctypes.POINTER(_OVERLAPPED),ctypes.POINTER(wintypes.ULONG),wintypes.BOOL];self.w.WinUsb_GetOverlappedResult.restype=wintypes.BOOL
        self.w.WinUsb_ResetPipe.argtypes=[ctypes.c_void_p,ctypes.c_ubyte];self.w.WinUsb_ResetPipe.restype=wintypes.BOOL
        self._file_handle=None;self._event=None;self._timeout_ms=1000
    def _raise(self,op): raise classify_win_error(ctypes.get_last_error(),op)
    def create_file(self,path,timeout_ms):
        # WinUSB requires a device handle created with FILE_FLAG_OVERLAPPED,
        # even when individual transfers are submitted synchronously.
        h=self.k.CreateFileW(path,0xC0000000,0x3,None,3,FILE_FLAG_OVERLAPPED,None)
        if h==INVALID_HANDLE_VALUE: self._raise("CreateFile")
        self._file_handle=h;self._event=self.k.CreateEventW(None,True,False,None)
        if not self._event:self.k.CloseHandle(h);self._file_handle=None;self._raise("CreateEvent")
        return h
    def winusb_initialize(self,handle):
        u=ctypes.c_void_p()
        if not self.w.WinUsb_Initialize(handle,ctypes.byref(u)): self._raise("WinUsb_Initialize")
        return u
    def query_pipe(self,u,interface,endpoint):
        # Query all alternate-setting-zero pipes and return the matching tuple.
        class P(ctypes.Structure): _fields_=[("PipeType",ctypes.c_int),("PipeId",ctypes.c_ubyte),("MaximumPacketSize",ctypes.c_ushort),("Interval",ctypes.c_ubyte)]
        for i in range(32):
            p=P()
            if not self.w.WinUsb_QueryPipe(u,0,i,ctypes.byref(p)):
                if ctypes.get_last_error()==259: break
                self._raise("WinUsb_QueryPipe")
            if p.PipeId==endpoint: return {"endpoint":p.PipeId,"type":p.PipeType,"maximum_packet_size":p.MaximumPacketSize}
        raise TransportError(f"endpoint 0x{endpoint:02x} not exposed")
    def set_timeout(self,u,endpoint,timeout_ms):
        self._timeout_ms=int(timeout_ms)
        v=wintypes.ULONG(timeout_ms)
        if not self.w.WinUsb_SetPipePolicy(u,endpoint,3,ctypes.sizeof(v),ctypes.byref(v)): self._raise("WinUsb_SetPipePolicy")
    def _overlapped(self,u,endpoint,buffer,length,write):
        if not self._event or not self.k.ResetEvent(self._event):self._raise("ResetEvent")
        ov=_OVERLAPPED();ov.hEvent=self._event;n=wintypes.ULONG();fn=self.w.WinUsb_WritePipe if write else self.w.WinUsb_ReadPipe
        ok=fn(u,endpoint,buffer,length,ctypes.byref(n),ctypes.byref(ov))
        if not ok and ctypes.get_last_error()!=ERROR_IO_PENDING:self._raise("WinUsb_WritePipe" if write else "WinUsb_ReadPipe")
        wait=self.k.WaitForSingleObject(self._event,self._timeout_ms)
        if wait==WAIT_TIMEOUT:
            self.k.CancelIoEx(self._file_handle,ctypes.byref(ov));self.k.WaitForSingleObject(self._event,1000)
            raise TransportTimeout("WinUSB transfer timeout")
        if wait!=WAIT_OBJECT_0:raise TransportError(f"WinUSB wait failed: {wait}")
        if not self.w.WinUsb_GetOverlappedResult(u,ctypes.byref(ov),ctypes.byref(n),False):self._raise("WinUsb_GetOverlappedResult")
        return n.value
    def write_pipe(self,u,endpoint,data):
        b=ctypes.create_string_buffer(data);return self._overlapped(u,endpoint,b,len(data),True)
    def read_pipe(self,u,endpoint,length):
        b=ctypes.create_string_buffer(length);n=self._overlapped(u,endpoint,b,length,False);return b.raw[:n]
    def abort_pipe(self,u,endpoint): self.w.WinUsb_AbortPipe(u,endpoint)
    def reset_pipe(self,u,endpoint):
        if not self.w.WinUsb_ResetPipe(u,endpoint):self._raise("WinUsb_ResetPipe")
    def free(self,u):
        if u: self.w.WinUsb_Free(u)
    def close_handle(self,h):
        event,self._event=self._event,None
        if event:self.k.CloseHandle(event)
        if h not in (None,INVALID_HANDLE_VALUE): self.k.CloseHandle(h)
        self._file_handle=None


def discover_identity(target: dict) -> DeviceIdentity:
    """Fresh read-only PnP discovery; never trusts a transient USB bus address."""
    sid=target["stable_instance_id"].replace("'","''"); iid=target["interface_instance_id"].replace("'","''")
    script=(f"$d=Get-PnpDevice -InstanceId '{sid}' -ErrorAction Stop; "
            f"$p=Get-PnpDeviceProperty -InstanceId '{sid}'; $ip=Get-PnpDeviceProperty -InstanceId '{iid}'; "
            "$o=[ordered]@{status=$d.Status;instance_id=$d.InstanceId;"
            "container_id=($p|? KeyName -eq 'DEVPKEY_Device_ContainerId').Data;"
            "service=($ip|? KeyName -eq 'DEVPKEY_Device_Service').Data;"
            "location=(($p|? KeyName -eq 'DEVPKEY_Device_LocationPaths').Data -join '|')};$o|ConvertTo-Json -Compress")
    cp=subprocess.run(["powershell","-NoProfile","-Command",script],capture_output=True,text=True,timeout=5,**hidden_subprocess_kwargs())
    if cp.returncode: raise DeviceDisconnected("allowlisted PnP identity not present")
    d=json.loads(cp.stdout)
    if d["status"]!="OK": raise DeviceDisconnected("device status is not OK")
    generation=f"{d.get('container_id')}|{d.get('location')}"
    return DeviceIdentity(target["vid_pid"],d["instance_id"],d.get("container_id"),target["interface"],
                          target["endpoint"],target["response_endpoint"],target["transfer_type"],
                          d.get("service") or "",generation,target.get("confirmed_device_path"),target["host_payload_size"])


def materialize_reviewed_winusb_target(definition: dict) -> dict:
    """Bind the reviewed 5408 definition to exactly one present WinUSB LCD."""
    if definition.get("vid_pid") != "0416:5408":raise SafetyError("unsupported reviewed WinUSB definition")
    script=("$ds=@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\\\VID_0416&PID_5408\\\\' });"
            "$items=@();foreach($d in $ds){$p=Get-PnpDeviceProperty -InstanceId $d.InstanceId;"
            "$items+=@([ordered]@{status=$d.Status;instance_id=$d.InstanceId;container_id=($p|? KeyName -eq 'DEVPKEY_Device_ContainerId').Data;service=($p|? KeyName -eq 'DEVPKEY_Device_Service').Data})};"
            "[ordered]@{count=$items.Count;items=$items}|ConvertTo-Json -Compress -Depth 4")
    cp=subprocess.run(["powershell","-NoProfile","-Command",script],capture_output=True,text=True,timeout=5,**hidden_subprocess_kwargs())
    if cp.returncode:raise DeviceDisconnected("reviewed PID 5408 is not present")
    result=json.loads(cp.stdout);items=result.get("items") or []
    if isinstance(items,dict):items=[items]
    if result.get("count")!=1:raise SafetyError(f"expected one reviewed PID 5408 device, found {result.get('count',0)}")
    item=items[0]
    if item.get("status")!="OK" or str(item.get("service","")).upper()!="WINUSB":raise SafetyError("PID 5408 requires an OK WinUSB device")
    target=deepcopy(definition);sid=item["instance_id"];guid=target["interface_guid"]
    target.update(stable_instance_id=sid,interface_instance_id=sid,container_id=str(item.get("container_id") or ""),confirmed_device_path="\\\\?\\"+sid.replace("\\","#")+"#"+guid)
    if not target["container_id"] or not device_path_registered(target):raise SafetyError("PID 5408 reviewed interface path is not registered")
    actual=discover_identity(target);validate_identity(actual,expected_identity(target));return target


def device_path_registered(target: dict) -> bool:
    guid=target.get("interface_guid"); path=target.get("confirmed_device_path")
    if not guid or not path: return False
    try:
        import winreg
        encoded=path[4:].replace("\\","#") if path.startswith("\\\\?\\") else path
        key=fr"SYSTEM\CurrentControlSet\Control\DeviceClasses\{guid}\##?#{encoded}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key): return True
    except OSError: return False
