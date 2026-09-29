import json
from unittest.mock import Mock

import pytest

from thermalright_lcd.live_state import DeviceDisconnected, SafetyError
from thermalright_lcd.windows_metadata import (
    GUID,
    _decode_device_property,
    collect_windows_metadata_snapshot,
    parse_windows_metadata_snapshot,
)


def record(instance_id, container="container", service="WINUSB", status="OK", location="port"):
    return {"instance_id":instance_id,"container_id":container,"service":service,"status":status,"location":location,
            "parent":"parent","hardware_ids":["hardware"],"compatible_ids":["compatible"],"class_name":"USB"}


def test_snapshot_is_collected_once_and_repeated_lookup_has_no_subprocess():
    api=Mock();api.enumerate_present_devices.return_value=(record(r"USB\VID_0416&PID_5408\ONE"),)
    snapshot=collect_windows_metadata_snapshot(api)
    assert snapshot.exact(r"USB\VID_0416&PID_5408\ONE") is snapshot.exact(r"usb\vid_0416&pid_5408\one")
    assert snapshot.for_vid_pid("0416:5408")[0].container_id=="container"
    api.enumerate_present_devices.assert_called_once()


def test_new_discovery_transaction_collects_a_fresh_snapshot_and_sees_topology_change():
    api=Mock();api.enumerate_present_devices.side_effect=[(record(r"USB\VID_0416&PID_5408\ONE"),),(record(r"USB\VID_0416&PID_5302\TWO",service="HIDUSB"),)]
    first=collect_windows_metadata_snapshot(api);second=collect_windows_metadata_snapshot(api)
    assert first.for_vid_pid("0416:5408") and not first.for_vid_pid("0416:5302")
    assert second.for_vid_pid("0416:5302") and not second.for_vid_pid("0416:5408")
    assert api.enumerate_present_devices.call_count==2


def test_snapshot_preserves_distinct_same_vid_pid_physical_identities():
    snapshot=parse_windows_metadata_snapshot(json.dumps([record(r"USB\VID_0416&PID_5408\ONE","c1"),record(r"USB\VID_0416&PID_5408\TWO","c2")]))
    assert {item.container_id for item in snapshot.for_vid_pid("0416:5408")}=={"c1","c2"}


def test_physical_roots_exclude_composite_child_interfaces():
    snapshot=parse_windows_metadata_snapshot(json.dumps([record(r"USB\VID_0416&PID_5302\ROOT"),record(r"USB\VID_0416&PID_5302&MI_00\CHILD")]))
    assert [item.instance_id for item in snapshot.physical_roots("0416:5302")]==[r"USB\VID_0416&PID_5302\ROOT"]


@pytest.mark.parametrize("payload", ["not-json", json.dumps([{"status":"OK"}]), json.dumps([record(r"USB\VID_0416&PID_5408\ONE"),record(r"USB\VID_0416&PID_5408\ONE")])])
def test_malformed_incomplete_or_ambiguous_snapshot_fails_closed(payload):
    with pytest.raises(SafetyError):parse_windows_metadata_snapshot(payload)


def test_missing_snapshot_identity_fails_closed():
    snapshot=parse_windows_metadata_snapshot("[]")
    with pytest.raises(DeviceDisconnected):snapshot.exact(r"USB\VID_0416&PID_5408\MISSING")


def test_native_snapshot_success_normalizes_all_consumed_properties():
    class Api:
        def enumerate_present_devices(self):return (record(r"USB\VID_0416&PID_5408\ONE","{ABCDEFAB-1234-5678-9ABC-DEF012345678}",location="path-a|path-b"),)
    item=collect_windows_metadata_snapshot(Api()).devices[0]
    assert item.instance_id==r"USB\VID_0416&PID_5408\ONE";assert item.status=="OK"
    assert item.container_id=="{ABCDEFAB-1234-5678-9ABC-DEF012345678}";assert item.parent=="parent"
    assert item.service=="WINUSB";assert item.location=="path-a|path-b";assert item.hardware_ids==("hardware",)
    assert item.compatible_ids==("compatible",);assert item.class_name=="USB"


def test_native_snapshot_is_fresh_per_transaction_and_has_no_global_cache():
    class Api:
        def __init__(self):self.calls=0
        def enumerate_present_devices(self):
            self.calls+=1;return (record(rf"USB\VID_0416&PID_5408\GEN{self.calls}"),)
    api=Api();first=collect_windows_metadata_snapshot(api);second=collect_windows_metadata_snapshot(api)
    assert first.devices[0].instance_id.endswith("GEN1");assert second.devices[0].instance_id.endswith("GEN2");assert api.calls==2


def test_native_api_error_is_fail_closed():
    class Api:
        def enumerate_present_devices(self):raise OSError(5,"denied")
    with pytest.raises(DeviceDisconnected):collect_windows_metadata_snapshot(Api())


def test_native_string_string_list_and_guid_decoding():
    assert _decode_device_property("WINUSB\0".encode("utf-16-le"),0x12)=="WINUSB"
    assert _decode_device_property("one\0two\0\0".encode("utf-16-le"),0x2012)==("one","two")
    guid=GUID.parse("{819C9B1F-272B-5523-91CD-BDC7075C48E5}")
    assert _decode_device_property(bytes(guid),0x0D)=="{819C9B1F-272B-5523-91CD-BDC7075C48E5}"
    with pytest.raises(ValueError):_decode_device_property(b"short",0x0D)
    with pytest.raises(ValueError):_decode_device_property(b"",0x99)


def test_native_duplicate_or_missing_required_identity_is_fail_closed():
    duplicate=record(r"USB\VID_0416&PID_5408\ONE")
    class DuplicateApi:
        def enumerate_present_devices(self):return (duplicate,duplicate)
    class MissingApi:
        def enumerate_present_devices(self):return ({"instance_id":"","status":""},)
    with pytest.raises(SafetyError):collect_windows_metadata_snapshot(DuplicateApi())
    with pytest.raises(SafetyError):collect_windows_metadata_snapshot(MissingApi())
