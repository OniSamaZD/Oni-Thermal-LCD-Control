from __future__ import annotations
import ctypes as c
from copy import deepcopy
import json
import subprocess
from .subprocess_utils import hidden_subprocess_kwargs
from ctypes import wintypes as w
from dataclasses import dataclass
from typing import Protocol

from .live_state import (DeviceDisconnected, DeviceIdentity, DeviceReenumerated,
                         SafetyError, TransportError, TransportTimeout, UsbTransport,
                         expected_identity, validate_identity)

HID_GUID="{4d1e55b2-f16f-11cf-88cb-001111000030}"
INVALID_HANDLE_VALUE=c.c_void_p(-1).value
FILE_FLAG_OVERLAPPED=0x40000000
ERROR_IO_PENDING=997
ERROR_OPERATION_ABORTED=995
ERROR_DEVICE_NOT_CONNECTED=1167

@dataclass(frozen=True)
class HidInterface:
    path:str; vid:int; pid:int; version:int; input_report_bytes:int; output_report_bytes:int

class _GUID(c.Structure):
    _fields_=[("Data1",w.DWORD),("Data2",w.WORD),("Data3",w.WORD),("Data4",c.c_ubyte*8)]
class _ATTR(c.Structure):
    _fields_=[("Size",w.ULONG),("VendorID",w.USHORT),("ProductID",w.USHORT),("VersionNumber",w.USHORT)]
class _CAPS(c.Structure):
    _fields_=[("Usage",w.USHORT),("UsagePage",w.USHORT),("InputReportByteLength",w.USHORT),("OutputReportByteLength",w.USHORT),("FeatureReportByteLength",w.USHORT),("Reserved",w.USHORT*17),("NumberLinkCollectionNodes",w.USHORT),("NumberInputButtonCaps",w.USHORT),("NumberInputValueCaps",w.USHORT),("NumberInputDataIndices",w.USHORT),("NumberOutputButtonCaps",w.USHORT),("NumberOutputValueCaps",w.USHORT),("NumberOutputDataIndices",w.USHORT),("NumberFeatureButtonCaps",w.USHORT),("NumberFeatureValueCaps",w.USHORT),("NumberFeatureDataIndices",w.USHORT)]
class _OVERLAPPED(c.Structure):
    _fields_=[("Internal",c.c_size_t),("InternalHigh",c.c_size_t),("Offset",w.DWORD),("OffsetHigh",w.DWORD),("hEvent",w.HANDLE)]

def _guid(text:str)->_GUID:
    import uuid
    b=uuid.UUID(text.strip("{}")).bytes_le; g=_GUID();c.memmove(c.byref(g),b,16);return g

def enumerate_paths(api=None)->list[str]:
    if api is not None:return api.enumerate_paths()
    cfg=c.WinDLL("cfgmgr32",use_last_error=True);g=_guid(HID_GUID);n=w.ULONG()
    size=cfg.CM_Get_Device_Interface_List_SizeW(c.byref(n),c.byref(g),None,0)
    if size: raise OSError(size,"CM_Get_Device_Interface_List_SizeW")
    buf=c.create_unicode_buffer(n.value)
    rc=cfg.CM_Get_Device_Interface_ListW(c.byref(g),None,buf,n.value,0)
    if rc: raise OSError(rc,"CM_Get_Device_Interface_ListW")
    return [x for x in buf[:].split("\0") if x]

def inspect_path(path:str, api=None)->HidInterface:
    if api is not None:return api.inspect_path(path)
    k=c.WinDLL("kernel32",use_last_error=True);h=c.WinDLL("hid",use_last_error=True)
    k.CreateFileW.restype=w.HANDLE;k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    handle=k.CreateFileW(path,0x80000000,3,None,3,0,None)
    if handle==w.HANDLE(-1).value: raise OSError(c.get_last_error(),"read-only HID CreateFile")
    prep=c.c_void_p();attr=_ATTR(c.sizeof(_ATTR));caps=_CAPS()
    try:
        if not h.HidD_GetAttributes(handle,c.byref(attr)): raise OSError(c.get_last_error(),"HidD_GetAttributes")
        if not h.HidD_GetPreparsedData(handle,c.byref(prep)): raise OSError(c.get_last_error(),"HidD_GetPreparsedData")
        if h.HidP_GetCaps(prep,c.byref(caps))<0: raise OSError("HidP_GetCaps")
        return HidInterface(path,attr.VendorID,attr.ProductID,attr.VersionNumber,caps.InputReportByteLength,caps.OutputReportByteLength)
    finally:
        if prep:h.HidD_FreePreparsedData(prep)
        k.CloseHandle(handle)

