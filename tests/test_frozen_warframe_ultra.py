from __future__ import annotations

import json
from pathlib import Path
import struct

from thermalright_lcd.devices.thermalright_reference import (
    MODELS, build_probe, detect_model, frame_packets, parse_chizhu_init_response,
)
from thermalright_lcd.physical_display import physical_profile


FIXTURE=json.loads((Path(__file__).parent/"fixtures"/"frozen-warframe-ultra-hstones.json").read_text(encoding="utf-8"))
INIT=bytes.fromhex(FIXTURE["init_packet_hex"])
RESPONSE=bytes.fromhex(FIXTURE["init_response_hex"])


def test_hstones_capture_exact_init_and_structured_response():
    assert len(INIT)==64 and INIT==build_probe("87ad:70db","winusb")
    assert len(RESPONSE)==64
    parsed=parse_chizhu_init_response(RESPONSE)
    assert parsed.magic_valid
    assert parsed.identifier=="SSCRM-V1"
    assert (parsed.signature,parsed.pm,parsed.field_28,parsed.variant)==(0x8F5DAC52,6,32,1)
    assert (parsed.field_36,parsed.field_40,parsed.ready)==(1,2,1)


def test_capture_resolves_frozen_but_partial_or_ambiguous_evidence_fails_closed():
    resolved=detect_model("87ad:70db","winusb",RESPONSE)
    assert resolved.key=="frozen-warframe-ultra"
    assert resolved.key!="frozen-vision-v2"
    assert detect_model("87ad:70db","winusb",b"")==None
    identifier_only=bytearray(64);identifier_only[:4]=b"\x12\x34\x56\x78";identifier_only[4:12]=b"SSCRM-V1"
    identified=detect_model("87ad:70db","winusb",bytes(identifier_only))
    assert identified is None or identified.key!="frozen-warframe-ultra"
    sibling=bytearray(RESPONSE);struct.pack_into("<I",sibling,32,2)
    assert detect_model("87ad:70db","winusb",bytes(sibling)) is None
    incomplete=bytearray(RESPONSE);struct.pack_into("<I",incomplete,36,0)
    assert detect_model("87ad:70db","winusb",bytes(incomplete)) is None
    assert detect_model("87ad:70db","winusb",RESPONSE[:29]) is None


def test_existing_legacy_chizhu_discriminator_remains_compatible():
    response=bytearray(64);response[:4]=b"\x12\x34\x56\x78";response[4:12]=b"SSCRM-V3";response[24]=4;response[28]=2
    assert detect_model("87ad:70db","winusb",bytes(response)).key=="rainbow-vision-360"
    assert detect_model("87ad:70db","winusb",bytes(response[:29])).key=="rainbow-vision-360"


def test_frozen_frame_contract_matches_single_chizhu_bulk_write():
    jpeg=b"\xff\xd8community-jpeg\xff\xd9";packet,=frame_packets(MODELS["frozen-warframe-ultra"],jpeg)
    assert packet[:4]==b"\x12\x34\x56\x78"
    assert struct.unpack_from("<I",packet,4)[0]==2
    assert struct.unpack_from("<II",packet,8)==(480,480)
    assert struct.unpack_from("<I",packet,56)[0]==2
    assert struct.unpack_from("<I",packet,60)[0]==len(jpeg)
    assert packet[64:]==jpeg


def test_frozen_metadata_is_community_experimental_unknown_diagonal_and_180_degrees():
    model=MODELS["frozen-warframe-ultra"]
    assert model.community_validated and not model.physically_verified
    assert model.evidence_source=="hstones community physical capture"
    profile=physical_profile(model.key,model.native_size,model.render_size)
    assert profile.diagonal_inches is None
    assert profile.output_orientation_degrees==180


