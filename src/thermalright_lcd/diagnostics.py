"""Read-only community display diagnostics and portable support packages.

This module intentionally has no dependency on output transports.  SafeScanner
accepts metadata/descriptor readers only; it cannot initialize a protocol,
write a report/pipe/serial port, reset a device, or create an output session.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
from typing import Callable, Iterable, Mapping
import zipfile
import ctypes
from ctypes import wintypes

from .devices.catalog import catalog_models
from .windows_metadata import WindowsDeviceMetadata, WindowsMetadataSnapshot, collect_windows_metadata_snapshot

SCHEMA_VERSION = "oni-support-package/1"
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_MEMBERS = 8


class Evidence(str, Enum):
    OBSERVED_WINDOWS = "OBSERVED_WINDOWS"
    OBSERVED_DESCRIPTOR = "OBSERVED_DESCRIPTOR"
    CATALOG_REFERENCE = "CATALOG_REFERENCE"
    USER_SUPPLIED = "USER_SUPPLIED"
    UNKNOWN = "UNKNOWN"


class MatchState(str, Enum):
    EXACT_IDENTITY_MATCH = "EXACT_IDENTITY_MATCH"
    POSSIBLE_FAMILY_MATCH = "POSSIBLE_FAMILY_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ObservedValue:
    value: object
    provenance: Evidence


@dataclass(frozen=True, slots=True)
class EndpointFingerprint:
    address: int
    direction: str
    transfer_type: str
    maximum_packet_size: int | None = None


@dataclass(frozen=True, slots=True)
class InterfaceFingerprint:
    instance_id: str = ""
    path: str = ""
    guid: str = ""
    number: int | None = None
    class_code: int | None = None
    subclass: int | None = None
    protocol: int | None = None
    transport: str = "unknown"
    endpoints: tuple[EndpointFingerprint, ...] = ()
    usage_page: int | None = None
    usage: int | None = None
    input_report_length: int | None = None
    output_report_length: int | None = None
    feature_report_length: int | None = None
    report_ids: tuple[int, ...] = ()
    access_error: str = ""


@dataclass(frozen=True, slots=True)
class HardwareFingerprint:
    vid: int
    pid: int
    revision: int | None
    instance_id: str
    hardware_ids: tuple[str, ...]
    compatible_ids: tuple[str, ...]
    parent_instance_id: str
    container_id: str
    class_name: str
    service: str
    driver_inf: str
    manufacturer: str
    description: str
    location: str
    transport_types: tuple[str, ...]
    interfaces: tuple[InterfaceFingerprint, ...]
    provenance: Mapping[str, str] = field(default_factory=dict)
    child_instance_ids: tuple[str, ...] = ()

    @property
    def vid_pid(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    def protocol_identity(self) -> dict:
        """Stable identity fields only; excludes paths, serials, ports and GUIDs."""
        return {
            "vid_pid": self.vid_pid,
            "revision": self.revision,
            "service": self.service.casefold(),
            "transports": list(self.transport_types),
            "interfaces": [{
                "number": item.number, "class": item.class_code,
                "subclass": item.subclass, "protocol": item.protocol,
                "transport": item.transport,
                "endpoints": [asdict(ep) for ep in item.endpoints],
                "usage_page": item.usage_page, "usage": item.usage,
                "input_report_length": item.input_report_length,
                "output_report_length": item.output_report_length,
                "feature_report_length": item.feature_report_length,
            } for item in self.interfaces],
        }

    def deterministic_id(self) -> str:
        raw = json.dumps(self.protocol_identity(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CatalogMatch:
    state: MatchState
    candidates: tuple[str, ...]
    support_statuses: tuple[str, ...]
    possible_protocol_families: tuple[str, ...]
    protocol_verification: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScanResult:
    fingerprint: HardwareFingerprint
    match: CatalogMatch
    warnings: tuple[str, ...] = ()


_KNOWN_VENDORS = {0x0416, 0x87AD, 0x87CD, 0x0402, 0x0418, 0x4E58, 0x33C3, 0x264A, 0x26CE, 0x1CBE, 0x345F, 0x1A86, 0x1908}
_EXCLUDED_CLASSES = {"keyboard", "mouse", "camera", "audioendpoint", "media", "biometric", "bluetooth"}


def _identity(instance_id: str) -> tuple[int, int, int | None] | None:
    match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})(?:&REV_([0-9A-F]{4}))?", instance_id, re.I)
    if not match:
        return None
    return int(match[1], 16), int(match[2], 16), int(match[3], 16) if match[3] else None


def _mi(instance_id: str) -> int | None:
    match = re.search(r"&MI_([0-9A-F]{2})", instance_id, re.I)
    return int(match[1], 16) if match else None


def _transport(record: WindowsDeviceMetadata) -> str:
    service, cls = record.service.casefold(), record.class_name.casefold()
    if "hid" in service or cls == "hidclass": return "hid"
    if "winusb" in service: return "winusb"
    if cls in {"ports", "modem"} or "usbser" in service: return "serial"
    if cls in {"diskdrive", "scsiadapter"} or "usbstor" in service: return "mass-storage/scsi"
    if cls == "usb" or "usb" in service: return "generic-usb"
    return "unknown"


def _candidate(record: WindowsDeviceMetadata, catalog_ids: set[str]) -> bool:
    ident = _identity(record.instance_id)
    if not ident or record.class_name.casefold() in _EXCLUDED_CLASSES:
        return False
    if "billboard" in " ".join((record.description, record.manufacturer)).casefold():
        return False
    vid_pid = f"{ident[0]:04x}:{ident[1]:04x}"
    known = vid_pid in catalog_ids or ident[0] in _KNOWN_VENDORS
    display_hint = any(token in " ".join((record.class_name, record.service, record.description, record.manufacturer)).casefold()
                       for token in ("display", "lcd", "winusb", "usbdk"))
    return known or display_hint


def match_catalog(fingerprint: HardwareFingerprint) -> CatalogMatch:
    matches = tuple(model for model in catalog_models() if fingerprint.vid_pid in {value.casefold() for value in model.identifiers})
    if not matches:
        return CatalogMatch(MatchState.UNKNOWN, (), (), (), "REQUIRED", ("No catalog identity matched.",))
    keys = tuple(model.key for model in matches)
    statuses = tuple(dict.fromkeys(model.status for model in matches))
    protocols = tuple(dict.fromkeys(model.connection_type.casefold() for model in matches))
    verified = tuple(model for model in matches if model.status.casefold() == "verified")
    if len(matches) == 1 and len(verified) == 1:
        state, verification = MatchState.EXACT_IDENTITY_MATCH, "VERIFIED_BY_EXISTING_ONI_EVIDENCE"
    elif len(matches) == 1:
        state, verification = MatchState.POSSIBLE_FAMILY_MATCH, "REQUIRED"
    elif len({model.family for model in matches}) == 1:
        state, verification = MatchState.POSSIBLE_FAMILY_MATCH, "REQUIRED"
    else:
        state, verification = MatchState.AMBIGUOUS, "REQUIRED"
    return CatalogMatch(state, keys, statuses, protocols, verification,
                        (f"VID/PID {fingerprint.vid_pid} matched {len(matches)} catalog reference(s).",
                         "Catalog identity does not independently prove protocol compatibility."))


class SafeScanner:
    """Explicitly invoked descriptor scanner with no writable dependency surface."""
    def __init__(self, snapshot_supplier: Callable[[], WindowsMetadataSnapshot] | None = None,
                 hid_enumerator: Callable[[], Iterable[str]] | None = None,
                 hid_inspector: Callable[[str], object] | None = None,
                 usb_descriptor_reader: Callable[[WindowsDeviceMetadata], Iterable[InterfaceFingerprint]] | None = None):
        self._snapshot_supplier = snapshot_supplier or (lambda:collect_windows_metadata_snapshot(diagnostic_candidates=True))
        self._hid_enumerator = hid_enumerator
        self._hid_inspector = hid_inspector
        self._usb_descriptor_reader = usb_descriptor_reader

    def candidates(self) -> tuple[WindowsDeviceMetadata, ...]:
        snapshot = self._snapshot_supplier()
        catalog_ids = {identifier.casefold() for model in catalog_models() for identifier in model.identifiers}
        return tuple(item for item in snapshot.devices if _candidate(item, catalog_ids))

    def scan(self, selected_instance_id: str | None = None) -> tuple[ScanResult, ...]:
        snapshot = self._snapshot_supplier(); catalog_ids = {identifier.casefold() for model in catalog_models() for identifier in model.identifiers}
        candidates = tuple(item for item in snapshot.devices if _candidate(item, catalog_ids))
        if selected_instance_id:
            selected = next((item for item in candidates if item.instance_id.casefold() == selected_instance_id.casefold()), None)
            if selected is None: raise ValueError("selected target is not a Safe Scan candidate")
            roots = (selected,)
        else:
            roots = tuple(item for item in candidates if "&mi_" not in item.instance_id.casefold()) or candidates
        results=[]
        for root in roots:
            ident=_identity(root.instance_id)
            if not ident: continue
            revision=ident[2]
            if revision is None:
                revision=next((parsed[2] for value in root.hardware_ids if (parsed:=_identity(value)) and parsed[2] is not None),None)
            members=tuple(item for item in snapshot.devices if item.instance_id.casefold()==root.instance_id.casefold()
                          or (root.container_id and item.container_id.casefold()==root.container_id.casefold())
                          or item.parent.casefold()==root.instance_id.casefold())
            interfaces=[InterfaceFingerprint(instance_id=item.instance_id,number=_mi(item.instance_id),transport=_transport(item))
                        for item in members if item.instance_id.casefold()!=root.instance_id.casefold()]
            warnings=[]
            if self._hid_enumerator and self._hid_inspector:
                for path in self._hid_enumerator():
                    if f"vid_{ident[0]:04x}&pid_{ident[1]:04x}" not in path.casefold(): continue
                    try:
                        info=self._hid_inspector(path)
                        interfaces.append(InterfaceFingerprint(path=path,number=_mi(path),transport="hid",
                            usage_page=getattr(info,"usage_page",None),usage=getattr(info,"usage",None),
                            input_report_length=getattr(info,"input_report_bytes",None),
                            output_report_length=getattr(info,"output_report_bytes",None),
                            feature_report_length=getattr(info,"feature_report_bytes",None)))
                    except (OSError, PermissionError) as exc:
                        interfaces.append(InterfaceFingerprint(path=path,number=_mi(path),transport="hid",access_error=type(exc).__name__))
                        warnings.append(f"HID metadata partial: {type(exc).__name__}")
            if self._usb_descriptor_reader:
                try: interfaces.extend(self._usb_descriptor_reader(root))
                except (OSError, PermissionError) as exc: warnings.append(f"USB metadata partial: {type(exc).__name__}")
            transports=tuple(dict.fromkeys([_transport(item) for item in members]+[item.transport for item in interfaces]))
            fp=HardwareFingerprint(ident[0],ident[1],revision,root.instance_id,root.hardware_ids,root.compatible_ids,
                root.parent,root.container_id,root.class_name,root.service,root.driver_inf,root.manufacturer,
                root.description,root.location,transports,tuple(interfaces),{
                    "identity":Evidence.OBSERVED_WINDOWS.value,"topology":Evidence.OBSERVED_WINDOWS.value,
                    "interfaces":Evidence.OBSERVED_DESCRIPTOR.value if any(item.path for item in interfaces) else Evidence.OBSERVED_WINDOWS.value},
                tuple(item.instance_id for item in members if item.instance_id.casefold()!=root.instance_id.casefold()))
            results.append(ScanResult(fp,match_catalog(fp),tuple(warnings)))
        return tuple(results)


def default_safe_scanner() -> SafeScanner:
    """Build the production Safe Scan reader set without output-capable adapters."""
    from .windows_hid import enumerate_paths, inspect_path
    return SafeScanner(
        hid_enumerator=enumerate_paths,
        hid_inspector=inspect_path,
        usb_descriptor_reader=read_only_winusb_interfaces,
    )


def read_only_winusb_interfaces(record: WindowsDeviceMetadata) -> tuple[InterfaceFingerprint, ...]:
    """Query WinUSB descriptors using GENERIC_READ; no transfer API is loaded."""
    if os.name!="nt" or record.service.casefold()!="winusb":return ()
    from .windows_usb import enumerate_registered_winusb_paths
    paths=tuple(path for vid_pid,path in enumerate_registered_winusb_paths((record.vid_pid,)) if vid_pid==record.vid_pid)
    if not paths:return ()
    kernel=ctypes.WinDLL("kernel32",use_last_error=True);winusb=ctypes.WinDLL("winusb",use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    winusb.WinUsb_Initialize.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_void_p)];winusb.WinUsb_Initialize.restype=wintypes.BOOL
    class Descriptor(ctypes.Structure):_fields_=[("Length",ctypes.c_ubyte),("DescriptorType",ctypes.c_ubyte),("InterfaceNumber",ctypes.c_ubyte),("AlternateSetting",ctypes.c_ubyte),("NumEndpoints",ctypes.c_ubyte),("InterfaceClass",ctypes.c_ubyte),("InterfaceSubClass",ctypes.c_ubyte),("InterfaceProtocol",ctypes.c_ubyte),("Interface",ctypes.c_ubyte)]
    class Pipe(ctypes.Structure):_fields_=[("PipeType",ctypes.c_int),("PipeId",ctypes.c_ubyte),("MaximumPacketSize",ctypes.c_ushort),("Interval",ctypes.c_ubyte)]
    output=[];type_names={0:"control",1:"isochronous",2:"bulk",3:"interrupt"}
    for path in paths:
        handle=kernel.CreateFileW(path,0x80000000,0x3,None,3,0x40000000,None);usb=ctypes.c_void_p()
        if handle==ctypes.c_void_p(-1).value:raise PermissionError(ctypes.get_last_error(),"read-only WinUSB descriptor open")
        try:
            if not winusb.WinUsb_Initialize(handle,ctypes.byref(usb)):raise OSError(ctypes.get_last_error(),"WinUsb_Initialize read-only descriptor query")
            descriptor=Descriptor()
            if not winusb.WinUsb_QueryInterfaceSettings(usb,0,ctypes.byref(descriptor)):raise OSError(ctypes.get_last_error(),"WinUsb_QueryInterfaceSettings")
            endpoints=[]
            for index in range(descriptor.NumEndpoints):
                pipe=Pipe()
                if not winusb.WinUsb_QueryPipe(usb,0,index,ctypes.byref(pipe)):raise OSError(ctypes.get_last_error(),"WinUsb_QueryPipe")
                endpoints.append(EndpointFingerprint(pipe.PipeId,"in" if pipe.PipeId&0x80 else "out",type_names.get(pipe.PipeType,"unknown"),pipe.MaximumPacketSize))
            output.append(InterfaceFingerprint(path=path,number=descriptor.InterfaceNumber,class_code=descriptor.InterfaceClass,
                subclass=descriptor.InterfaceSubClass,protocol=descriptor.InterfaceProtocol,transport="winusb",endpoints=tuple(endpoints)))
        finally:
            if usb:winusb.WinUsb_Free(usb)
            kernel.CloseHandle(handle)
    return tuple(output)


class Redactor:
    def __init__(self): self._values: dict[str,str]={}; self._counts: dict[str,int]={}
    def token(self, kind: str, value: str) -> str:
        if not value:return value
        key=f"{kind}:{value.casefold()}"
        if key not in self._values:
            self._counts[kind]=self._counts.get(kind,0)+1; self._values[key]=f"TARGET_{kind}_{chr(64+self._counts[kind])}"
        return self._values[key]

    def public_fingerprint(self, fingerprint: HardwareFingerprint) -> dict:
        value=asdict(fingerprint)
        value["instance_id"]=self.token("INSTANCE",fingerprint.instance_id)
        value["parent_instance_id"]=self.token("PARENT",fingerprint.parent_instance_id)
        value["container_id"]=self.token("CONTAINER",fingerprint.container_id)
        value["location"]=self.token("LOCATION",fingerprint.location)
        value["child_instance_ids"]=[self.token("CHILD",item) for item in fingerprint.child_instance_ids]
        for interface in value["interfaces"]:
            interface["instance_id"]=self.token("INTERFACE",interface["instance_id"])
            interface["path"]=self.token("PATH",interface["path"])
        return value


def _result_dict(result: ScanResult, *, public: bool, redactor: Redactor | None = None) -> dict:
    fingerprint=(redactor or Redactor()).public_fingerprint(result.fingerprint) if public else asdict(result.fingerprint)
    return {"fingerprint":fingerprint,"fingerprint_id":result.fingerprint.deterministic_id(),
            "catalog_match":asdict(result.match),"warnings":list(result.warnings)}


def export_support_package(results: Iterable[ScanResult], output_dir: Path, *, include_private: bool = False,
                           now: datetime | None = None, oni_version: str = "0.1.1") -> Path:
    items=tuple(results)
    if not items: raise ValueError("at least one selected target is required")
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); stamp=now.strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True,exist_ok=True); path=output_dir/f"ONI-Support-Package-{stamp}.zip"
    redactor=Redactor(); public={"schema":SCHEMA_VERSION,"targets":[_result_dict(item,public=True,redactor=redactor) for item in items]}
    manifest={"schema":SCHEMA_VERSION,"oni_version":oni_version,"windows_version":platform.platform(),
              "scan_timestamp":now.isoformat(),"safe_scan":True,"target_count":len(items),
              "selected_target_identity":[item.fingerprint.vid_pid for item in items],
              "catalog_match_state":[item.match.state.value for item in items],
              "possible_protocol_families":[list(item.match.possible_protocol_families) for item in items],
              "protocol_verification_state":[item.match.protocol_verification for item in items],
              "active_write_operations_performed":False,"private_report_included":bool(include_private)}
    files={"manifest.json":json.dumps(manifest,indent=2,sort_keys=True)+"\n",
           "public_report.json":json.dumps(public,indent=2,sort_keys=True)+"\n",
           "README.txt":"ONI Safe Scan diagnostic evidence. This package does not prove protocol compatibility.\nNo active-write operation was performed.\n"}
    if include_private: files["private_report.json"]=json.dumps({"schema":SCHEMA_VERSION,"targets":[_result_dict(x,public=False) for x in items]},indent=2,sort_keys=True)+"\n"
    files["checksums.sha256"]="".join(f"{hashlib.sha256(data.encode()).hexdigest()}  {name}\n" for name,data in sorted(files.items()))
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o600<<16
            archive.writestr(info,data.encode())
    return path


def inspect_support_package(path: Path) -> dict:
    if path.stat().st_size>MAX_PACKAGE_BYTES:raise ValueError("support package exceeds size limit")
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist()
        if len(infos)>MAX_MEMBERS:raise ValueError("support package has too many members")
        for info in infos:
            pure=PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename:raise ValueError("unsafe ZIP member path")
            if info.file_size>MAX_MEMBER_BYTES:raise ValueError("support package member exceeds size limit")
        names={info.filename for info in infos}
        required={"manifest.json","public_report.json","README.txt","checksums.sha256"}
        if not required.issubset(names):raise ValueError("support package is incomplete")
        raw={name:archive.read(name) for name in names}
    expected={line.split("  ",1)[1]:line.split("  ",1)[0] for line in raw["checksums.sha256"].decode().splitlines() if "  " in line}
    for name,digest in expected.items():
        if name not in raw or hashlib.sha256(raw[name]).hexdigest()!=digest:raise ValueError(f"checksum mismatch: {name}")
    try: manifest=json.loads(raw["manifest.json"]);report=json.loads(raw["public_report.json"])
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise ValueError("malformed support package JSON") from exc
    if manifest.get("schema")!=SCHEMA_VERSION or report.get("schema")!=SCHEMA_VERSION:raise ValueError("unsupported diagnostic schema")
    if manifest.get("active_write_operations_performed") is not False:raise ValueError("package is not a Safe Scan report")
    targets=report.get("targets")
    if not isinstance(targets,list) or len(targets)!=manifest.get("target_count"):raise ValueError("target count mismatch")
    reconstructed=[]
    for target in targets:
        fp=target.get("fingerprint",{}); interfaces=[]
        for raw_interface in fp.get("interfaces",[]):
            endpoints=tuple(EndpointFingerprint(**endpoint) for endpoint in raw_interface.get("endpoints",[]))
            interfaces.append(InterfaceFingerprint(**{**raw_interface,"endpoints":endpoints}))
        try:
            rebuilt=HardwareFingerprint(**{**fp,"hardware_ids":tuple(fp.get("hardware_ids",())),
                "compatible_ids":tuple(fp.get("compatible_ids",())),"transport_types":tuple(fp.get("transport_types",())),
                "interfaces":tuple(interfaces)})
        except (TypeError,ValueError) as exc:raise ValueError("invalid fingerprint schema") from exc
        rebuilt_id=rebuilt.deterministic_id()
        if rebuilt_id!=target.get("fingerprint_id"):raise ValueError("fingerprint reconstruction mismatch")
        reconstructed.append(rebuilt_id)
    return {"manifest":manifest,"targets":targets,"interpretation":[target.get("catalog_match",{}) for target in targets],
            "reconstructed_fingerprint_ids":reconstructed}


def peerless_vision_fixture() -> ScanResult:
    fp=HardwareFingerprint(0x87AD,0x70DB,None,"REFERENCE:PEERLESS-VISION-360",(),(),"","","USB","WINUSB","","Thermalright","SSCRM-V1","",("winusb",),(),{
        "identity":Evidence.CATALOG_REFERENCE.value,"reference_identifier":Evidence.CATALOG_REFERENCE.value,
        "reference_resolution":Evidence.CATALOG_REFERENCE.value,"physical_resolution":Evidence.UNKNOWN.value})
    match=match_catalog(fp)
    return ScanResult(fp,match,("Reference resolution 480x480; physical resolution NOT VERIFIED.","Possible protocol ChiZhu; verification REQUIRED."))
