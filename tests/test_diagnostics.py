import json
from pathlib import Path
import zipfile

import pytest

from thermalright_lcd import __version__
from thermalright_lcd.diagnostics import (EndpointFingerprint, Evidence, HardwareFingerprint,
    InterfaceFingerprint, MatchState, Redactor, SafeScanner, export_support_package,
    inspect_support_package, match_catalog, peerless_vision_fixture)
from thermalright_lcd.windows_metadata import WindowsDeviceMetadata, WindowsMetadataSnapshot
from thermalright_lcd.windows_metadata import collect_windows_metadata_snapshot


def record(vid="0416",pid="5302",*,suffix="SERIAL",service="HidUsb",cls="USB",container="{C}",parent="USB\\ROOT",description="LCD"):
    instance=fr"USB\VID_{vid}&PID_{pid}\{suffix}"
    return WindowsDeviceMetadata(instance,"OK",container,service,"PCIROOT#USBROOT(0)#USB(1)",parent,
        (fr"USB\VID_{vid}&PID_{pid}&REV_0100",),("USB\\Class_FF",),cls,"oem42.inf","Thermalright",description)


def scanner_for(*items,**kwargs):return SafeScanner(lambda:WindowsMetadataSnapshot(tuple(items)),**kwargs)


@pytest.mark.parametrize("pid,service,expected",[("5302","HidUsb","hid"),("5408","WINUSB","winusb")])
def test_reviewed_shared_identity_fixtures_remain_ambiguous_without_discriminator(pid,service,expected):
    result=scanner_for(record(pid=pid,service=service)).scan()[0]
    assert result.fingerprint.transport_types[0]==expected
    assert result.match.state is MatchState.AMBIGUOUS
    assert result.match.protocol_verification=="REQUIRED"


def test_peerless_reference_remains_unverified():
    result=peerless_vision_fixture()
    assert result.fingerprint.vid_pid=="87ad:70db"
    assert result.match.state in {MatchState.POSSIBLE_FAMILY_MATCH,MatchState.AMBIGUOUS}
    assert result.match.protocol_verification=="REQUIRED"
    assert result.fingerprint.provenance["physical_resolution"]==Evidence.UNKNOWN.value
    assert any("ChiZhu" in warning for warning in result.warnings)


def test_peerless_fixture_encodes_reference_evidence_only():
    fixture=json.loads((Path(__file__).parent/"fixtures"/"peerless-vision-360.json").read_text())
    assert fixture["internal_key"]=="peerless-vision-360"
    assert fixture["identity"]["vid_pid"]=="87ad:70db"
    assert fixture["possible_protocol"]=={"value":"ChiZhu","provenance":"CATALOG_REFERENCE","verification":"REQUIRED"}
    assert fixture["physical_resolution"]=={"value":None,"provenance":"UNKNOWN","verification":"NONE"}


def test_shared_vid_pid_is_ambiguous():
    result=scanner_for(record(vid="1A86",pid="5722",service="usbser")).scan()[0]
    assert result.match.state is MatchState.AMBIGUOUS


def test_generic_hid_and_winusb_candidates_and_unknown_match():
    hid=scanner_for(record(vid="1234",pid="5678",service="HidUsb",cls="HIDClass")).scan()[0]
    usb=scanner_for(record(vid="1234",pid="5679",service="WinUSB")).scan()[0]
    assert hid.fingerprint.transport_types==("hid",) and usb.fingerprint.transport_types==("winusb",)
    assert hid.match.state is MatchState.UNKNOWN and usb.match.state is MatchState.UNKNOWN


def test_composite_container_scopes_children():
    root=record(pid="5408",service="usbccgp",container="{SAME}")
    child=record(pid="5408",suffix="IFACE",service="WinUSB",container="{SAME}",parent=root.instance_id)
    result=scanner_for(root,child).scan()[0]
    assert "generic-usb" in result.fingerprint.transport_types and "winusb" in result.fingerprint.transport_types


def test_partial_metadata_and_missing_container_are_accepted():
    item=record(container="",service="WinUSB",description="")
    result=scanner_for(item).scan()[0]
    assert result.fingerprint.container_id=="" and result.fingerprint.description==""


def test_access_denied_hid_is_partial_not_fatal():
    item=record()
    path=r"\\?\hid#vid_0416&pid_5302&mi_00#SERIAL"
    result=scanner_for(item,hid_enumerator=lambda:[path],hid_inspector=lambda _p:(_ for _ in ()).throw(PermissionError())) .scan()[0]
    assert result.fingerprint.interfaces[0].access_error=="PermissionError"
    assert result.warnings


def test_multiple_candidates_and_unrelated_exclusion():
    lcd=record();other=record(vid="9999",pid="0001",service="kbdhid",cls="Keyboard",description="Keyboard")
    second=record(vid="1234",pid="5678",service="WinUSB",suffix="B")
    candidates=scanner_for(lcd,other,second).candidates()
    assert {item.instance_id for item in candidates}=={lcd.instance_id,second.instance_id}


