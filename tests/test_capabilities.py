import pytest
from thermalright_lcd.capabilities import capabilities


def test_known_devices_keep_independent_proven_capabilities():
    wide=capabilities("0416:5408");small=capabilities("0416:5302")
    assert (wide.encoded_size,wide.out_endpoint,wide.in_endpoint,wide.frame_ack_required)==((1920,462),"0x09","0x81",True)
    assert (small.encoded_size,small.out_endpoint,small.in_endpoint,small.frame_ack_required)==((1280,480),"0x02","0x83",False)
    assert wide.backend!=small.backend and not wide.dirty_region_protocol and not small.dirty_region_protocol


def test_unknown_device_remains_unknown():
    with pytest.raises(ValueError):capabilities("0416:9999")
