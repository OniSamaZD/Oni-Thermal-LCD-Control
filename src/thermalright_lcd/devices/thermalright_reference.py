"""Reference-backed Thermalright panel identities and protocol framing.

This module contains no USB enumeration or handle ownership.  Discovery code may
feed an initialization response into :func:`detect_model`; only an exact result
is eligible for a transport adapter.  This keeps shared VID/PIDs fail-closed.

The table and wire formats are ported from the InfoPanel ThermalrightPanel
reference supplied for this project.  Models other than ONI's 0416:5408 and
0416:5302 devices are community-hardware-needed, not physically verified.
"""

from __future__ import annotations

from dataclasses import dataclass
import binascii
import json
import re
import subprocess
import struct
from ..subprocess_utils import hidden_subprocess_kwargs


@dataclass(frozen=True, slots=True)
class ThermalrightPanelModel:
    key: str
    name: str
    vid_pid: str
    native_size: tuple[int, int]
    render_size: tuple[int, int]
    transport: str
    protocol: str
    pixel_format: str = "jpeg"
    pm: int | None = None
    sub: int | None = None
    identifier: str = ""
    physically_verified: bool = False
    reference_output: bool = True


def _m(key, name, vid_pid, size, *, render=None, transport="winusb", protocol="chizhu",
       pixel="jpeg", pm=None, sub=None, identifier="", verified=False):
    return ThermalrightPanelModel(key, name, vid_pid, size, render or size, transport,
                                  protocol, pixel, pm, sub, identifier, verified, True)


