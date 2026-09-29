"""MacroSilicon MS9132 composite HID/bulk panel protocol.

Evidence: the user-supplied InfoPanel Jonsbo/VMAX implementations and
MacroSilicon's GPL MS91xx driver.  VID/PID 345f:9132 is only the bridge
identity; a valid EDID preferred timing is required before output is enabled.
"""
from __future__ import annotations

from dataclasses import replace
import time

from ..live_state import SafetyError, TransportError
from .community_panels import CommunityPanelModel, MODELS

VIC_BY_SIZE={(376,960):171,(320,960):178}
MODEL_BY_SIZE={(376,960):"jonsbo-ds339",(320,960):"vmax-46"}

STARTUP_REPORTS=(
    (0xB5,0xFF,0),(0xB5,0xF0,0),(0xB5,0,0x31),(0xB5,0,0x30),(0xB5,0xF4,0x39),
    (0xF5,0,0x1F,0xE0),(0xF5,0,0x1F,0xE8),(0xF5,0,0x1F,0xF0),(0xF5,0,0x1F,0xF8),
    (0xA6,0x07,0x01,0x02),(0xB5,0xC4,0x54),(0xA6,0x05,0),(0xB5,0xC5,0x55),
    (0xB5,0xF0,0x05),(0xB6,0xF0,0x05,0x20),(0xC5,0xB0,0),(0xC6,0xB0,0xDF),
    (0xC5,0xA0,0),(0xC6,0xA0,0xE4),(0xC5,0xA0,0),(0xC6,0xA0,0xF0),
    (0xB5,0xF0,0x16),(0xB6,0xF0,0x16,0),(0xB5,0,0x32),
)+tuple((0xB5,0xC0,offset) for offset in range(0,128,4))

def _report(*values:int)->bytes:return bytes(values).ljust(8,b"\0")

def _command_delay(payload:bytes)->float:
    if payload[:3]==b"\xa6\x07\x01":return .105
    if payload[:3]==b"\xb5\x00\x32":return .108
    if payload[0]==0xA6:return .015
    return .003

def parse_ms9132_edid(edid:bytes)->CommunityPanelModel:
    if len(edid)!=128 or edid[:8]!=b"\x00\xff\xff\xff\xff\xff\xff\x00" or sum(edid)&0xff:
        raise SafetyError("invalid MS9132 EDID block")
    base=0x36
    width=((edid[base+4]&0xf0)<<4)|edid[base+2]
    height=((edid[base+7]&0xf0)<<4)|edid[base+5]
    size=(width,height);key=MODEL_BY_SIZE.get(size)
    if key is None:raise SafetyError(f"unsupported or ambiguous MS9132 EDID resolution {size}")
    return replace(MODELS[key],native_size=size,render_size=size)

def ms9132_frame(model:CommunityPanelModel,pixels:bytes)->bytes:
    width,height=model.render_size;expected=width*height*3
    if model.protocol!="ms9132-rgb888" or len(pixels)!=expected:raise ValueError(f"MS9132 BGR888 payload must be exactly {expected} bytes")
    flagged=height|0x8000
    return bytes((0xff,0,0,0,0,width//16,flagged>>8,flagged&0xff))+pixels+b"\xff\xc0"+b"\0"*6

def probe_ms9132_model(hid_path,hid_api)->CommunityPanelModel:
    """Read the bridge EDID over its HID control plane; no bulk output occurs."""
    handle=hid_api.open(hid_path);edid=bytearray(128)
    try:
        for values in STARTUP_REPORTS:
            payload=_report(*values);report=b"\0"+payload
            hid_api.set_feature(handle,report);reply=hid_api.get_feature(handle,9)
            if len(reply)!=9:raise TransportError("short MS9132 feature response")
            if payload[:2]==b"\xb5\xc0":edid[payload[2]:payload[2]+4]=reply[4:8]
            time.sleep(_command_delay(payload))
        return parse_ms9132_edid(bytes(edid))
    finally:
        try:hid_api.set_feature(handle,b"\0"+_report(0xA6,0x07,0))
        except Exception:pass
        hid_api.close(handle)

class Ms9132Connection:
    """Owns the HID control and WinUSB frame handles for one physical panel."""
    def __init__(self,model,hid_path,bulk_path,hid_api,usb_api):
        self.model=model;self.hid_path=hid_path;self.bulk_path=bulk_path;self.hid_api=hid_api;self.usb_api=usb_api
        self.hid=self.file=self.usb=None;self.opened=False;self.video_enabled=False
    def _feature(self,payload:bytes)->bytes:
        report=b"\0"+bytes(payload).ljust(8,b"\0");self.hid_api.set_feature(self.hid,report)
        reply=self.hid_api.get_feature(self.hid,9)
        if len(reply)!=9:raise TransportError("short MS9132 feature response")
        time.sleep(_command_delay(payload))
        return reply[4:9]
    def _initialize(self):
        edid=bytearray(128)
        for values in STARTUP_REPORTS:
            payload=_report(*values);reply=self._feature(payload)
            if payload[:2]==b"\xb5\xc0":edid[payload[2]:payload[2]+4]=reply[:4]
        detected=parse_ms9132_edid(bytes(edid))
        if detected.key!=self.model.key:raise SafetyError("MS9132 identity changed between discovery and session open")
        width,height=self.model.render_size;vic=VIC_BY_SIZE[(width,height)];wh=(width>>8,width&255,height>>8,height&255)
        for values in ((0xB5,0,0x32),(0xB5,0xF4,0x39),(0xA6,0x03,0x03),(0xB5,0xC5,0x58),
                       (0xA6,0x01,*wh,0x11,0),(0xB5,0xC5,0x56),(0xA6,0x02,vic,0,*wh),(0xB5,0xC5,0x57),(0xA6,0x04,1)):
            self._feature(_report(*values))
        time.sleep(.4)
    def open(self):
        if self.opened:return
        self.hid=self.hid_api.open(self.hid_path)
        try:
            self.file=self.usb_api.create_file(self.bulk_path,5000);self.usb=self.usb_api.winusb_initialize(self.file)
            self.usb_api.query_pipe(self.usb,0,0x04);self.usb_api.set_timeout(self.usb,0x04,5000)
            self._initialize();self.opened=True
        except Exception:self.close();raise
    def __call__(self,frame)->int:
        self.open();total=0
        for wire in frame.writes:
            for offset in range(0,len(wire),65536):
                part=wire[offset:offset+65536];count=self.usb_api.write_pipe(self.usb,0x04,part)
                if count!=len(part):
                    try:self.usb_api.reset_pipe(self.usb,0x04)
                    except Exception:pass
                    raise TransportError(f"short MS9132 bulk write {count}/{len(part)}")
                total+=count
        if not self.video_enabled:
            for values in ((0xB5,0xF0,0x05),(0xB6,0xF0,0x05,0x30),(0xA6,0x05,1),(0xB5,0xC5,0x55)):self._feature(_report(*values))
            self.video_enabled=True
        return total
    def close(self):
        if self.hid is not None:
            try:self._feature(_report(0xA6,0x07,0))
            except Exception:pass
        hid,self.hid=self.hid,None
        if hid is not None:self.hid_api.close(hid)
        usb,file_handle=self.usb,self.file;self.usb=self.file=None
        if usb:self.usb_api.free(usb)
        if file_handle:self.usb_api.close_handle(file_handle)
        self.opened=False;self.video_enabled=False
