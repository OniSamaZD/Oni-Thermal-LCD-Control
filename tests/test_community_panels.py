import json
import unittest

from thermalright_lcd.community_runtime import discover_community_displays
from thermalright_lcd.devices.community_panels import (MODELS, encode_community,
    jl_command, lianli_packet, parse_beada_info, parse_jl_device_info, parse_jonsbo_identity,
    thermaltake_command, thermaltake_frame, turzx_packet, usbpc_command, parse_usbpc_hello)
from thermalright_lcd.devices.ms9132 import parse_ms9132_edid
from thermalright_lcd.live_state import SafetyError
from thermalright_lcd.encoder import reframe_encoded
from thermalright_lcd.device_connection import build_gui_sender
from thermalright_lcd.windows_hid import HidInterface
from thermalright_lcd.windows_serial import SerialCandidate


def beada_response(model=15,size=(1280,480)):
    from thermalright_lcd.devices.beadapanel_protocol import ones_complement_checksum
    data=bytearray(100);data[:11]=b"STATUS-LINK";data[12]=1;data[22]=1;data[24]=1;data[25]=model;data[18:20]=ones_complement_checksum(data[:18]).to_bytes(2,"little")
    data[90:92]=size[0].to_bytes(2,"little");data[92:94]=size[1].to_bytes(2,"little")
    return bytes(data)

class FakeSerial:
    replies=[]
    instances=[]
    def __init__(self,*args,**kwargs):self.writes=[];self.dtr=self.rts=False;self.closed=False;self.reply=self.replies.pop(0);self.instances.append(self)
    def write(self,data):self.writes.append(bytes(data));return len(data)
    def read(self,n):
        data=self.reply[:n];self.reply=self.reply[n:];return data
    @property
    def in_waiting(self):return len(self.reply)
    def close(self):self.closed=True

class FakeHid:
    def __init__(self):self.responses=[b"\0HTTP 200 OK",b"\0HTTP 200 OK"];self.writes=[];self.closed=[]
    def open(self,path):return path
    def write_report(self,handle,data,timeout):self.writes.append(bytes(data));return len(data)
    def read_report(self,handle,length,timeout):return self.responses.pop(0)
    def close(self,handle):self.closed.append(handle)

class FakeUsb:
    def __init__(self,response):self.response=response;self.writes=[];self.closed=0
    def create_file(self,path,timeout):return "file"
    def winusb_initialize(self,handle):return "usb"
    def query_pipe(self,u,interface,endpoint):return {"endpoint":endpoint,"type":2}
    def set_timeout(self,*args):pass
    def write_pipe(self,u,ep,data):self.writes.append(bytes(data));return len(data)
    def read_pipe(self,u,ep,length):return self.response
    def free(self,u):pass
    def close_handle(self,h):self.closed+=1
    def reset_pipe(self,*args):pass

def ms9132_edid(size=(376,960),name="DS339"):
    data=bytearray(128);data[:8]=b"\x00\xff\xff\xff\xff\xff\xff\x00";base=0x36
    width,height=size;data[base]=1;data[base+2]=width&255;data[base+4]=((width>>8)&15)<<4
    data[base+5]=height&255;data[base+7]=((height>>8)&15)<<4
    descriptor=0x48;data[descriptor:descriptor+5]=b"\0\0\0\xfc\0";data[descriptor+5:descriptor+18]=name.encode()[:13].ljust(13,b" ")
    data[127]=(-sum(data))&255;return bytes(data)

class FakeMsHid:
    def __init__(self,edid):self.edid=edid;self.command=b"";self.closed=[];self.features=[]
    def open(self,path):return path
    def set_feature(self,handle,data):self.command=bytes(data[1:9]);self.features.append(self.command)
    def get_feature(self,handle,length):
        reply=bytearray(9)
        if self.command[:2]==b"\xb5\xc0":reply[4:8]=self.edid[self.command[2]:self.command[2]+4]
        elif self.command[:3]==b"\xb5\x00\x32":reply[4]=1
        return bytes(reply)
    def close(self,handle):self.closed.append(handle)

