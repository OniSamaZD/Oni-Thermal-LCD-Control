import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import time
import zipfile

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from thermalright_lcd.diagnostics import (
    CatalogMatch, EndpointFingerprint, HardwareFingerprint, InterfaceFingerprint,
    MatchState, SafeScanner, ScanResult, inspect_support_package, peerless_vision_fixture,
)
from thermalright_lcd.help_add_display import (
    DEVICE_DETAILS, DEVICE_SELECTION, ERROR, PARTIAL_SUCCESS, SCANNING, SUCCESS,
    HelpAddDisplayDialog,
)
from thermalright_lcd.interaction_effects import apply_interaction_effects
from thermalright_lcd.themes import THEME_NAMES
from thermalright_lcd.gui import STYLE, SupportedDisplaysDialog
from thermalright_lcd.windows_metadata import WindowsDeviceMetadata, WindowsMetadataSnapshot

_APP = QApplication.instance() or QApplication([])


def app():
    return _APP


def wait_until(predicate, timeout=3000):
    end=time.monotonic()+timeout/1000
    while time.monotonic()<end:
        QApplication.processEvents()
        if predicate():return
        QTest.qWait(5)
    assert predicate()


def result(pid=0x5302, *, state=MatchState.AMBIGUOUS, transport="hid", warnings=(), access_error="", container="CONTAINER-A"):
    interface=InterfaceFingerprint(instance_id=f"IFACE-{pid:04X}",path=f"PATH-{pid:04X}",number=0,
        transport=transport,usage_page=0xFF00 if transport=="hid" else None,
        input_report_length=37 if transport=="hid" else None,output_report_length=513 if transport=="hid" else None,
        endpoints=(EndpointFingerprint(9,"out","bulk",512),) if transport=="winusb" and not access_error else (),access_error=access_error)
    fingerprint=HardwareFingerprint(0x0416,pid,0x100,f"INSTANCE-{pid:04X}",(),(),"PARENT",container,"USB",
        "HidUsb" if transport=="hid" else "WINUSB","oem.inf","Thermalright",f"Thermalright USB Display {pid:04X}",
        "PORT",(transport,),(interface,),{"identity":"OBSERVED_WINDOWS","interfaces":"OBSERVED_DESCRIPTOR"})
    match=CatalogMatch(state,("trofeo-vision-686" if pid==0x5302 else "trofeo-vision-916",),("Verified",),(transport,),
        "REQUIRED" if state is not MatchState.EXACT_IDENTITY_MATCH else "VERIFIED_BY_EXISTING_ONI_EVIDENCE",("fixture",))
    return ScanResult(fingerprint,match,tuple(warnings))


class Scanner:
    def __init__(self,results=(),error=None,delay=0):self.results=tuple(results);self.error=error;self.delay=delay
    def scan(self):
        if self.delay:time.sleep(self.delay)
        if self.error:raise self.error
        return self.results


def dialog_for(results=(), **kwargs):
    return HelpAddDisplayDialog(scanner_factory=lambda:Scanner(results),**kwargs)


def finish_scan(dialog):
    dialog.start_scan();wait_until(lambda:not dialog.scan_thread_running)


def close_dialog(dialog):
    dialog.close();wait_until(lambda:not dialog.scan_thread_running);dialog.deleteLater();QApplication.processEvents()


def test_supported_displays_has_single_native_help_entry(monkeypatch):
    app();opened=[]
    class Fake(QDialog):
        def exec(self):opened.append(True);return QDialog.Accepted
    monkeypatch.setattr("thermalright_lcd.gui.HelpAddDisplayDialog",Fake)
    dialog=SupportedDisplaysDialog()
    action=next(button for button in dialog.findChildren(QPushButton) if button.text()=="Help Add My Display")
    action.click();assert opened==[True];dialog.close()


def test_scan_runs_asynchronously_and_keeps_dialog_responsive():
    app();dialog=HelpAddDisplayDialog(scanner_factory=lambda:Scanner((result(),),delay=.08));dialog.show();dialog.start_scan()
    assert dialog.workflow_state==SCANNING and dialog.scan_thread_running
    dialog.setWindowTitle("Responsive");QApplication.processEvents();assert dialog.windowTitle()=="Responsive"
    wait_until(lambda:not dialog.scan_thread_running);assert dialog.workflow_state==DEVICE_SELECTION;close_dialog(dialog)


