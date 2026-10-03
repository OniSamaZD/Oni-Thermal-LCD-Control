from __future__ import annotations

from dataclasses import dataclass
import ctypes as c
from ctypes import wintypes as w
import json
import os
import re
import uuid

from .live_state import DeviceDisconnected, SafetyError


@dataclass(frozen=True, slots=True)
class WindowsDeviceMetadata:
    instance_id: str
    status: str
    container_id: str
    service: str
    location: str
    parent: str
    hardware_ids: tuple[str, ...]
    compatible_ids: tuple[str, ...]
    class_name: str
    driver_inf: str = ""
    manufacturer: str = ""
    description: str = ""

    @property
    def vid_pid(self) -> str:
        match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", self.instance_id, re.I)
        return f"{match.group(1)}:{match.group(2)}".lower() if match else ""


@dataclass(frozen=True, slots=True)
class WindowsMetadataSnapshot:
    """Immutable PnP metadata valid for exactly one discovery transaction."""

    devices: tuple[WindowsDeviceMetadata, ...]

    def exact(self, instance_id: str) -> WindowsDeviceMetadata:
        matches = tuple(item for item in self.devices if item.instance_id.casefold() == instance_id.casefold())
        if len(matches) != 1:
            raise DeviceDisconnected(f"PnP identity is not uniquely present: {instance_id}")
        return matches[0]

    def for_vid_pid(self, vid_pid: str) -> tuple[WindowsDeviceMetadata, ...]:
        return tuple(item for item in self.devices if item.vid_pid == vid_pid.casefold())

    def physical_roots(self, vid_pid: str) -> tuple[WindowsDeviceMetadata, ...]:
        vid, pid = vid_pid.split(":")
        pattern = re.compile(rf"^USB\\VID_{re.escape(vid)}&PID_{re.escape(pid)}\\", re.I)
        return tuple(item for item in self.devices if pattern.match(item.instance_id))


