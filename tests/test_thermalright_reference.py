from __future__ import annotations

import struct
import unittest
from PIL import Image

from thermalright_lcd.devices.thermalright_reference import (
    MODELS, SUPPORTED_VID_PIDS, ReferencePanelConnection, build_probe, build_scsi_cdb, detect_model, frame_packets, parse_connected_candidates,
)
from thermalright_lcd.devices.catalog import classify_catalog_descriptor


class ThermalrightReferenceTests(unittest.TestCase):
    def test_reference_vid_pids_and_existing_models(self):
        self.assertTrue({"0416:5408","0416:5302","0416:5409","0416:5406","87ad:70db","87cd:70db","0402:3922","0418:5303","0418:5304"}.issubset(SUPPORTED_VID_PIDS))
        self.assertTrue(MODELS["trofeo-vision-916"].physically_verified)
        self.assertTrue(MODELS["trofeo-vision-686"].physically_verified)
        self.assertFalse(MODELS["lm24"].physically_verified)

    def test_trofeo_hid_detection_is_exact_and_fail_closed(self):
        response=bytearray(37);response[:4]=b"\xda\xdb\xdc\xdd";response[5]=0x80;response[4]=0
        self.assertEqual(detect_model("0416:5302","hid",bytes(response)).key,"trofeo-vision-686")
        response[5]=0x3A;self.assertEqual(detect_model("0416:5302","hid",bytes(response)).key,"frozen-warframe-se")
        response[4]=9;self.assertEqual(detect_model("0416:5302","hid",bytes(response)).key,"lm26")
        response[5]=0xFF;self.assertIsNone(detect_model("0416:5302","hid",bytes(response)))
        self.assertIsNone(detect_model("0416:5302","winusb",bytes(response)))

    def test_trofeo_bulk_variants(self):
        for marker,key in ((1,"trofeo-vision-916"),(2,"trofeo-vision-916-v2"),(3,"trofeo-vision-916-v2"),(5,"trofeo-vision-113")):
            response=bytearray(512);response[:2]=b"\x03\xff";response[8]=1;response[20]=marker
            self.assertEqual(detect_model("0416:5408","winusb",bytes(response)).key,key)
        response[20]=9;self.assertIsNone(detect_model("0416:5408","winusb",bytes(response)))

    def test_chizhu_pm_sub_identifier_and_booting(self):
        response=bytearray(1024);response[4:12]=b"SSCRM-V3";response[24]=4;response[28]=2
        self.assertEqual(detect_model("87ad:70db","winusb",bytes(response)).key,"rainbow-vision-360")
        response[4:12]=b"UNKNOWN\0";response[24]=65;response[28]=4
        self.assertEqual(detect_model("87ad:70db","winusb",bytes(response)).key,"ld10")
        response[4:8]=b"\xa1\xa2\xa3\xa4";self.assertIsNone(detect_model("87ad:70db","winusb",bytes(response)))

    def test_unknown_and_ambiguous_devices_fail_closed(self):
        self.assertIsNone(detect_model("ffff:ffff","winusb",bytes(64)))
        self.assertIsNone(detect_model("0416:5406","winusb",bytes(64)))
        self.assertIsNone(detect_model("0418:5303","hid",bytes(64)))
        classified=classify_catalog_descriptor(0x87AD,0x70DB,transport="winusb")
        self.assertEqual(classified.family_ids,("thermalright-reference-panels",));self.assertFalse(classified.output_authorized);self.assertIsNone(classified.selected_adapter)

    def test_probe_packets(self):
        self.assertEqual(len(build_probe("0416:5302","hid")),512)
        self.assertEqual(build_probe("0416:5408","winusb")[:2],b"\x02\xff")
        probe=build_probe("87ad:70db","winusb");self.assertEqual(probe[:4],b"\x12\x34\x56\x78");self.assertEqual(struct.unpack_from("<I",probe,56)[0],1)

    def test_trofeo_frame_construction(self):
        model=MODELS["frozen-warframe-se"];payload=bytes(model.render_size[0]*model.render_size[1]*2)
        packets=frame_packets(model,payload);self.assertTrue(all(len(p)==512 for p in packets));self.assertEqual(packets[0][:4],b"\xda\xdb\xdc\xdd")
        self.assertEqual(packets[0][6],1);self.assertEqual(struct.unpack_from("<HH",packets[0],8),model.render_size)
        with self.assertRaises(ValueError):frame_packets(model,payload[:-1])

    def test_chizhu_and_scsi_frame_construction(self):
        packets=frame_packets(MODELS["core-vision"],b"jpeg");self.assertEqual(packets[0][:4],b"\x12\x34\x56\x78");self.assertEqual(packets[0][64:],b"jpeg");self.assertEqual(struct.unpack_from("<I",packets[0],60)[0],4)
        model=MODELS["elite-vision-scsi"];payload=bytes(model.render_size[0]*model.render_size[1]*2);packets=frame_packets(model,payload)
        self.assertGreater(len(packets),1);self.assertEqual(packets[0][:20],build_scsi_cdb(0x101F5,0x10000))
        cdb=build_scsi_cdb(0xF5,0xE100);self.assertEqual(len(cdb),20);self.assertEqual(struct.unpack_from("<I",cdb)[0],0xF5)

    def test_ly1_and_ali_detection_and_frames(self):
        response=bytearray(511);response[:2]=b"\x03\xff";response[8]=1
        model=detect_model("0416:5409","winusb",bytes(response));self.assertEqual(model.key,"trofeo-vision-916-ly1")
        jpeg=b"x"*700;packets=frame_packets(model,jpeg);self.assertEqual(len(packets),2);self.assertEqual(packets[0][8],2)
        ali=bytearray(1024);ali[0]=54;model=detect_model("0416:5406","winusb",bytes(ali));self.assertEqual(model.key,"ali-vision-320x240")
        pixels=bytes(320*240*2);packet=frame_packets(model,pixels)[0];self.assertEqual(packet[:8],bytes.fromhex("f5010100bcffb6c8"));self.assertEqual(struct.unpack_from("<I",packet,12)[0],len(pixels))

    def test_bound_connection_initializes_identifies_sends_and_reads_ack(self):
        class Transport:
            def __init__(self):self.writes=[];self.closed=0
            def open(self,_):pass
            def write(self,endpoint,data,_):self.writes.append((endpoint,data));return len(data)
            def read(self,endpoint,length,_):
                if length==1024:
                    response=bytearray(length);response[0]=54;return bytes(response)
                return bytes([1])*length
            def close(self,_):self.closed+=1
        transport=Transport();connection=ReferencePanelConnection("0416:5406","winusb",transport,"0x02","0x81")
        self.assertEqual(connection.open().key,"ali-vision-320x240")
        payload=bytes(320*240*2);self.assertEqual(connection.send(payload),16+len(payload));self.assertEqual(len(transport.writes),2)
        connection.close();self.assertEqual(transport.closed,1)

    def test_connected_displays_come_only_from_physical_enumeration(self):
        payload='[{"instance_id":"USB\\\\VID_0416&PID_5409\\\\REAL","status":"OK","service":"WinUSB"},{"instance_id":"USB\\\\VID_87AD&PID_70DB\\\\GONE","status":"Unknown","service":"WinUSB"},{"instance_id":"USB\\\\VID_FFFF&PID_FFFF\\\\OTHER","status":"OK","service":"WinUSB"}]'
        found=parse_connected_candidates(payload);self.assertEqual(len(found),1);self.assertEqual(found[0].vid_pid,"0416:5409")
        self.assertNotIn("0416:5408",{item.vid_pid for item in found})

    def test_dynamic_media_pipeline_routes_jpeg_and_rgb565(self):
        from thermalright_lcd.reference_runtime import install_reference_binding,remove_reference_binding
        from thermalright_lcd.media import MediaPipeline
        a=install_reference_binding("mock-core",MODELS["core-vision"],lambda:None);b=install_reference_binding("mock-ali",MODELS["ali-vision-320x240"],lambda:None)
        pipeline=MediaPipeline();pipeline.register_target(a.device_id,(480,480));pipeline.register_target(b.device_id,(320,240))
        image=Image.new("RGB",(32,32),(255,0,0))
        prepared,jpeg_frame=pipeline.prepare_image(image,a.device_id);self.assertEqual(jpeg_frame.dimensions,(480,480));self.assertTrue(jpeg_frame.writes[0].startswith(b"\x12\x34\x56\x78"));prepared.canvas.close()
        prepared,rgb_frame=pipeline.prepare_image(image,b.device_id);self.assertEqual(rgb_frame.dimensions,(320,240));self.assertEqual(len(rgb_frame.writes[0]),16+320*240*2);prepared.canvas.close();image.close();remove_reference_binding(a.device_id);remove_reference_binding(b.device_id)

    def test_physical_candidate_creates_dynamic_definition_session_sender(self):
        from thermalright_lcd.device_discovery import resolve_reference_candidates
        from thermalright_lcd.reference_runtime import reference_binding,remove_reference_binding
        from thermalright_lcd.runtime import DisplaySession
        from thermalright_lcd.devices.thermalright_reference import ConnectedPanelCandidate
        class Connection:
            def __init__(self):self.closed=0
            def open(self):return MODELS["lm24"]
            def close(self):self.closed+=1
            def __call__(self,frame):return frame.total_bytes
        candidates=(ConnectedPanelCandidate("USB\\VID_87AD&PID_70DB\\REAL","87ad:70db","WinUSB","connected"),)
        found=resolve_reference_candidates(candidates,lambda _:Connection());self.assertEqual(len(found),1);self.assertTrue(found[0].connectable);self.assertIn("LM24",found[0].definition.model)
        sender=reference_binding(found[0].device_id).sender_factory();session=DisplaySession(found[0].device_id,sender,refresh_interval=.1);self.assertIsNotNone(session);remove_reference_binding(found[0].device_id)

    def test_real_winusb_binder_uses_enumerated_interface_and_exact_pipes(self):
        from thermalright_lcd.windows_usb import reference_winusb_connection
        from thermalright_lcd.devices.thermalright_reference import ConnectedPanelCandidate
        class Api:
            def create_file(self,p,t):return 1
            def winusb_initialize(self,h):return 2
            def query_pipe(self,u,i,ep):
                if ep not in (2,0x81):raise RuntimeError()
                return {"endpoint":ep,"type":2,"maximum_packet_size":512}
            def free(self,u):pass
            def close_handle(self,h):pass
        c=ConnectedPanelCandidate("USB\\VID_0416&PID_5409\\REAL","0416:5409","WinUSB","connected","container","{guid}","\\\\?\\usb#real#{guid}")
        connection=reference_winusb_connection(c,Api());self.assertEqual(connection.out_endpoint,"0x02");self.assertEqual(connection.in_endpoint,"0x81")


if __name__ == "__main__":
    unittest.main()