_models = [
    _m("peerless-vision-360", "Grand / Hydro / Hyper / Peerless Vision 240/360", "87ad:70db", (480,480), identifier="SSCRM-V1"),
    _m("wonder-vision-360", 'Wonder Vision 360 6.67"', "87ad:70db", (2400,1080), render=(1600,720), sub=1, identifier="SSCRM-V3"),
    _m("wonder-vision-360-v2", 'Wonder Vision 360 6.67"', "87ad:70db", (2400,1080), render=(1600,720), sub=0x20, identifier="SSCRM-V3"),
    _m("rainbow-vision-360", 'Rainbow Vision 360 6.67"', "87ad:70db", (2400,1080), render=(1600,720), sub=2, identifier="SSCRM-V3"),
    _m("levita-vision-360", 'Levita Vision 360 6.67"', "87ad:70db", (2400,1080), render=(1600,720), sub=3, identifier="SSCRM-V3"),
    _m("tl-m10-vision", "TL-M10 Vision", "87ad:70db", (1920,462), identifier="SSCRM-V4"),
    _m("trofeo-vision-686", 'Trofeo Vision 6.86"', "0416:5302", (1280,480), transport="hid", protocol="trofeo", pm=0x80, identifier="BP21940", verified=True),
    _m("frozen-warframe-se", "Frozen Warframe SE", "0416:5302", (240,320), transport="hid", protocol="trofeo", pixel="rgb565-le", pm=0x3A, sub=0),
    _m("lm26", "LM26", "0416:5302", (240,320), transport="hid", protocol="trofeo", pixel="rgb565-le", pm=0x3A),
    _m("trofeo-vision-916", 'Trofeo Vision 9.16"', "0416:5408", (1920,480), transport="winusb", protocol="trofeo-bulk", verified=True),
    _m("trofeo-vision-916-v2", 'Trofeo Vision 9.16" v2', "0416:5408", (1920,480), transport="winusb", protocol="trofeo-bulk"),
    _m("trofeo-vision-113", 'Trofeo Vision 11.3"', "0416:5408", (1920,400), transport="winusb", protocol="trofeo-bulk"),
    _m("trofeo-vision-320", "Trofeo Vision 320x320", "0416:5302", (320,320), transport="hid", protocol="trofeo", pixel="rgb565-be", pm=0x20),
    _m("trofeo-vision-1600x720", "Trofeo Vision 1600x720", "0416:5302", (1600,720), transport="hid", protocol="trofeo", pm=0x40),
    _m("trofeo-vision-960x540", "Trofeo Vision 960x540", "0416:5302", (960,540), transport="hid", protocol="trofeo", pm=0x0A),
    _m("trofeo-vision-800x480", "Trofeo Vision 800x480", "0416:5302", (800,480), transport="hid", protocol="trofeo", pm=0x0C),
    _m("assassin-spirit-120-vision", 'Assassin Spirit 120 Vision 1.54"', "0416:5302", (240,240), transport="hid", protocol="trofeo", pixel="rgb565-le", pm=0x24),
    _m("frozen-warframe-49", "Frozen Warframe", "0416:5302", (240,320), transport="hid", protocol="trofeo", pixel="rgb565-le", pm=0x31),
    _m("frozen-warframe", "Frozen Warframe", "0416:5302", (320,320), transport="hid", protocol="trofeo", pm=0x32),
    _m("frozen-warframe-portrait", "Frozen Warframe", "0416:5302", (240,320), transport="hid", protocol="trofeo", pixel="rgb565-le", pm=0x33),
    _m("ba120-vision", 'BA120 Vision 2.4"', "0416:5302", (240,320), transport="hid", protocol="trofeo", pixel="rgb565-le", pm=0x34),
    _m("lf20", "LF20", "0416:5302", (320,320), transport="hid", protocol="trofeo", pm=0x35),
    _m("lc5", "LC5", "0416:5302", (360,360), transport="hid", protocol="trofeo", pm=0x36),
    _m("elite-vision-916", 'Elite Vision 9.16"', "0416:5302", (1920,462), transport="hid", protocol="trofeo", pm=0x41),
    _m("frozen-warframe-pro", "Frozen Warframe Pro", "0416:5302", (320,320), transport="hid", protocol="trofeo", pm=0x64),
    _m("elite-vision-hid", "Elite Vision", "0416:5302", (320,320), transport="hid", protocol="trofeo", pm=0x65),
    _m("elite-vision-360", "Thermalright 320x320 (SPISCRM-V2)", "87ad:70db", (320,320), pixel="rgb565-be", sub=0x20, identifier="SPISCRM-V2"),
    _m("trofeo-vision-916-ly1", 'Trofeo Vision 9.16" LY1', "0416:5409", (1920,480), protocol="trofeo-bulk-ly1"),
    _m("ali-vision-320x240", "ALi Vision 320x240", "0416:5406", (320,240), protocol="ali", pixel="rgb565-le"),
    _m("ali-vision-320x320", "ALi Vision 320x320", "0416:5406", (320,320), protocol="ali", pixel="rgb565-le"),
    _m("elite-vision-scsi", 'Elite Vision 360 2.73"', "0402:3922", (320,320), transport="scsi", protocol="scsi", pixel="rgb565-be"),
    _m("thermalright-scsi", "Thermalright LCD (SCSI)", "87cd:70db", (320,320), transport="scsi", protocol="scsi", pixel="rgb565-be"),
    _m("winbond-scsi", "Thermalright AIO LCD (SCSI)", "0416:5406", (320,320), transport="scsi", protocol="scsi", pixel="rgb565-be"),
]