def _strings(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise SafetyError("malformed PnP string-list property")
    return tuple(str(item) for item in value)


def parse_windows_metadata_snapshot(payload: str) -> WindowsMetadataSnapshot:
    try:
        raw = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise SafetyError("malformed Windows PnP metadata snapshot") from exc
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise SafetyError("malformed Windows PnP metadata snapshot")
    devices = []
    seen = set()
    for value in raw:
        if not isinstance(value, dict):
            raise SafetyError("malformed Windows PnP metadata record")
        instance_id = str(value.get("instance_id") or "").strip()
        status = str(value.get("status") or "").strip()
        container_id = str(value.get("container_id") or "").strip()
        if not instance_id or not status:
            raise SafetyError("incomplete Windows PnP metadata record")
        key = instance_id.casefold()
        if key in seen:
            raise SafetyError(f"ambiguous duplicate PnP identity: {instance_id}")
        seen.add(key)
        devices.append(WindowsDeviceMetadata(
            instance_id=instance_id,
            status=status,
            container_id=container_id,
            service=str(value.get("service") or "").strip(),
            location=str(value.get("location") or "").strip(),
            parent=str(value.get("parent") or "").strip(),
            hardware_ids=_strings(value.get("hardware_ids")),
            compatible_ids=_strings(value.get("compatible_ids")),
            class_name=str(value.get("class_name") or "").strip(),
            driver_inf=str(value.get("driver_inf") or "").strip(),
            manufacturer=str(value.get("manufacturer") or "").strip(),
            description=str(value.get("description") or "").strip(),
        ))
    return WindowsMetadataSnapshot(tuple(devices))


class GUID(c.Structure):
    _fields_ = (("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", c.c_ubyte * 8))

    @classmethod
    def parse(cls, value: str):
        raw = uuid.UUID(value.strip("{}"))
        return cls.from_buffer_copy(raw.bytes_le)

    def text(self) -> str:
        return "{" + str(uuid.UUID(bytes_le=bytes(self))).upper() + "}"


class DEVPROPKEY(c.Structure):
    _fields_ = (("fmtid", GUID), ("pid", w.DWORD))


class SP_DEVINFO_DATA(c.Structure):
    _fields_ = (("cbSize", w.DWORD), ("ClassGuid", GUID), ("DevInst", w.DWORD), ("Reserved", c.c_void_p))


class SP_DEVICE_INTERFACE_DATA(c.Structure):
    _fields_ = (("cbSize", w.DWORD), ("InterfaceClassGuid", GUID), ("Flags", w.DWORD), ("Reserved", c.c_void_p))


def _key(guid: str, pid: int) -> DEVPROPKEY:
    return DEVPROPKEY(GUID.parse(guid), pid)


_DEVICE_KEY = "{A45C254E-DF1C-4EFD-8020-67D146A850E0}"
_KEYS = {
    "hardware_ids": _key(_DEVICE_KEY, 3),
    "compatible_ids": _key(_DEVICE_KEY, 4),
    "service": _key(_DEVICE_KEY, 6),
    "class_name": _key(_DEVICE_KEY, 9),
    "location_paths": _key(_DEVICE_KEY, 37),
    "parent": _key("{4340A6C5-93FA-4706-972C-7B648008A5A7}", 8),
    "container_id": _key("{8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C}", 2),
    "bus_reported_desc": _key("{540B947E-8B40-45BC-A8A2-6A0B894CBDA2}", 4),
    "manufacturer": _key(_DEVICE_KEY, 13),
    "driver_inf": _key("{A8B865DD-2E3D-4094-AD97-E593A70C75D6}", 5),
}
_DEVPROP_TYPE_GUID = 0x0D
_DEVPROP_TYPE_STRING = 0x12
_DEVPROP_TYPE_STRING_LIST = 0x2012
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_NO_MORE_ITEMS = 259
_ERROR_NOT_FOUND = 1168
_DIGCF_PRESENT = 0x2
_DIGCF_ALLCLASSES = 0x4
_DIGCF_DEVICEINTERFACE = 0x10
_DISK_INTERFACE_GUID = "{53F56307-B6BF-11D0-94F2-00A0C91EFB8B}"
_IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080


def _decode_device_property(raw: bytes, kind: int):
    if kind == _DEVPROP_TYPE_GUID:
        if len(raw) < c.sizeof(GUID): raise ValueError("short GUID device property")
        return GUID.from_buffer_copy(raw[:c.sizeof(GUID)]).text()
    if kind in (_DEVPROP_TYPE_STRING, _DEVPROP_TYPE_STRING_LIST):
        text = raw.decode("utf-16-le", "strict").rstrip("\0")
        values = tuple(item for item in text.split("\0") if item)
        return values if kind == _DEVPROP_TYPE_STRING_LIST else (values[0] if values else "")
    raise ValueError(f"unsupported device property type: 0x{kind:x}")


class CtypesWindowsMetadataApi:
    """Small SetupAPI/Configuration Manager surface used by one scan."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("native Windows metadata is available only on Windows")
        self.setup = c.WinDLL("setupapi", use_last_error=True)
        self.cfg = c.WinDLL("cfgmgr32", use_last_error=True)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.setup.SetupDiGetClassDevsW.restype = c.c_void_p
        self.setup.SetupDiGetClassDevsW.argtypes = (c.POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD)
        self.setup.SetupDiEnumDeviceInfo.argtypes = (c.c_void_p, w.DWORD, c.POINTER(SP_DEVINFO_DATA))
        self.setup.SetupDiGetDeviceInstanceIdW.argtypes = (c.c_void_p, c.POINTER(SP_DEVINFO_DATA), w.LPWSTR, w.DWORD, c.POINTER(w.DWORD))
        self.setup.SetupDiGetDevicePropertyW.argtypes = (c.c_void_p, c.POINTER(SP_DEVINFO_DATA), c.POINTER(DEVPROPKEY), c.POINTER(w.ULONG), c.c_void_p, w.DWORD, c.POINTER(w.DWORD), w.DWORD)
        self.setup.SetupDiEnumDeviceInterfaces.argtypes = (c.c_void_p, c.POINTER(SP_DEVINFO_DATA), c.POINTER(GUID), w.DWORD, c.POINTER(SP_DEVICE_INTERFACE_DATA))
        self.setup.SetupDiGetDeviceInterfaceDetailW.argtypes = (c.c_void_p, c.POINTER(SP_DEVICE_INTERFACE_DATA), c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(SP_DEVINFO_DATA))
        self.setup.SetupDiDestroyDeviceInfoList.argtypes = (c.c_void_p,)
        self.setup.SetupDiGetDevicePropertyW.restype = w.BOOL
        self.setup.SetupDiGetDeviceInstanceIdW.restype = w.BOOL
        self.setup.SetupDiGetDeviceInterfaceDetailW.restype = w.BOOL
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE)
        self.kernel.DeviceIoControl.argtypes = (w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p)

    @staticmethod
    def _info() -> SP_DEVINFO_DATA:
        value = SP_DEVINFO_DATA(); value.cbSize = c.sizeof(value); return value

    def _instance_id(self, info: SP_DEVINFO_DATA) -> str:
        needed = w.DWORD()
        self.setup.SetupDiGetDeviceInstanceIdW(self._set, c.byref(info), None, 0, c.byref(needed))
        if c.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or needed.value < 2:
            raise OSError(c.get_last_error(), "SetupDiGetDeviceInstanceIdW(size)")
        buffer = c.create_unicode_buffer(needed.value)
        if not self.setup.SetupDiGetDeviceInstanceIdW(self._set, c.byref(info), buffer, needed.value, None):
            raise OSError(c.get_last_error(), "SetupDiGetDeviceInstanceIdW")
        return buffer.value

    def _property(self, info: SP_DEVINFO_DATA, key: DEVPROPKEY):
        kind = w.ULONG(); needed = w.DWORD()
        self.setup.SetupDiGetDevicePropertyW(self._set, c.byref(info), c.byref(key), c.byref(kind), None, 0, c.byref(needed), 0)
        error = c.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return None
        if error != _ERROR_INSUFFICIENT_BUFFER or not needed.value:
            raise OSError(error, "SetupDiGetDevicePropertyW(size)")
        buffer = (c.c_ubyte * needed.value)()
        if not self.setup.SetupDiGetDevicePropertyW(self._set, c.byref(info), c.byref(key), c.byref(kind), buffer, needed.value, None, 0):
            raise OSError(c.get_last_error(), "SetupDiGetDevicePropertyW")
        return _decode_device_property(bytes(buffer), kind.value)

    def _status(self, devinst: int) -> str:
        status = w.ULONG(); problem = w.ULONG()
        result = self.cfg.CM_Get_DevNode_Status(c.byref(status), c.byref(problem), devinst, 0)
        if result != 0: raise OSError(result, "CM_Get_DevNode_Status")
        return "OK" if problem.value == 0 else "Error"

    def _device_record(self, info: SP_DEVINFO_DATA) -> dict:
        instance_id = self._instance_id(info)
        values = {name: self._property(info, key) for name, key in _KEYS.items()}
        locations = values.get("location_paths") or ()
        if isinstance(locations, str): locations = (locations,)
        return {"instance_id": instance_id, "status": self._status(info.DevInst),
                "container_id": values.get("container_id") or "", "service": values.get("service") or "",
                "location": "|".join(locations), "parent": values.get("parent") or "",
                "hardware_ids": list(values.get("hardware_ids") or ()),
                "compatible_ids": list(values.get("compatible_ids") or ()), "class_name": values.get("class_name") or "",
                "driver_inf": values.get("driver_inf") or "", "manufacturer": values.get("manufacturer") or "",
                "description": values.get("bus_reported_desc") or ""}

    def enumerate_present_devices(self) -> tuple[dict, ...]:
        return self._enumerate_present(False)

    def enumerate_present_usb_devices(self) -> tuple[dict, ...]:
        """Broad USB identity snapshot for an explicit diagnostic scan only."""
        return self._enumerate_present(True)

    def _enumerate_present(self, diagnostic_candidates: bool) -> tuple[dict, ...]:
        self._set = self.setup.SetupDiGetClassDevsW(None, None, None, _DIGCF_PRESENT | _DIGCF_ALLCLASSES)
        if self._set == c.c_void_p(-1).value: raise OSError(c.get_last_error(), "SetupDiGetClassDevsW")
        try:
            output=[]; index=0
            while True:
                info=self._info()
                if not self.setup.SetupDiEnumDeviceInfo(self._set, index, c.byref(info)):
                    if c.get_last_error()==_ERROR_NO_MORE_ITEMS:break
                    raise OSError(c.get_last_error(), "SetupDiEnumDeviceInfo")
                index+=1
                instance=self._instance_id(info)
                known=re.search(r"VID_(0416|87AD|87CD|0402)&PID_(5302|5408|70DB|5409|5406|3922)",instance,re.I)
                if known or (diagnostic_candidates and re.search(r"^(?:USB|HID)\\.*VID_[0-9A-F]{4}&PID_[0-9A-F]{4}",instance,re.I)):
                    output.append(self._device_record(info))
            return tuple(output)
        finally:
            self.setup.SetupDiDestroyDeviceInfoList(self._set); self._set=None

    def _ancestor_ids(self, devinst: int) -> tuple[str, ...]:
        output=[]; current=w.DWORD(devinst)
        for _ in range(16):
            size=w.ULONG()
            if self.cfg.CM_Get_Device_ID_Size(c.byref(size), current.value, 0)!=0:break
            buffer=c.create_unicode_buffer(size.value+1)
            if self.cfg.CM_Get_Device_IDW(current.value, buffer, size.value+1, 0)!=0:break
            output.append(buffer.value)
            parent=w.DWORD()
            if self.cfg.CM_Get_Parent(c.byref(parent), current.value, 0)!=0:break
            current=parent
        return tuple(output)

    def _disk_number(self, interface_path: str) -> int:
        handle=self.kernel.CreateFileW(interface_path,0,3,None,3,0,None)
        if handle==c.c_void_p(-1).value:raise OSError(c.get_last_error(),"disk interface CreateFileW")
        try:
            data=(w.DWORD*3)();returned=w.DWORD()
            if not self.kernel.DeviceIoControl(handle,_IOCTL_STORAGE_GET_DEVICE_NUMBER,None,0,c.byref(data),c.sizeof(data),c.byref(returned),None):
                raise OSError(c.get_last_error(),"IOCTL_STORAGE_GET_DEVICE_NUMBER")
            return int(data[1])
        finally:self.kernel.CloseHandle(handle)

    def enumerate_disk_interfaces(self) -> tuple[dict, ...]:
        guid=GUID.parse(_DISK_INTERFACE_GUID)
        self._set=self.setup.SetupDiGetClassDevsW(c.byref(guid),None,None,_DIGCF_PRESENT|_DIGCF_DEVICEINTERFACE)
        if self._set==c.c_void_p(-1).value:raise OSError(c.get_last_error(),"SetupDiGetClassDevsW(disk)")
        try:
            output=[];index=0
            while True:
                interface=SP_DEVICE_INTERFACE_DATA();interface.cbSize=c.sizeof(interface)
                if not self.setup.SetupDiEnumDeviceInterfaces(self._set,None,c.byref(guid),index,c.byref(interface)):
                    if c.get_last_error()==_ERROR_NO_MORE_ITEMS:break
                    raise OSError(c.get_last_error(),"SetupDiEnumDeviceInterfaces")
                index+=1;needed=w.DWORD();info=self._info()
                self.setup.SetupDiGetDeviceInterfaceDetailW(self._set,c.byref(interface),None,0,c.byref(needed),c.byref(info))
                if c.get_last_error()!=_ERROR_INSUFFICIENT_BUFFER:raise OSError(c.get_last_error(),"SetupDiGetDeviceInterfaceDetailW(size)")
                detail=c.create_string_buffer(needed.value);c.cast(detail,c.POINTER(w.DWORD))[0]=8 if c.sizeof(c.c_void_p)==8 else 6
                if not self.setup.SetupDiGetDeviceInterfaceDetailW(self._set,c.byref(interface),detail,needed.value,None,c.byref(info)):
                    raise OSError(c.get_last_error(),"SetupDiGetDeviceInterfaceDetailW")
                path=c.wstring_at(c.addressof(detail)+4);ancestors=self._ancestor_ids(info.DevInst)
                identity=next((value for value in ancestors if re.search(r"VID_(87CD|0402|0416)&PID_(70DB|3922|5406)",value,re.I)),"")
                if not identity:continue
                model=self._property(info,_KEYS["bus_reported_desc"]) or self._instance_id(info)
                output.append({"path":rf"\\.\PhysicalDrive{self._disk_number(path)}","pnp":identity,"model":model,"status":self._status(info.DevInst)})
            return tuple(output)
        finally:self.setup.SetupDiDestroyDeviceInfoList(self._set);self._set=None


def _snapshot_from_records(records) -> WindowsMetadataSnapshot:
    return parse_windows_metadata_snapshot(json.dumps(list(records)))


def collect_windows_metadata_snapshot(api=None, *, diagnostic_candidates: bool = False) -> WindowsMetadataSnapshot:
    """Collect a fresh immutable native snapshot for one discovery transaction."""
    try:
        native=api or CtypesWindowsMetadataApi()
        method=native.enumerate_present_usb_devices if diagnostic_candidates and hasattr(native,"enumerate_present_usb_devices") else native.enumerate_present_devices
        return _snapshot_from_records(method())
    except SafetyError:
        raise
    except (OSError, ValueError, UnicodeError) as exc:
        raise DeviceDisconnected("native Windows PnP metadata snapshot failed") from exc
