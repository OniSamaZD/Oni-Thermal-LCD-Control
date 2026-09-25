from PIL import Image

from thermalright_lcd.devices.beadapanel_protocol import encode_rgb565, ones_complement_checksum, panel_link_start_tag
from thermalright_lcd.devices.catalog import classify_catalog_descriptor, identify_catalog_device


def test_beadapanel_exact_read_only_descriptor_match():
    family=identify_catalog_device(0x4E58,0x1001,interface=0,endpoints={0x01,0x02,0x82})
    assert family and family.family_id=="beadapanel" and family.output_enabled
    classification=classify_catalog_descriptor(0x4E58,0x1001,interface=0,endpoints={0x01,0x02,0x82})
    assert classification and not classification.output_authorized
    assert identify_catalog_device(0x4E58,0x1001,interface=1,endpoints={0x01,0x02,0x82}) is None
    assert identify_catalog_device(0x4E58,0x1001,interface=0,endpoints={0x01}) is None
    assert identify_catalog_device(0x4E58,0x9999,interface=0,endpoints={0x01,0x02,0x82}) is None
    assert identify_catalog_device(0x4E58,0x1002,interface=0,endpoints={0x01,0x02,0x82}) is not None


def test_read_only_catalog_classification_never_authorizes_community_hardware():
    beada=classify_catalog_descriptor(0x4E58,0x1001,interface=0,endpoints={1,2,0x82},transport="winusb")
    assert beada.selected_adapter=="beadapanel" and not beada.output_authorized
    incomplete=classify_catalog_descriptor(0x4E58,0x1001,interface=0,endpoints={1})
    assert incomplete.selected_adapter is None and not incomplete.output_authorized
    ax206=classify_catalog_descriptor(0x1908,0x0102,interface=0,endpoints={1,0x81})
    assert ax206.selected_adapter=="ax206-diagnostic" and not ax206.output_authorized
    ambiguous=classify_catalog_descriptor(0x1A86,0x5722,interface=0,endpoints=set(),transport="serial")
    assert len(ambiguous.family_ids)==2 and ambiguous.selected_adapter is None and not ambiguous.output_authorized
    assert classify_catalog_descriptor(0x1234,0x5678,interface=0,endpoints={1}) is None


def test_beadapanel_panel_link_start_tag_is_bounded_and_checksummed():
    tag=panel_link_start_tag(1280,480,protocol_version=2,pixel_format="BGR16")
    assert len(tag)==270 and tag.startswith(b"PANEL-LINK\x02\x05")
    assert b"format=BGR16" in tag and b"width=1280" in tag
    assert int.from_bytes(tag[-2:],"little")==ones_complement_checksum(tag[:-2])


def test_beadapanel_rgb_and_bgr565_are_exact_and_frame_size_is_bounded():
    image=Image.new("RGB",(2,1));image.putdata([(255,0,0),(0,0,255)])
    rgb=encode_rgb565(image,(2,1),order="RGB");bgr=encode_rgb565(image,(2,1),order="BGR");image.close()
    assert rgb==bytes.fromhex("00f8 1f00") and bgr==bytes.fromhex("1f00 00f8")
    frame=encode_rgb565(Image.new("RGB",(4,3),"black"),(4,3));assert len(frame)==4*3*2