_chizhu = {
    (3,None):("core-vision","Core Vision",(480,480)), (4,1):("hyper-vision","Hyper Vision",(480,480)),
    (4,2):("rp130-vision","RP130 Vision",(480,480)), (4,3):("lm16-se","LM16 SE",(480,480)),
    (4,4):("lf10v","LF10V",(480,480)), (4,5):("lm19-se","LM19 SE",(480,480)),
    (4,0x2E):("phantom-spirit-120-vision","Phantom Spirit 120 Vision EVO",(480,480)),
    (5,None):("mjolnir-vision","Mjolnir Vision",(320,240)), (6,1):("frozen-warframe-ultra","Frozen Warframe Ultra",(480,480)),
    (6,None):("frozen-vision-v2","Frozen Vision V2",(480,480)), (7,1):("stream-vision","Stream Vision",(640,480)),
    (7,2):("mjolnir-vision-pro","Mjolnir Vision Pro",(640,480)), (7,None):("stream-vision","Stream Vision",(640,480)),
    (9,None):("lc2jd","LC2JD",(854,480)), (10,5):("lf16","LF16",(960,540)),
    (10,6):("lf18","LF18",(960,540)), (10,7):("ld6","LD6",(960,540)), (10,None):("lc3","LC3",(960,540)),
    (11,6):("ld8","LD8",(854,480)), (11,None):("lf19","LF19",(854,480)), (12,None):("lf17","LF17",(800,480)),
    (13,None):("pc1","PC1",(960,320)), (14,1):("stream-vision","Stream Vision",(640,480)),
    (14,2):("mjolnir-vision-pro","Mjolnir Vision Pro",(640,480)), (14,None):("stream-vision","Stream Vision",(640,480)),
    (15,1):("lc7","LC7",(640,172)), (15,None):("lc8","LC8",(640,172)), (16,None):("cz2","CZ2",(960,540)),
    (17,2):("lc9","LC9",(960,320)), (17,None):("pc1","PC1",(960,320)),
    (0x20,None):("chizhu-vision-320x320","ChiZhu Vision 320x320",(320,320)),
    (63,1):("lm22","LM22",(1600,720)), (63,2):("lm27","LM27",(1600,720)), (63,3):("lm30","LM30",(1600,720)),
    (64,1):("lm22","LM22",(1600,720)), (64,2):("lm27","LM27",(1600,720)), (64,3):("lm30","LM30",(1600,720)),
    (65,1):("lf14","LF14",(1920,462)), (65,2):("lf14","LF14",(1920,462)),
    (65,3):("ld7","LD7",(1920,462)), (65,5):("ld7","LD7",(1920,462)), (65,4):("ld10","LD10",(1920,462)),
    (66,1):("lf14","LF14",(1920,462)), (66,2):("lf14","LF14",(1920,462)),
    (66,3):("ld7","LD7",(1920,462)), (66,4):("ld7","LD7",(1920,462)),
    (68,None):("lm24","LM24",(1280,480)), (69,2):("ld9","LD9",(1920,440)),
    (128,None):("lm24b","LM24",(1280,480)), (129,None):("grand-vision","Grand Vision",(480,480)),
    (1,48):("lm22","LM22",(1600,720)), (1,49):("lf14","LF14",(1920,462)),
}
for (pm, sub), (key, name, size) in _chizhu.items():
    pixel = "rgb565-be" if pm == 0x20 else "jpeg"
    if not any(model.key == key for model in _models):
        _models.append(_m(key, name, "87ad:70db", size, pm=pm, sub=sub, pixel=pixel))

MODELS = {model.key: model for model in _models}
SUPPORTED_VID_PIDS = frozenset(model.vid_pid for model in MODELS.values()) | {"0418:5303", "0418:5304"}


@dataclass(frozen=True, slots=True)
class ConnectedPanelCandidate:
    instance_id: str
    vid_pid: str
    service: str
    status: str
    container_id: str = ""
    interface_guid: str = ""
    device_path: str = ""


def parse_connected_candidates(payload: str) -> tuple[ConnectedPanelCandidate, ...]:
    """Filter a Windows PnP snapshot to physically present catalog identities."""
    raw=json.loads(payload or "[]")
    if isinstance(raw,dict):raw=[raw]
    found=[]
    for item in raw:
        instance=str(item.get("instance_id") or "")
        lowered=instance.lower();vid_pid=""
        for known in SUPPORTED_VID_PIDS:
            vid,pid=known.split(":")
            if f"vid_{vid}&pid_{pid}" in lowered:vid_pid=known;break
        if vid_pid and str(item.get("status") or "").upper()=="OK":
            found.append(ConnectedPanelCandidate(instance,vid_pid,str(item.get("service") or ""),"connected",str(item.get("container_id") or ""),str(item.get("interface_guid") or ""),str(item.get("device_path") or "")))
    return tuple(found)


def _instance_id_from_interface_path(path: str) -> str | None:
    match=re.search(r"usb#(vid_[0-9a-f]{4}&pid_[0-9a-f]{4}(?:&mi_[0-9a-f]{2})?)#([^#]+)#",path,re.I)
    return f"USB\\{match.group(1)}\\{match.group(2)}".upper() if match else None