def discover_5302(api=None)->HidInterface:
    matches=[]
    for path in enumerate_paths(api):
        if "vid_0416&pid_5302&mi_00" not in path.lower():continue
        info=inspect_path(path,api)
        if (info.vid,info.pid)==(0x0416,0x5302):matches.append(info)
    if len(matches)!=1:raise RuntimeError(f"expected one exact PID 5302 MI_00 HID interface, found {len(matches)}")
    return matches[0]


class WindowsHidApi(Protocol):
    def open(self,path:str): ...
    def write_report(self,handle,data:bytes,timeout_ms:int)->int: ...
    def read_report(self,handle,length:int,timeout_ms:int)->bytes: ...
    def cancel(self,handle)->None: ...
    def close(self,handle)->None: ...


class CtypesWindowsHidApi:
    """Overlapped HID boundary. Construction and discovery never open for output."""
    def __init__(self):
        if not hasattr(c,"WinDLL"):raise OSError("Windows HID transport requires Windows")
        self.k=c.WinDLL("kernel32",use_last_error=True)
        self.k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        self.k.CreateFileW.restype=w.HANDLE
        self.k.CreateEventW.argtypes=[c.c_void_p,w.BOOL,w.BOOL,w.LPCWSTR];self.k.CreateEventW.restype=w.HANDLE
        self.k.ResetEvent.argtypes=[w.HANDLE];self.k.ResetEvent.restype=w.BOOL
        self.k.WriteFile.argtypes=[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.POINTER(_OVERLAPPED)];self.k.WriteFile.restype=w.BOOL
        self.k.ReadFile.argtypes=[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.POINTER(_OVERLAPPED)];self.k.ReadFile.restype=w.BOOL
        self.k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];self.k.WaitForSingleObject.restype=w.DWORD
        self.k.GetOverlappedResult.argtypes=[w.HANDLE,c.POINTER(_OVERLAPPED),c.POINTER(w.DWORD),w.BOOL];self.k.GetOverlappedResult.restype=w.BOOL
        self.k.CancelIoEx.argtypes=[w.HANDLE,c.POINTER(_OVERLAPPED)];self.k.CancelIoEx.restype=w.BOOL
        self.k.CloseHandle.argtypes=[w.HANDLE];self.k.CloseHandle.restype=w.BOOL
        self._events={};self._write_buffers={};self._read_buffers={}
    def open(self,path):
        handle=self.k.CreateFileW(path,0xC0000000,3,None,3,FILE_FLAG_OVERLAPPED,None)
        if handle==INVALID_HANDLE_VALUE:raise TransportError(f"HID CreateFile failed: {c.get_last_error()}")
        return handle
    def _io(self,handle,data_or_length,timeout_ms,write):
        event=self._events.get(handle)
        if not event:
            event=self.k.CreateEventW(None,True,False,None)
            if not event:raise TransportError(f"CreateEvent failed: {c.get_last_error()}")
            self._events[handle]=event
        elif not self.k.ResetEvent(event):raise TransportError(f"ResetEvent failed: {c.get_last_error()}")
        ov=_OVERLAPPED();ov.hEvent=event;n=w.DWORD()
        if write:
            size=len(data_or_length);buf=self._write_buffers.get(size)
            if buf is None:buf=c.create_string_buffer(size);self._write_buffers[size]=buf
            c.memmove(buf,data_or_length,size);ok=self.k.WriteFile(handle,buf,size,c.byref(n),c.byref(ov))
        else:
            buf=self._read_buffers.get(data_or_length)
            if buf is None:buf=c.create_string_buffer(data_or_length);self._read_buffers[data_or_length]=buf
            ok=self.k.ReadFile(handle,buf,data_or_length,c.byref(n),c.byref(ov))
        try:
            if not ok and c.get_last_error()!=ERROR_IO_PENDING:self._raise_io("WriteFile" if write else "ReadFile")
            wait=self.k.WaitForSingleObject(event,timeout_ms)
            if wait==258:
                self.k.CancelIoEx(handle,c.byref(ov));self.k.WaitForSingleObject(event,1000)
                raise TransportTimeout("HID transfer timeout")
            if wait!=0:raise TransportError(f"HID wait failed: {wait}")
            if not self.k.GetOverlappedResult(handle,c.byref(ov),c.byref(n),False):self._raise_io("GetOverlappedResult")
            return n.value if write else buf.raw[:n.value]
        finally:pass
    def _raise_io(self,operation):
        code=c.get_last_error()
        if code==ERROR_OPERATION_ABORTED:raise TransportTimeout(f"{operation} cancelled")
        if code==ERROR_DEVICE_NOT_CONNECTED:raise DeviceDisconnected(f"{operation}: device disconnected")
        raise TransportError(f"{operation} failed: {code}")
    def write_report(self,handle,data,timeout_ms):return self._io(handle,data,timeout_ms,True)
    def read_report(self,handle,length,timeout_ms):return self._io(handle,length,timeout_ms,False)
    def cancel(self,handle):
        if handle not in (None,INVALID_HANDLE_VALUE):self.k.CancelIoEx(handle,None)
    def close(self,handle):
        if handle not in (None,INVALID_HANDLE_VALUE):
            event=self._events.pop(handle,None)
            if event:self.k.CloseHandle(event)
            self.k.CloseHandle(handle)