class CommunityProtocolTests(unittest.TestCase):
    def test_jl_command_and_identity_are_strict(self):
        frame=jl_command(6,b"abc")
        self.assertEqual(frame[:2],b"\x55\xaa");self.assertEqual(int.from_bytes(frame[2:4],"little"),10)
        self.assertEqual(int.from_bytes(frame[-2:],"little"),sum(frame[:-2])&0xffff)
        self.assertEqual(parse_jonsbo_identity(b"VMAXB160462*1920S261301227")[1],(462,1920))
        with self.assertRaises(SafetyError):parse_jonsbo_identity(b"VMAXB160320*480S1")

    def test_jl_info_controls_dynamic_canvas(self):
        name,size,angle=parse_jl_device_info(json.dumps({"status":200,"model":"JL Custom","width":1920,"height":462,"angle":90}).encode())
        self.assertEqual((name,size,angle),("JL Custom",(1920,462),90))

    def test_beada_response_controls_exact_model(self):
        model=parse_beada_info(beada_response())
        self.assertEqual((model.name,model.render_size),("BeadaPanel 6C",(1280,480)))
        with self.assertRaises(SafetyError):parse_beada_info(beada_response(size=(800,480)))

    def test_thermaltake_framing(self):
        command=thermaltake_command("POST conn 1",100,timestamp_ms=0)
        self.assertEqual(len(command),1025);self.assertEqual(command[1:3],b"\x5a\0")
        writes=thermaltake_frame(b"x"*2001)
        self.assertEqual(len(writes),3);self.assertTrue(all(len(x)==1025 for x in writes))
        self.assertEqual(writes[0][1:10],b"\x5c\x03\xfd\0\0\x03\0\0\x01")

    def test_lianli_encrypted_command_and_combined_payload(self):
        packet=lianli_packet(101,b"jpeg",timestamp=1)
        self.assertEqual(len(packet),516);self.assertEqual(packet[510:512],b"\xa1\x1a");self.assertEqual(packet[-4:],b"jpeg")

    def test_turzx_command_uses_reference_zero_padding_and_payload(self):
        packet=turzx_packet(101,b"jpeg",timestamp=1)
        self.assertEqual(len(packet),516);self.assertEqual(packet[510:512],b"\xa1\x1a");self.assertEqual(packet[-4:],b"jpeg")
        self.assertNotEqual(packet[:504],lianli_packet(101,b"jpeg",timestamp=1)[:504])

    def test_serial_discovery_requires_protocol_response(self):
        reply=b"VMAXB160462*1920S261301227"
        FakeSerial.replies=[reply];FakeSerial.instances=[]
        displays=discover_community_displays(serial_candidates=[SerialCandidate("COM7","serial-7","33c3:f101")],hid_paths=[],winusb_candidates=[],serial_factory=FakeSerial)
        self.assertEqual(len(displays),1);self.assertTrue(displays[0].connectable);self.assertIn("jonsbo-ds916",displays[0].device_id)

    def test_serial_runtime_revalidates_then_sends_through_registered_sender(self):
        reply=b"VMAXB160462*1920S261301227"
        FakeSerial.replies=[reply,reply];FakeSerial.instances=[]
        display=discover_community_displays(serial_candidates=[SerialCandidate("COM9","serial-9","33c3:f101")],hid_paths=[],winusb_candidates=[],serial_factory=FakeSerial)[0]
        sender=build_gui_sender(display.device_id);frame=encode_community(MODELS["jonsbo-ds916"],jpeg=b"\xff\xd8x\xff\xd9")
        self.assertEqual(sender(frame),len(frame.writes[0]));sender.close()
        self.assertEqual(FakeSerial.instances[1].writes[0],b"\xf0\xa5\x5a\x0f")
        self.assertEqual(FakeSerial.instances[1].writes[1],frame.writes[0])

    def test_unknown_serial_response_is_fail_closed(self):
        FakeSerial.replies=[b"not a panel"]
        displays=discover_community_displays(serial_candidates=[SerialCandidate("COM8","serial-8","33c3:f101")],hid_paths=[],winusb_candidates=[],serial_factory=FakeSerial)
        self.assertFalse(displays[0].connectable);self.assertTrue(displays[0].device_id.startswith("unsupported:"))

    def test_hid_discovery_needs_200_handshake(self):
        api=FakeHid();info=HidInterface("hid-1",0x264a,0x2347,1,1025,1025)
        displays=discover_community_displays(serial_candidates=[],hid_paths=["hid-1"],hid_inspector=lambda p:info,hid_api=api,winusb_candidates=[])
        self.assertTrue(displays[0].connectable);self.assertEqual(len(api.writes),2);self.assertEqual(api.closed,["hid-1"])

    def test_beada_discovery_uses_physical_probe(self):
        api=FakeUsb(beada_response())
        displays=discover_community_displays(serial_candidates=[],hid_paths=[],winusb_candidates=[("beada-1","4e58:1001","path")],winusb_api=api)
        self.assertTrue(displays[0].connectable);self.assertIn("beada-15",displays[0].device_id)
        self.assertEqual(len(api.writes),2)

    def test_lianli_discovery_requires_real_acknowledgements(self):
        api=FakeUsb(bytes(512))
        displays=discover_community_displays(serial_candidates=[],hid_paths=[],winusb_candidates=[("lian-1","1cbe:a088","path")],winusb_api=api)
        self.assertTrue(displays[0].connectable);self.assertIn("lianli-88",displays[0].device_id)
        self.assertEqual(len(api.writes),2)

    def test_turzx_unique_usb_pid_routes_to_exact_model_and_sender(self):
        api=FakeUsb(bytes(512))
        displays=discover_community_displays(serial_candidates=[],hid_paths=[],winusb_candidates=[("turzx-1","1cbe:0046","path")],winusb_api=api)
        self.assertTrue(displays[0].connectable);self.assertIn("turzx-46",displays[0].device_id)
        sender=build_gui_sender(displays[0].device_id);encoded=encode_community(MODELS["turzx-46"],jpeg=b"\xff\xd8x\xff\xd9")
        self.assertEqual(sender(encoded),len(encoded.writes[0]));sender.close()
        self.assertEqual(api.writes[-2],encoded.writes[0]);self.assertEqual(api.writes[-1],turzx_packet(123,timestamp=0))

    def test_usbpc_hello_strictly_selects_each_geometry(self):
        self.assertEqual(parse_usbpc_hello(b"\x01"*6).render_size,(320,480))
        self.assertEqual(parse_usbpc_hello(b"\x02"*6).render_size,(480,800))
        self.assertEqual(parse_usbpc_hello(b"\x03"*6).render_size,(600,1024))
        with self.assertRaises(SafetyError):parse_usbpc_hello(b"TURING")

    def test_usbpc_discovery_and_frame_route_through_dynamic_session(self):
        FakeSerial.replies=[b"\x02"*6,b"\x02"*6];FakeSerial.instances=[]
        display=discover_community_displays(serial_candidates=[SerialCandidate("COM11","serial-usbpc","1a86:5722")],hid_paths=[],winusb_candidates=[],serial_factory=FakeSerial)[0]
        self.assertTrue(display.connectable);self.assertIn("usbpc-5",display.device_id)
        pixels=b"\x00\xf8"*(480*800);encoded=encode_community(MODELS["usbpc-5"],pixels=pixels)
        self.assertEqual(encoded.writes[0],usbpc_command(197,0,0,479,799));self.assertTrue(all(len(part)<=480*8*2 for part in encoded.writes[1:]))
        sender=build_gui_sender(display.device_id);self.assertEqual(sender(encoded),sum(map(len,encoded.writes)));sender.close()
        self.assertEqual(FakeSerial.instances[1].writes[0],bytes((69,))*6)

    def test_catalog_does_not_create_connected_devices(self):
        displays=discover_community_displays(serial_candidates=[],hid_paths=[],winusb_candidates=[])
        self.assertEqual(displays,())

    def test_dynamic_encoder_routes_each_family(self):
        jpeg=b"\xff\xd8abc\xff\xd9"
        self.assertEqual(encode_community(MODELS["jonsbo-ds916"],jpeg=jpeg).writes,(jpeg,))
        encoded=encode_community(MODELS["thermaltake-6"],jpeg=jpeg)
        self.assertEqual(len(encoded.writes[0]),1025)
        self.assertIs(reframe_encoded(encoded),encoded)

    def test_ms9132_edid_is_the_model_discriminator(self):
        self.assertEqual(parse_ms9132_edid(ms9132_edid()).key,"jonsbo-ds339")
        self.assertEqual(parse_ms9132_edid(ms9132_edid((320,960),"VMAXB01")).key,"vmax-46")
        with self.assertRaises(SafetyError):parse_ms9132_edid(ms9132_edid((360,960)))

    def test_ms9132_frame_geometry_and_exact_wire_contract(self):
        model=MODELS["vmax-46"];pixels=b"\x03\x02\x01"*(320*960)
        encoded=encode_community(model,pixels=pixels);wire=encoded.writes[0]
        self.assertEqual(wire[:8],b"\xff\x00\x00\x00\x00\x14\x83\xc0")
        self.assertEqual(wire[8:11],b"\x03\x02\x01");self.assertEqual(wire[-8:],b"\xff\xc0"+b"\0"*6)
        self.assertEqual(len(wire),320*960*3+16)

    def test_ms9132_physical_pair_edid_probe_registers_dynamic_sender(self):
        hid=FakeMsHid(ms9132_edid());usb=FakeUsb(b"")
        displays=discover_community_displays(serial_candidates=[],hid_paths=[],hid_api=hid,
            winusb_candidates=[("ms-1","345f:9132","bulk-path","hid-path")],winusb_api=usb)
        self.assertEqual(len(displays),1);self.assertTrue(displays[0].connectable);self.assertIn("jonsbo-ds339",displays[0].device_id)
        sender=build_gui_sender(displays[0].device_id)
        pixels=b"\0"*(376*960*3);frame=encode_community(MODELS["jonsbo-ds339"],pixels=pixels)
        self.assertEqual(sender(frame),len(frame.writes[0]));sender.close()
        bulk=[part for part in usb.writes if len(part)>9]
        self.assertEqual(sum(map(len,bulk)),len(frame.writes[0]));self.assertTrue(all(len(part)<=65536 for part in bulk))
        self.assertIn(b"\xa6\x05\x01\0\0\0\0\0",hid.features)

    def test_ms9132_without_composite_pair_remains_blocked(self):
        displays=discover_community_displays(serial_candidates=[],hid_paths=[],hid_api=FakeMsHid(ms9132_edid()),
            winusb_candidates=[("ms-1","345f:9132","bulk-path")],winusb_api=FakeUsb(b""))
        self.assertFalse(displays[0].connectable);self.assertIn("unambiguous HID/bulk",displays[0].detail)

if __name__=="__main__":unittest.main()