def enumerate_connected_candidates(runner=subprocess.run, path_enumerator=None) -> tuple[ConnectedPanelCandidate, ...]:
    """Enumerate only registered interfaces for supported WinUSB identities.

    The old implementation queried properties for every USB PnP node and asked
    for a device-interface property on device objects.  On some Windows hosts
    that query never completes.  Interface enumeration is native and bounded;
    PowerShell is used only for the exact physical interfaces already found.
    """
    from ..windows_usb import enumerate_registered_winusb_paths
    supported=("87ad:70db","0416:5409","0416:5406")
    paths=(path_enumerator or enumerate_registered_winusb_paths)(supported)
    found=[]
    for vid_pid,path in paths:
        instance=_instance_id_from_interface_path(path)
        if not instance:continue
        escaped=instance.replace("'","''")
        script=(f"$d=Get-PnpDevice -InstanceId '{escaped}' -ErrorAction Stop;"
                f"$p=Get-PnpDeviceProperty -InstanceId '{escaped}' -ErrorAction Stop;"
                "$o=[ordered]@{status=$d.Status;container_id=($p|? KeyName -eq 'DEVPKEY_Device_ContainerId').Data};$o|ConvertTo-Json -Compress")
        try:cp=runner(["powershell","-NoProfile","-Command",script],capture_output=True,text=True,timeout=3,**hidden_subprocess_kwargs())
        except subprocess.TimeoutExpired:continue
        if cp.returncode:continue
        try:data=json.loads(cp.stdout or "{}")
        except json.JSONDecodeError:continue
        container=str(data.get("container_id") or "")
        if str(data.get("status") or "").upper()!="OK" or not container:continue
        guid_match=re.search(r"(#\{[0-9a-f-]+\})$",path,re.I);guid=guid_match.group(1)[1:] if guid_match else ""
        found.append(ConnectedPanelCandidate(instance,vid_pid,"WINUSB","connected",container,guid,path))
    return tuple(found)