class RealHidTransport(UsbTransport):
    """Exact PID 5302 HID report transport; report ID zero is added/removed here."""
    def __init__(self,target:dict,identity_supplier,api:WindowsHidApi,write_budget_count:int,write_budget_bytes:int):
        self.target=target;self.identity_supplier=identity_supplier;self.api=api
        self.identity=None;self.handle=None;self._generation=None
        self.write_budget_count=write_budget_count;self.write_budget_bytes=write_budget_bytes
        self.write_count=0;self.write_bytes=0;self.hardware_ever_opened=False;self.hardware_write_calls=0
    def discover(self):
        d=self.identity_supplier()
        if not d.device_path or "vid_0416&pid_5302&mi_00" not in d.device_path.lower():raise SafetyError("exact PID 5302 MI_00 HID path required")
        self.identity=d;return d
    def open(self,timeout_ms):
        if not self.identity:raise SafetyError("discover/validate before open")
        self.handle=self.api.open(self.identity.device_path);self.hardware_ever_opened=True;self._generation=self.identity.generation
    def write(self,endpoint,payload,timeout_ms):
        if self.handle is None:raise DeviceDisconnected("HID handle is not open")
        if endpoint.lower()!=self.target["endpoint"].lower():raise SafetyError("wrong HID logical OUT endpoint")
        if len(payload)!=512:raise SafetyError("PID 5302 requires exact 512-byte reports")
        if self.write_count+1>self.write_budget_count or self.write_bytes+len(payload)>self.write_budget_bytes:raise SafetyError("physical session write budget exceeded")
        self.hardware_write_calls+=1;n=self.api.write_report(self.handle,b"\x00"+payload,timeout_ms)
        if n!=513:raise TransportError("short HID write")
        self.write_count+=1;self.write_bytes+=len(payload);return len(payload)
    def read(self,endpoint,length,timeout_ms):
        if self.handle is None:raise DeviceDisconnected("HID handle is not open")
        if endpoint.lower()!=self.target["response_endpoint"].lower():raise SafetyError("wrong HID logical IN endpoint")
        raw=self.api.read_report(self.handle,length+1,timeout_ms)
        if len(raw)!=length+1 or raw[0]!=0:raise TransportError("short or malformed HID read")
        return raw[1:]
    def pending_input(self):return False
    def revalidate(self,expected):
        current=self.identity_supplier();validate_identity(current,expected)
        if self._generation is not None and current.generation!=self._generation:raise DeviceReenumerated("device re-enumerated")
    def close(self,timeout_ms):
        handle,self.handle=self.handle,None
        if handle is not None:
            try:self.api.cancel(handle)
            finally:self.api.close(handle)