@pytest.mark.parametrize("items,count",[((result(),),1),((result(),result(0x5408,transport="winusb",container="CONTAINER-B")),2)])
def test_one_and_two_physical_candidates_are_independent(items,count):
    app();dialog=dialog_for(items);finish_scan(dialog);assert dialog.candidates.count()==count
    assert len({dialog.candidates.item(i).data(Qt.UserRole).fingerprint.container_id for i in range(count)})==count
    close_dialog(dialog)


def test_no_candidates_and_scan_exception_are_normal_user_errors():
    app();empty=dialog_for(());finish_scan(empty);assert empty.workflow_state==ERROR and "No likely display" in empty.error_text.text();close_dialog(empty)
    failed=HelpAddDisplayDialog(scanner_factory=lambda:Scanner(error=RuntimeError("secret traceback")));finish_scan(failed)
    assert failed.workflow_state==ERROR and "secret traceback" not in failed.error_text.text();close_dialog(failed)


@pytest.mark.parametrize("state,label",[(MatchState.UNKNOWN,"New / unknown display"),(MatchState.AMBIGUOUS,"More information required"),(MatchState.POSSIBLE_FAMILY_MATCH,"Possible known display family"),(MatchState.EXACT_IDENTITY_MATCH,"Known hardware identity")])
def test_truthful_identity_language(state,label):
    app();dialog=dialog_for((result(state=state),));finish_scan(dialog);assert label in dialog.candidates.item(0).text();close_dialog(dialog)


def test_hid_winusb_and_partial_access_denied_are_presented_as_observed_only():
    app();hid=result();usb=result(0x5408,transport="winusb",warnings=("USB metadata partial: PermissionError",),access_error="PermissionError")
    dialog=dialog_for((hid,usb));finish_scan(dialog);assert dialog.workflow_state==PARTIAL_SUCCESS
    dialog._show_state(DEVICE_SELECTION);dialog.candidates.setCurrentRow(1);dialog.show_selected_details()
    text=dialog.advanced.toPlainText();assert dialog.workflow_state==DEVICE_DETAILS
    assert "optional metadata unavailable" in text and "Catalog references (not observed hardware facts)" in text
    assert "OUT 0x09" not in text and "IN 0x81" not in text
    close_dialog(dialog)


def test_peerless_fixture_is_not_presented_as_verified_hardware():
    app();dialog=dialog_for((peerless_vision_fixture(),));finish_scan(dialog)
    text=dialog.candidates.item(0).text();assert "Possible known display family" in text and "Known hardware identity" not in text
    dialog.show_selected_details();assert "Additional protocol information may be needed" in dialog.detail_summary.text();close_dialog(dialog)


def test_public_export_roundtrip_selects_only_requested_target(tmp_path):
    app();a=result();b=result(0x5408,transport="winusb",container="CONTAINER-B")
    dialog=dialog_for((a,b),export_directory=tmp_path);finish_scan(dialog);dialog.candidates.setCurrentRow(1);dialog.show_selected_details();dialog.begin_export();wait_until(lambda:dialog.workflow_state in {SUCCESS,ERROR})
    assert dialog.workflow_state==SUCCESS
    inspected=inspect_support_package(dialog._last_package);assert inspected["manifest"]["target_count"]==1
    assert inspected["manifest"]["selected_target_identity"]==["0416:5408"]
    with zipfile.ZipFile(dialog._last_package) as archive:assert "private_report.json" not in archive.namelist()
    assert inspected["reconstructed_fingerprint_ids"]==[b.fingerprint.deterministic_id()];close_dialog(dialog)


def test_private_report_requires_explicit_opt_in(tmp_path):
    app();dialog=dialog_for((result(),),export_directory=tmp_path);finish_scan(dialog);dialog.show_selected_details();dialog.private_opt_in.setChecked(True);dialog.begin_export();wait_until(lambda:dialog.workflow_state==SUCCESS)
    with zipfile.ZipFile(dialog._last_package) as archive:assert "private_report.json" in archive.namelist()
    close_dialog(dialog)