def _only(candidates: list[ThermalrightPanelModel]) -> ThermalrightPanelModel | None:
    unique = {item.key: item for item in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def detect_model(vid_pid: str, transport: str, response: bytes) -> ThermalrightPanelModel | None:
    """Return one exact model or ``None``; never guesses on shared identifiers."""
    vid_pid, transport = vid_pid.lower(), transport.lower()
    if vid_pid == "0416:5302" and transport == "hid":
        if len(response) < 7 or response[:4] != b"\xda\xdb\xdc\xdd":
            return None
        pm, sub = response[5], response[4]
        exact = [m for m in MODELS.values() if m.vid_pid == vid_pid and m.pm == pm and m.sub == sub]
        if exact:
            return _only(exact)
        return _only([m for m in MODELS.values() if m.vid_pid == vid_pid and m.pm == pm and m.sub is None])
    if vid_pid == "0416:5408" and transport == "winusb":
        if len(response) < 21 or response[:2] != b"\x03\xff" or response[8] != 1:
            return None
        return MODELS[{1:"trofeo-vision-916", 2:"trofeo-vision-916-v2", 3:"trofeo-vision-916-v2", 5:"trofeo-vision-113"}.get(response[20], "")] if response[20] in (1,2,3,5) else None
    if vid_pid == "87ad:70db" and transport == "winusb":
        if len(response) < 29 or response[4:8] == b"\xa1\xa2\xa3\xa4":
            return None
        pm, sub = response[24], response[28]
        identifier = response[4:20].rstrip(b"\0").decode("ascii", "ignore")
        strict = [m for m in MODELS.values() if m.vid_pid == vid_pid and m.identifier == identifier and m.sub == sub]
        if strict:
            return _only(strict)
        entry = _chizhu.get((pm, sub)) or _chizhu.get((pm, None))
        if pm == 9 and sub >= 5:
            entry = ("lf19", "LF19", (854,480))
        if entry:
            return MODELS[entry[0]]
        return _only([m for m in MODELS.values() if m.vid_pid == vid_pid and m.identifier == identifier])
    if vid_pid == "0416:5409" and transport == "winusb":
        return MODELS["trofeo-vision-916-ly1"] if len(response) >= 9 and response[:2] == b"\x03\xff" and response[8] == 1 else None
    if vid_pid == "0416:5406" and transport == "winusb":
        if len(response) < 14:
            return None
        return MODELS["ali-vision-320x240"] if response[0] == 54 else MODELS["ali-vision-320x320"] if response[0] in (101,102) else None
    if transport == "scsi" and vid_pid in {"0402:3922", "87cd:70db", "0416:5406"}:
        if len(response) < 8 or response[4:8] == b"\xa1\xa2\xa3\xa4":
            return None
        sizes = {0x24:(240,240), 0x32:(320,240), 0x33:(320,240), 0x64:(320,320), 0x65:(320,320)}
        expected = sizes.get(response[0])
        candidates = [m for m in MODELS.values() if m.vid_pid == vid_pid and m.transport == "scsi" and m.native_size == expected]
        return _only(candidates)
    # Unique VID/PID is safe only when transport also matches.
    return _only([m for m in MODELS.values() if m.vid_pid == vid_pid and m.transport == transport])


def build_probe(vid_pid: str, transport: str) -> bytes:
    if vid_pid.lower() == "0416:5302" and transport.lower() == "hid":
        return b"\xda\xdb\xdc\xdd" + bytes(8) + b"\x01" + bytes(499)
    if vid_pid.lower() == "0416:5408" and transport.lower() == "winusb":
        packet = bytearray(2048); packet[:2] = b"\x02\xff"; packet[8] = 1; return bytes(packet)
    if vid_pid.lower() == "0416:5409" and transport.lower() == "winusb":
        packet = bytearray(512); packet[:2] = b"\x02\xff"; packet[8] = 1; return bytes(packet)
    if vid_pid.lower() == "0416:5406" and transport.lower() == "winusb":
        return bytes.fromhex("f5000100bcffb6c80000000000040000") + bytes(1024)
    if vid_pid.lower() == "87ad:70db" and transport.lower() == "winusb":
        packet = bytearray(64); packet[:4] = b"\x12\x34\x56\x78"; packet[56:60] = struct.pack("<I", 1); return bytes(packet)
    raise ValueError("no reviewed probe for VID/PID and transport")


def frame_packets(model: ThermalrightPanelModel, payload: bytes) -> tuple[bytes, ...]:
    """Construct reference wire frames after caller has validated payload format/size."""
    width, height = model.render_size
    expected = width * height * 2
    if model.pixel_format.startswith("rgb565") and len(payload) != expected:
        raise ValueError(f"RGB565 payload must be exactly {expected} bytes")
    if model.protocol == "trofeo":
        header = bytearray(512); header[:4] = b"\xda\xdb\xdc\xdd"; header[4] = 2
        header[6] = int(model.pixel_format.startswith("rgb565")); header[8:12] = struct.pack("<HH", width, height)
        header[12] = 2; header[16:20] = struct.pack("<I", len(payload)); header[20:20+min(492,len(payload))] = payload[:492]
        rest = payload[492:]
        return (bytes(header),) + tuple(rest[i:i+512].ljust(512,b"\0") for i in range(0,len(rest),512))
    if model.protocol == "chizhu":
        header = bytearray(64); header[:4] = b"\x12\x34\x56\x78"
        header[4:8] = struct.pack("<I", 3 if model.pixel_format.startswith("rgb565") else 2)
        header[8:16] = struct.pack("<II", width, height); header[56:60] = struct.pack("<I", 2)
        header[60:64] = struct.pack("<I", len(payload))
        return (bytes(header) + payload,)
    if model.protocol in {"trofeo-bulk", "trofeo-bulk-ly1"}:
        chunks=(len(payload)+495)//496
        blocks=[]
        command_type=2 if model.protocol.endswith("ly1") else 1
        for index in range(chunks):
            body=payload[index*496:(index+1)*496]
            header=b"\x01\xff"+struct.pack("<IH",len(payload),len(body))+bytes([command_type])+struct.pack("<HH",chunks,index)+b"\0\0\0"
            blocks.append(header+body.ljust(496,b"\0"))
        if model.protocol == "trofeo-bulk":
            blocks.extend([bytes(512)]*((-len(blocks))%4))
            stream=b"".join(blocks);return tuple(stream[i:i+4096] for i in range(0,len(stream),4096))
        return tuple(blocks)
    if model.protocol == "ali":
        header = bytearray(bytes.fromhex("f5010100bcffb6c80000000000000000"));header[12:16]=struct.pack("<I",len(payload))
        return (bytes(header)+payload,)
    if model.protocol == "scsi":
        chunk_size = 0xE100 if width * height <= 76800 else 0x10000
        return tuple(build_scsi_cdb(0x101F5 | (index << 24), len(chunk)) + chunk
                     for index, chunk in enumerate(payload[i:i+chunk_size] for i in range(0,len(payload),chunk_size)))
    raise ValueError(f"frame construction is not defined for {model.protocol}")


def build_scsi_cdb(command: int, data_size: int) -> bytes:
    head = struct.pack("<I8xI", command, data_size)
    return head + struct.pack("<I", binascii.crc32(head) & 0xFFFFFFFF)


class ReferencePanelConnection:
    """Bounded protocol session over an already identity-validated transport.

    The transport is deliberately injected: enumeration must first prove that a
    physical interface exists and bind its stable identity.  Construction never
    opens a handle and the catalog alone can never create a session.
    """

    def __init__(self, vid_pid: str, transport_name: str, transport, out_endpoint: str, in_endpoint: str,
                 *, timeout_ms: int = 5000, max_frame_writes: int = 4096):
        self.vid_pid=vid_pid.lower();self.transport_name=transport_name.lower();self.transport=transport
        self.out_endpoint=out_endpoint;self.in_endpoint=in_endpoint;self.timeout_ms=timeout_ms
        self.max_frame_writes=max_frame_writes;self.model=None;self._opened=False;self._writes=0

    def open(self):
        if self._opened:return self.model
        discover=getattr(self.transport,"discover",None)
        if discover:
            identity=discover();revalidate=getattr(self.transport,"revalidate",None)
            if revalidate:revalidate(identity)
        self.transport.open(self.timeout_ms)
        try:
            probe=build_probe(self.vid_pid,self.transport_name)
            if self.transport.write(self.out_endpoint,probe,self.timeout_ms)!=len(probe):raise RuntimeError("short initialization write")
            response_size=37 if self.transport_name=="hid" else 511 if self.vid_pid=="0416:5409" else 1024 if self.vid_pid in {"87ad:70db","0416:5406"} else 512
            response=self.transport.read(self.in_endpoint,response_size,self.timeout_ms)
            self.model=detect_model(self.vid_pid,self.transport_name,response)
            if self.model is None:raise RuntimeError("initialization response did not identify one supported model")
            self._opened=True;return self.model
        except Exception:
            self.transport.close(self.timeout_ms);raise

    def send(self,payload: bytes) -> int:
        model=self.open();packets=frame_packets(model,payload)
        if self._writes+len(packets)>self.max_frame_writes:raise RuntimeError("reference panel write budget exceeded")
        total=0
        for packet in packets:
            written=self.transport.write(self.out_endpoint,packet,self.timeout_ms)
            if written!=len(packet):raise RuntimeError("short frame write")
            total+=written;self._writes+=1
        if model.protocol in {"trofeo-bulk","trofeo-bulk-ly1","ali"}:
            ack_size=16 if model.protocol=="ali" else 511 if model.protocol=="trofeo-bulk-ly1" else 512
            if not self.transport.read(self.in_endpoint,ack_size,self.timeout_ms):raise RuntimeError("missing frame acknowledgement")
        return total

    def send_encoded(self, encoded) -> int:
        model=self.open()
        if encoded.dimensions != model.render_size or encoded.vid_pid != model.key:
            raise RuntimeError("encoded frame does not match detected reference model")
        packets=encoded.writes
        if self._writes+len(packets)>self.max_frame_writes:raise RuntimeError("reference panel write budget exceeded")
        total=0
        for packet in packets:
            written=self.transport.write(self.out_endpoint,packet,self.timeout_ms)
            if written!=len(packet):raise RuntimeError("short frame write")
            total+=written;self._writes+=1
        if model.protocol in {"trofeo-bulk","trofeo-bulk-ly1","ali"}:
            ack_size=16 if model.protocol=="ali" else 511 if model.protocol=="trofeo-bulk-ly1" else 512
            if not self.transport.read(self.in_endpoint,ack_size,self.timeout_ms):raise RuntimeError("missing frame acknowledgement")
        return total

    __call__ = send_encoded

    def close(self):
        if self._opened:self.transport.close(self.timeout_ms)
        self._opened=False