def discover_hid_identity(target:dict,api=None)->DeviceIdentity:
    """Fresh HID capability discovery plus stable parent/container validation."""
    info=discover_5302(api)
    if info.input_report_bytes!=target["hid_input_report_bytes"] or info.output_report_bytes!=target["hid_output_report_bytes"]:
        raise SafetyError("HID report capability mismatch")
    sid=target["stable_instance_id"].replace("'","''")
    script=(f"$d=Get-PnpDevice -InstanceId '{sid}' -ErrorAction Stop;$p=Get-PnpDeviceProperty -InstanceId '{sid}';"
            "$o=[ordered]@{status=$d.Status;container_id=($p|? KeyName -eq 'DEVPKEY_Device_ContainerId').Data;"
            "location=(($p|? KeyName -eq 'DEVPKEY_Device_LocationPaths').Data -join '|')};$o|ConvertTo-Json -Compress")
    cp=subprocess.run(["powershell","-NoProfile","-Command",script],capture_output=True,text=True,timeout=5,**hidden_subprocess_kwargs())
    if cp.returncode:raise DeviceDisconnected("PID 5302 stable parent is not present")
    pnp=json.loads(cp.stdout)
    if pnp.get("status")!="OK" or str(pnp.get("container_id","")).lower()!=target["container_id"].lower():
        raise SafetyError("PID 5302 stable identity/container mismatch")
    if info.path.lower()!=target["confirmed_device_path"].lower():raise SafetyError("PID 5302 HID path changed")
    return DeviceIdentity(target["vid_pid"],target["stable_instance_id"],pnp["container_id"],target["interface"],
                          target["endpoint"],target["response_endpoint"],target["transfer_type"],"HIDUSB",
                          f"{pnp['container_id']}|{pnp.get('location')}|{info.path}",info.path,target["host_payload_size"])

def materialize_reviewed_hid_target(definition:dict,api=None)->dict:
    """Bind the reviewed 5302 definition to one exact MI_00 HID interface."""
    if definition.get("vid_pid")!="0416:5302":raise SafetyError("unsupported reviewed HID definition")
    info=discover_5302(api)
    if info.input_report_bytes!=definition["hid_input_report_bytes"] or info.output_report_bytes!=definition["hid_output_report_bytes"]:raise SafetyError("PID 5302 HID report capability mismatch")
    script=("$ds=@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\\\VID_0416&PID_5302\\\\' });"
            "$items=@();foreach($d in $ds){$p=Get-PnpDeviceProperty -InstanceId $d.InstanceId;"
            "$items+=@([ordered]@{status=$d.Status;instance_id=$d.InstanceId;container_id=($p|? KeyName -eq 'DEVPKEY_Device_ContainerId').Data})};"
            "[ordered]@{count=$items.Count;items=$items}|ConvertTo-Json -Compress -Depth 4")
    cp=subprocess.run(["powershell","-NoProfile","-Command",script],capture_output=True,text=True,timeout=5,**hidden_subprocess_kwargs())
    if cp.returncode:raise DeviceDisconnected("reviewed PID 5302 parent is not present")
    result=json.loads(cp.stdout);items=result.get("items") or []
    if isinstance(items,dict):items=[items]
    if result.get("count")!=1:raise SafetyError(f"expected one reviewed PID 5302 parent, found {result.get('count',0)}")
    item=items[0]
    if item.get("status")!="OK":raise SafetyError("PID 5302 parent status is not OK")
    target=deepcopy(definition);target.update(stable_instance_id=item["instance_id"],interface_instance_id=item["instance_id"],container_id=str(item.get("container_id") or ""),confirmed_device_path=info.path)
    if not target["container_id"]:raise SafetyError("PID 5302 container identity is unavailable")
    actual=discover_hid_identity(target,api);validate_identity(actual,expected_identity(target));return target