def test_fixture_endpoint_topology_is_exact_and_no_frozen_specific_sender_exists():
    assert (FIXTURE["bulk_out"],FIXTURE["bulk_in"],FIXTURE["maximum_packet_size"])==("0x01","0x81",512)
    import thermalright_lcd.devices.thermalright_reference as reference
    assert not hasattr(reference,"FrozenWarframeUltraSender")


def test_real_winusb_binder_accepts_captured_one_out_one_in_topology():
    from thermalright_lcd.devices.thermalright_reference import ConnectedPanelCandidate
    from thermalright_lcd.windows_usb import reference_winusb_connection
    class Api:
        def create_file(self,path,timeout):return 1
        def winusb_initialize(self,handle):return 2
        def query_pipe(self,usb,interface,endpoint):
            if endpoint not in (1,0x81):raise RuntimeError("absent")
            return {"endpoint":endpoint,"type":2,"maximum_packet_size":512}
        def free(self,usb):pass
        def close_handle(self,handle):pass
    candidate=ConnectedPanelCandidate("USB\\VID_87AD&PID_70DB\\FROZEN","87ad:70db","WinUSB","connected","container","{guid}","\\\\?\\usb#frozen#{guid}")
    connection=reference_winusb_connection(candidate,Api())
    assert (connection.out_endpoint,connection.in_endpoint)==("0x01","0x81")


def test_real_winusb_binder_rejects_wrong_chizhu_packet_size():
    from thermalright_lcd.devices.thermalright_reference import ConnectedPanelCandidate
    from thermalright_lcd.live_state import SafetyError
    from thermalright_lcd.windows_usb import reference_winusb_connection
    class Api:
        def create_file(self,path,timeout):return 1
        def winusb_initialize(self,handle):return 2
        def query_pipe(self,usb,interface,endpoint):
            if endpoint not in (1,0x81):raise RuntimeError("absent")
            return {"endpoint":endpoint,"type":2,"maximum_packet_size":64}
        def free(self,usb):pass
        def close_handle(self,handle):pass
    candidate=ConnectedPanelCandidate("USB\\VID_87AD&PID_70DB\\FROZEN","87ad:70db","WinUSB","connected","container","{guid}","\\\\?\\usb#frozen#{guid}")
    import pytest
    with pytest.raises(SafetyError,match="512-byte"):
        reference_winusb_connection(candidate,Api())


def test_runtime_binding_uses_generic_chizhu_sender_contract_and_profile_orientation():
    from thermalright_lcd.devices.registry import device_definition
    from thermalright_lcd.media import MediaPipeline
    from thermalright_lcd.reference_runtime import install_reference_binding,remove_reference_binding
    binding=install_reference_binding("community-frozen",MODELS["frozen-warframe-ultra"],lambda:object())
    try:
        definition=device_definition(binding.device_id)
        assert definition.orientation=="rotation-180"
        assert definition.support_status=="Implemented — community tested; ONI hardware validation pending"
        assert MediaPipeline._output_rotation(binding.device_id)==180
    finally:remove_reference_binding(binding.device_id)


def test_generic_connection_initializes_once_then_sends_frame_without_response_dependency():
    from thermalright_lcd.devices.thermalright_reference import ReferencePanelConnection
    class Transport:
        def __init__(self):self.writes=[];self.reads=0
        def open(self,timeout):pass
        def write(self,endpoint,data,timeout):self.writes.append((endpoint,data));return len(data)
        def read(self,endpoint,length,timeout):self.reads+=1;return RESPONSE
        def close(self,timeout):pass
    transport=Transport();connection=ReferencePanelConnection("87ad:70db","winusb",transport,"0x01","0x81")
    assert connection.open().key=="frozen-warframe-ultra"
    jpeg=b"\xff\xd8frame\xff\xd9"
    assert connection.send(jpeg)==64+len(jpeg)
    assert transport.writes[0]==("0x01",INIT)
    assert transport.writes[1][0]=="0x01" and transport.writes[1][1][64:]==jpeg
    assert transport.reads==1
