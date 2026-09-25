"""Interoperability definitions for community LCD panels.

The wire contracts were independently implemented from the GPLv3 InfoPanel
reference supplied by the user.  Nothing in this module enumerates catalog
entries as connected hardware: a model is installed only after a physical
interface has passed its protocol probe.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import struct
import time

from ..encoder import EncodedFrame
from ..live_state import DeviceDisconnected, SafetyError, TransportError


@dataclass(frozen=True, slots=True)
class CommunityPanelModel:
    key: str
    manufacturer: str
    name: str
    vid_pid: str
    native_size: tuple[int, int]
    render_size: tuple[int, int]
    transport: str
    protocol: str
    pixel_format: str = "jpeg"
    maximum_fps: int = 30
    orientation: str = "portrait"


MODELS = {
    "beada": CommunityPanelModel("beada", "NXElec", "BeadaPanel", "4e58:1001", (0, 0), (0, 0), "winusb", "panel-link", "rgb565-bgr-le", 30),
    "jl": CommunityPanelModel("jl", "Jungle Leopard", "JL LCD", "33c3:7788", (0, 0), (0, 0), "serial", "jl-jpeg", "jpeg", 30),
    "jonsbo-ds916": CommunityPanelModel("jonsbo-ds916", "Jonsbo", "Jonsbo DS916", "33c3:f101", (462, 1920), (462, 1920), "serial", "raw-jpeg", "jpeg", 25),
    "thermaltake-6": CommunityPanelModel("thermaltake-6", "Thermaltake", 'Thermaltake 6" LCD', "264a:2347", (1480, 720), (1480, 720), "hid", "by-hid-jpeg", "jpeg", 30, "landscape"),
    "asrock-pg360": CommunityPanelModel("asrock-pg360", "ASRock", "Phantom Gaming 360 LCD", "26ce:0a10", (480, 480), (480, 480), "hid", "by-hid-jpeg", "jpeg", 30, "square"),
    "lianli-88": CommunityPanelModel("lianli-88", "Lian Li", 'Universal Screen 8.8"', "1cbe:a088", (480,1920), (480,1920), "winusb", "lianli-jpeg", "jpeg", 30),
    "lianli-92": CommunityPanelModel("lianli-92", "Lian Li", 'Universal Screen 9.2"', "1cbe:a092", (464,1920), (464,1920), "winusb", "lianli-jpeg", "jpeg", 30),
    "lianli-oled": CommunityPanelModel("lianli-oled", "Lian Li", "HydroShift II OLED Curve", "1cbe:a068", (2288,1080), (2288,1080), "winusb", "lianli-jpeg", "jpeg", 30, "landscape"),
    "lianli-lcd": CommunityPanelModel("lianli-lcd", "Lian Li", "HydroShift II LCD", "1cbe:a034", (480,480), (480,480), "winusb", "lianli-jpeg", "jpeg", 30, "square"),
}

BEADA_MODEL_NAMES = {0:"5", 1:"7", 2:"6", 3:"3", 4:"4", 10:"5C", 11:"5T", 12:"7C", 13:"3C", 14:"4C", 15:"6C", 16:"6S", 17:"2", 18:"2W", 19:"7S", 20:"5S", 21:"8", 22:"11", 23:"9", 24:"Y", 25:"X", 26:"Z"}
BEADA_MODEL_SIZES = {0:(800,480),2:(480,1280),3:(320,480),4:(480,800),10:(800,480),11:(800,480),12:(800,480),13:(480,320),14:(800,480),15:(1280,480),16:(1280,480),17:(480,480),18:(480,480),19:(1280,400),20:(480,854),21:(480,1920),22:(440,1920),23:(462,1920),24:(480,1920),25:(440,1920),26:(462,1920)}


def parse_beada_info(response: bytes, vid_pid: str = "4e58:1001") -> CommunityPanelModel:
    if len(response) < 100 or response[:11] != b"STATUS-LINK" or response[12] != 1:
        raise SafetyError("invalid Beada STATUS-LINK panel-info response")
    from .beadapanel_protocol import ones_complement_checksum
    if int.from_bytes(response[18:20],"little") != ones_complement_checksum(response[:18]):raise SafetyError("invalid Beada STATUS-LINK header checksum")
    payload=response[20:100]; model_id=payload[5]
    if payload[2] not in (1,2):raise SafetyError(f"unsupported Beada Panel-Link version {payload[2]}")
    if payload[4] not in (1,2):raise SafetyError(f"unsupported Beada platform {payload[4]}")
    if model_id not in BEADA_MODEL_SIZES: raise SafetyError(f"unknown Beada model byte {model_id}")
    reported=(int.from_bytes(payload[70:72],"little"),int.from_bytes(payload[72:74],"little"))
    expected=BEADA_MODEL_SIZES[model_id]
    if reported != expected: raise SafetyError(f"Beada model/resolution mismatch: {model_id} reported {reported}")
    name=f"BeadaPanel {BEADA_MODEL_NAMES[model_id]}"
    return CommunityPanelModel(f"beada-{model_id}","NXElec",name,vid_pid,expected,expected,"winusb","panel-link","rgb565-bgr-le",30)


def parse_jonsbo_identity(data: bytes) -> tuple[str, tuple[int,int], str]:
    text=data.decode("ascii",errors="strict").strip("\0\r\n ")
    match=re.fullmatch(r"([A-Za-z0-9]{5,12})(\d{3,4})\*(\d{3,4})([A-Za-z0-9]+)",text)
    if not match: raise SafetyError("invalid Jonsbo identity response")
    size=(int(match.group(2)),int(match.group(3)))
    if size != (462,1920): raise SafetyError(f"unsupported Jonsbo identity resolution {size}")
    return match.group(1),size,match.group(4)


def parse_jl_device_info(data: bytes) -> tuple[str, tuple[int,int], int]:
    try: info=json.loads(data.rstrip(b"\0").decode("utf-8"))
    except Exception as exc: raise SafetyError("invalid JL device-info JSON") from exc
    if int(info.get("status",0)) != 200: raise SafetyError("JL getDeviceInfo was not accepted")
    size=(int(info.get("width",0)),int(info.get("height",0)))
    if min(size)<=0 or max(size)>4096: raise SafetyError(f"invalid JL resolution {size}")
    return str(info.get("model") or "JL LCD"),size,int(info.get("angle",0))


def jl_command(command: int, payload: bytes=b"") -> bytes:
    frame=bytearray(b"\x55\xaa"+struct.pack("<H",7+len(payload))+bytes((command,))+payload+b"\0\0")
    frame[-2:]=struct.pack("<H",sum(frame[:-2])&0xffff)
    return bytes(frame)


def jl_frame(jpeg: bytes) -> tuple[bytes,...]:
    size=struct.pack("<I",len(jpeg)); checksum=struct.pack("<H",sum(size+jpeg)&0xffff)
    return (jl_command(0x11),size+jpeg+checksum,b"\xff\xd9\xff\xd9")


def thermaltake_command(command: str, sequence: int, *, body: str|None=None, content_type: str|None=None, timestamp_ms: int|None=None) -> bytes:
    text=f"{command}\r\nSeqNumber={sequence}\r\nDate={timestamp_ms if timestamp_ms is not None else int(time.time()*1000)}\r\n"
    if content_type is not None:text+=f"ContentType={content_type}\r\nContentLength={len(body or '')}\r\n"
    content=(text+"\r\n"+(body or "")).encode("ascii")
    length=(len(content)+5)&0xff; wire=bytearray(1024);wire[:3]=bytes((0x5a,0,length));wire[3:3+len(content)]=content
    end=3+len(content);wire[end]=sum(content, length)&0xff;wire[end+1:end+3]=b"\x5a\0"
    return b"\0"+bytes(wire)


def thermaltake_frame(jpeg: bytes) -> tuple[bytes,...]:
    chunks=(len(jpeg)+999)//1000; output=[]
    for index in range(chunks):
        wire=bytearray(1024);wire[:9]=b"\x5c\x03\xfd\0"+struct.pack(">HH",chunks,index)+b"\x01"
        part=jpeg[index*1000:(index+1)*1000];wire[24:24+len(part)]=part;output.append(b"\0"+bytes(wire))
    return tuple(output)

def lianli_packet(command: int, payload: bytes=b"", *, timestamp: int|None=None) -> bytes:
    if len(payload)>512_000:raise ValueError("Lian Li image exceeds 512000-byte limit")
    from Crypto.Cipher import DES
    if timestamp is None:
        import datetime
        now=datetime.datetime.now();start=datetime.datetime.combine(now.date()-datetime.timedelta(days=1),datetime.time())
        timestamp=int((now-start).total_seconds()*1000)
    command_data=bytearray(500);command_data[0]=command;command_data[2:4]=b"\x1a\x6d";command_data[4:8]=struct.pack("<I",timestamp&0xffffffff)
    if command in (101,102):command_data[8:12]=struct.pack(">I",len(payload))
    padding=8-(len(command_data)%8)
    encrypted=DES.new(b"slv3tuzx",DES.MODE_CBC,b"slv3tuzx").encrypt(bytes(command_data)+bytes((padding,))*padding)
    packet=encrypted[:510].ljust(510,b"\0")+b"\xa1\x1a"
    return packet+payload


def encode_community(model: CommunityPanelModel, jpeg: bytes|None=None, pixels: bytes|None=None) -> EncodedFrame:
    raw=pixels if model.pixel_format.startswith("rgb565") else jpeg
    if raw is None: raise ValueError(f"{model.pixel_format} payload required")
    if model.protocol=="raw-jpeg":writes=(raw,)
    elif model.protocol=="jl-jpeg":writes=jl_frame(raw)
    elif model.protocol=="by-hid-jpeg":writes=thermaltake_frame(raw)
    elif model.protocol=="lianli-jpeg":writes=(lianli_packet(101,raw),)
    elif model.protocol=="panel-link":writes=(raw,)
    else:raise ValueError(f"unsupported community protocol {model.protocol}")
    return EncodedFrame(model.key,model.render_size,len(raw),hashlib.sha256(raw).hexdigest(),writes,f"community-{model.protocol}-{model.pixel_format}")


class CommunityConnection:
    """One physical handle owner; compatible with DisplaySession's sender contract."""
    def __init__(self, model: CommunityPanelModel, io, *, close_command: bytes|None=None):
        self.model=model;self.io=io;self.close_command=close_command;self.opened=False
    def open(self):
        if not self.opened:self.io.open();self.opened=True
    def __call__(self, frame: EncodedFrame) -> int:
        self.open();total=0
        for write in frame.writes:total+=self.io.write(write)
        return total
    def close(self):
        if self.opened and self.close_command:
            try:self.io.write(self.close_command)
            except Exception:pass
        self.io.close();self.opened=False