def test_usb_billboard_is_not_misclassified_as_a_display_candidate():
    billboard=record(vid="2109",pid="8884",service="WinUSB",description="USB Billboard Device")
    assert scanner_for(billboard).candidates()==()


def test_explicit_diagnostic_snapshot_uses_broad_usb_enumerator():
    class Api:
        def enumerate_present_devices(self):raise AssertionError("normal narrow discovery should not be selected")
        def enumerate_present_usb_devices(self):return ({"instance_id":record(vid="1234",pid="5678").instance_id,"status":"OK"},)
    snapshot=collect_windows_metadata_snapshot(Api(),diagnostic_candidates=True)
    assert snapshot.devices[0].vid_pid=="1234:5678"


def test_selection_scopes_one_target():
    a=record();b=record(pid="5408",suffix="B",service="WinUSB")
    results=scanner_for(a,b).scan(b.instance_id)
    assert len(results)==1 and results[0].fingerprint.pid==0x5408


def test_hid_descriptor_metadata_and_provenance():
    class Info:
        usage_page=0xFF00;usage=1;input_report_bytes=37;output_report_bytes=513;feature_report_bytes=0
    path=r"\\?\hid#vid_0416&pid_5302&mi_00#SERIAL"
    result=scanner_for(record(),hid_enumerator=lambda:[path],hid_inspector=lambda _:Info()).scan()[0]
    interface=result.fingerprint.interfaces[0]
    assert (interface.usage_page,interface.output_report_length)==(0xFF00,513)
    assert result.fingerprint.provenance["interfaces"]==Evidence.OBSERVED_DESCRIPTOR.value


def test_endpoint_fingerprint_is_deterministic_and_machine_fields_are_excluded():
    def fp(path):return HardwareFingerprint(1,2,3,path,(),(),"P","C","USB","WINUSB","","M","D","LOC",("winusb",),
        (InterfaceFingerprint(path=path,number=0,transport="winusb",endpoints=(EndpointFingerprint(9,"out","bulk",512),)),),{})
    assert fp("machine-a").deterministic_id()==fp("machine-b").deterministic_id()


def test_redaction_is_consistent_and_preserves_protocol_values():
    redactor=Redactor();fp=HardwareFingerprint(0x416,0x5302,None,"SERIAL","",(),"SERIAL","GUID","USB","HIDUSB","","M","D","PORT",("hid",),(),{})
    public=redactor.public_fingerprint(fp)
    assert public["instance_id"]==redactor.token("INSTANCE","SERIAL")
    assert public["container_id"]!="GUID" and public["vid"]==0x416 and public["pid"]==0x5302


def test_public_package_manifest_checksums_and_roundtrip(tmp_path):
    result=scanner_for(record()).scan()[0]
    package=export_support_package((result,),tmp_path)
    inspected=inspect_support_package(package)
    assert inspected["manifest"]["oni_version"]==__version__
    assert inspected["manifest"]["active_write_operations_performed"] is False
    assert inspected["manifest"]["private_report_included"] is False
    assert inspected["reconstructed_fingerprint_ids"]==[result.fingerprint.deterministic_id()]
    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist())=={"manifest.json","public_report.json","README.txt","checksums.sha256"}
        assert b"SERIAL" not in archive.read("public_report.json")


def test_optional_private_report_requires_explicit_flag(tmp_path):
    package=export_support_package(scanner_for(record()).scan(),tmp_path,include_private=True)
    with zipfile.ZipFile(package) as archive:
        assert "private_report.json" in archive.namelist()
        assert b"SERIAL" in archive.read("private_report.json")


def rewrite_zip(path,entries):
    with zipfile.ZipFile(path,"w") as archive:
        for name,data in entries.items():archive.writestr(name,data)


def test_malformed_package_rejected(tmp_path):
    path=tmp_path/"bad.zip";rewrite_zip(path,{"manifest.json":"{"})
    with pytest.raises(ValueError):inspect_support_package(path)


def test_zip_traversal_rejected(tmp_path):
    path=tmp_path/"bad.zip";rewrite_zip(path,{"../escape":"x"})
    with pytest.raises(ValueError,match="unsafe"):inspect_support_package(path)


def test_oversized_untrusted_member_rejected(tmp_path,monkeypatch):
    path=tmp_path/"big.zip";rewrite_zip(path,{"manifest.json":"x"*1024})
    monkeypatch.setattr("thermalright_lcd.diagnostics.MAX_MEMBER_BYTES",100)
    with pytest.raises(ValueError,match="size limit"):inspect_support_package(path)


def test_no_write_surface_is_reachable():
    scanner=SafeScanner(lambda:WindowsMetadataSnapshot((record(),)))
    forbidden={"write_report","set_feature","write_pipe","serial_write","scsi_command","send_frame","brightness","initialize"}
    assert forbidden.isdisjoint(set(dir(scanner)))


def test_protocol_compatibility_is_separate_from_identity():
    result=scanner_for(record(vid="87AD",pid="70DB",service="WinUSB")).scan()[0]
    assert result.fingerprint.vid_pid=="87ad:70db"
    assert result.match.protocol_verification=="REQUIRED"