def test_export_failure_is_actionable_and_snapshot_survives_device_disappearance(tmp_path):
    app();selected=result();seen=[]
    def exporter(items,_directory,**_kwargs):seen.extend(items);raise PermissionError("private path")
    dialog=dialog_for((selected,),export_directory=tmp_path,exporter=exporter);finish_scan(dialog);dialog.show_selected_details();dialog.begin_export();wait_until(lambda:dialog.workflow_state==ERROR)
    assert seen==[selected] and "private path" not in dialog.error_text.text();close_dialog(dialog)


def test_keyboard_selection_continue_and_advanced_toggle():
    app();dialog=dialog_for((result(),));dialog.show();finish_scan(dialog);dialog.candidates.setFocus();QTest.keyClick(dialog.candidates,Qt.Key_Return);QApplication.processEvents()
    assert dialog.workflow_state==DEVICE_DETAILS
    assert dialog.advanced_toggle.focusPolicy()!=Qt.NoFocus
    dialog.advanced_toggle.setChecked(False)
    dialog.advanced_toggle.click();QApplication.processEvents()
    assert dialog.advanced_toggle.isChecked() and not dialog.advanced.isHidden();close_dialog(dialog)


@pytest.mark.parametrize("width,height",[(1920,1080),(1600,900),(1366,768),(1280,800)])
def test_major_states_fit_supported_window_sizes(width,height):
    app();dialog=dialog_for((result(),));dialog.resize(width,height);dialog.show();QApplication.processEvents();finish_scan(dialog)
    assert dialog.rect().contains(dialog.pages.geometry().center()) and dialog.scan_again.isVisible()
    dialog.show_selected_details();QApplication.processEvents();assert dialog.export_button.isVisible() and dialog.export_button.geometry().width()>80
    close_dialog(dialog)


def test_all_themes_and_effects_modes_keep_workflow_functional():
    application=app();old=application.styleSheet()
    try:
        for theme in THEME_NAMES:
            for enabled in (False,True):
                apply_interaction_effects(application,STYLE,enabled,theme)
                dialog=dialog_for((result(),));dialog.show();finish_scan(dialog)
                assert dialog.candidates.count()==1 and dialog.scan_again.isEnabled();close_dialog(dialog)
    finally:application.setStyleSheet(old)


def test_repeated_open_scan_close_leaves_no_worker_thread():
    app();dialogs=[]
    for _ in range(6):
        dialog=HelpAddDisplayDialog(scanner_factory=lambda:Scanner((result(),),delay=.01));dialogs.append(dialog);finish_scan(dialog);close_dialog(dialog)
    assert all(not dialog.scan_thread_running for dialog in dialogs)


def test_close_during_scan_waits_for_worker_without_leaking_or_reopening():
    app();dialog=HelpAddDisplayDialog(scanner_factory=lambda:Scanner((result(),),delay=.05));dialog.show();dialog.start_scan();dialog.close()
    assert dialog.scan_thread_running and not dialog.isVisible()
    wait_until(lambda:not dialog.scan_thread_running);assert not dialog.isVisible() and dialog.result()==QDialog.Rejected
    dialog.deleteLater();QApplication.processEvents()


def test_safe_scan_integration_has_no_output_capability():
    record=WindowsDeviceMetadata(r"USB\VID_0416&PID_5302\TARGET","OK","C","HidUsb","L","P",(r"USB\VID_0416&PID_5302",),(),"USB","oem.inf","Thermalright","LCD")
    scanner=SafeScanner(lambda:WindowsMetadataSnapshot((record,)))
    forbidden=("write_report","set_feature","write_pipe","send_frame","set_brightness","initialize","open_session")
    assert all(not hasattr(scanner,name) for name in forbidden)
    app();dialog=HelpAddDisplayDialog(scanner_factory=lambda:scanner);finish_scan(dialog);assert dialog.candidates.count()==1;close_dialog(dialog)