def read_only_hid_capture_probe(vid:int,pid:int,timeout_ms:int=100)->dict:
    """Post input-only HID requests; never obtains output access."""
    matches=[]
    for path in enumerate_paths():
        try:
            info=inspect_path(path)
            if (info.vid,info.pid)==(vid,pid):matches.append(info)
        except OSError:pass
    if not matches:raise RuntimeError(f"no HID path for {vid:04x}:{pid:04x}")
    info=matches[0];k=c.WinDLL("kernel32",use_last_error=True);hid=c.WinDLL("hid",use_last_error=True)
    k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE];k.CreateFileW.restype=w.HANDLE
    k.CreateEventW.argtypes=[c.c_void_p,w.BOOL,w.BOOL,w.LPCWSTR];k.CreateEventW.restype=w.HANDLE
    k.ReadFile.argtypes=[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.POINTER(_OVERLAPPED)];k.ReadFile.restype=w.BOOL
    k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.WaitForSingleObject.restype=w.DWORD
    k.CancelIoEx.argtypes=[w.HANDLE,c.POINTER(_OVERLAPPED)];k.CancelIoEx.restype=w.BOOL
    k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
    handle=k.CreateFileW(info.path,0x80000000,3,None,3,FILE_FLAG_OVERLAPPED,None)
    if handle==INVALID_HANDLE_VALUE:raise OSError(c.get_last_error(),"read-only HID capture probe open")
    event=k.CreateEventW(None,True,False,None);ov=_OVERLAPPED();ov.hEvent=event;n=w.DWORD();buf=c.create_string_buffer(info.input_report_bytes)
    try:
        # HID class GET_REPORT is device-to-host only and supplies timed,
        # ordinary USB control traffic for recorder validation.
        get_report=bool(hid.HidD_GetInputReport(handle,buf,len(buf)))
        ok=k.ReadFile(handle,buf,len(buf),c.byref(n),c.byref(ov));pending=(not ok and c.get_last_error()==ERROR_IO_PENDING)
        wait=k.WaitForSingleObject(event,timeout_ms)
        if pending and wait==258:k.CancelIoEx(handle,c.byref(ov));k.WaitForSingleObject(event,1000)
        return {"vid_pid":f"{vid:04x}:{pid:04x}","access":"GENERIC_READ","output_access":False,"write_calls":0,"input_report_bytes":info.input_report_bytes,
                "get_input_report_result":get_report,"wait_result":int(wait)}
    finally:
        if event:k.CloseHandle(event)
        k.CloseHandle(handle)

def read_only_capture_probe_5302(timeout_ms:int=100)->dict:
    return read_only_hid_capture_probe(0x0416,0x5302,timeout_ms)

def read_only_hid_report_scan(vid:int,pid:int)->dict:
    """Try all input report IDs with device-to-host GET_REPORT only."""
    infos=[]
    for path in enumerate_paths():
        try:
            info=inspect_path(path)
            if (info.vid,info.pid)==(vid,pid) and info.input_report_bytes>0:infos.append(info)
        except OSError:pass
    if not infos:raise RuntimeError(f"no HID input path for {vid:04x}:{pid:04x}")
    hid=c.WinDLL("hid",use_last_error=True);k=c.WinDLL("kernel32",use_last_error=True)
    k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE];k.CreateFileW.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
    successes=0;requests=0
    for info in infos:
        handle=k.CreateFileW(info.path,0x80000000,3,None,3,0,None)
        if handle==INVALID_HANDLE_VALUE:continue
        try:
            for report_id in range(256):
                buf=c.create_string_buffer(info.input_report_bytes);buf[0]=bytes([report_id]);requests+=1
                successes+=int(bool(hid.HidD_GetInputReport(handle,buf,len(buf))))
        finally:k.CloseHandle(handle)
    return {"vid_pid":f"{vid:04x}:{pid:04x}","access":"GENERIC_READ","output_access":False,"write_calls":0,
            "input_get_report_requests":requests,"successful_reports":successes}
