import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_discovery import DiscoveredDisplay
from thermalright_lcd.devices.thermalright_reference import enumerate_connected_candidates
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.windows_metadata import parse_windows_metadata_snapshot


class Sender:
    enabled=False
    def close(self):pass

def wait_until(app,predicate,timeout=2):
    deadline=time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert predicate()

def make_window(provider,startup_discovery=None):
    app=QApplication.instance() or QApplication([])
    folder=tempfile.TemporaryDirectory();environment=patch.dict(os.environ,{"LOCALAPPDATA":folder.name});sender=patch("thermalright_lcd.gui.build_gui_sender",return_value=Sender())
    environment.start();sender.start();window=MainWindow(discovery_provider=provider,startup_discovery=startup_discovery)
    return app,window,(folder,environment,sender)

def cleanup(window,resources):
    window.shutdown();resources[2].stop();resources[1].stop();resources[0].cleanup()

def test_zero_device_scan_is_async_responsive_and_stable():
    gate=threading.Event();calls=[]
    def provider():calls.append(1);return () if len(calls)==1 else (gate.wait(1),())[1]
    app,window,resources=make_window(provider);ticks=[];QTimer.singleShot(10,lambda:ticks.append(True))
    started=time.perf_counter();assert window.scan_for_displays();assert time.perf_counter()-started<.1;assert window.scan_for_displays()
    wait_until(app,lambda:bool(ticks));assert not window.cards;assert window.display_empty_state.isVisible() or not window.isVisible()
    gate.set();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);assert window.display_count_label.text()=="Displays: 0 connected";cleanup(window,resources)

def test_successful_repeated_scan_reconciles_without_duplicate_session():
    observations=[]
    app,window,resources=make_window(lambda:tuple(observations));observations.append(DiscoveredDisplay("one","0416:5408"))
    assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);card=window.cards[0]
    assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);assert window.cards==[card]
    observations.clear();assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);assert window.cards==[];cleanup(window,resources)

def test_side_by_side_selected_before_async_discovery_balances_after_insert_and_rescan():
    observations=(DiscoveredDisplay("one","0416:5408"),DiscoveredDisplay("two","0416:5302"))
    app,window,resources=make_window(lambda:observations,startup_discovery=False);window.resize(1280,800);window.show();window.open_display_workspace();window.set_display_layout("side_by_side")
    assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);wait_until(app,lambda:len(window.cards)==2)
    available=window.display_splitter.width()-window.display_splitter.handleWidth();widths=[card.width() for card in window.cards]
    assert min(widths)>=int((available/2)*.90);assert max(widths)-min(widths)<=max(2,int(available*.02))
    cards=tuple(window.cards);sessions=tuple(card.session for card in cards)
    assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None)
    assert tuple(window.cards)==cards;assert tuple(card.session for card in window.cards)==sessions
    widths=[card.width() for card in window.cards];assert min(widths)>=int((available/2)*.90);assert max(widths)-min(widths)<=max(2,int(available*.02));cleanup(window,resources)

def test_worker_error_preserves_existing_session_and_recovers_button():
    calls=0
    def provider():
        nonlocal calls;calls+=1
        if calls>1:raise RuntimeError("synthetic PnP failure")
        return (DiscoveredDisplay("one","0416:5408"),)
    app,window,resources=make_window(provider);card=window.cards[0]
    with patch("thermalright_lcd.gui.QMessageBox.warning",return_value=None) as warning:
        assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);warning.assert_called_once()
    assert window.cards==[card];assert window.display_count_label.text()=="Displays: 1 connected";cleanup(window,resources)

def test_shutdown_while_worker_is_active_does_not_block():
    gate=threading.Event();calls=0
    def provider():
        nonlocal calls;calls+=1
        if calls==1:return ()
        gate.wait(1);return ()
    app,window,resources=make_window(provider);assert window.scan_for_displays();started=time.perf_counter();window.shutdown();assert time.perf_counter()-started<.2
    gate.set();time.sleep(.02);app.processEvents();resources[2].stop();resources[1].stop();resources[0].cleanup()

def test_startup_shell_exists_while_discovery_worker_is_blocked():
    gate=threading.Event()
    def provider():gate.wait(1);return ()
    app=QApplication.instance() or QApplication([]);folder=tempfile.TemporaryDirectory();environment=patch.dict(os.environ,{"LOCALAPPDATA":folder.name});sender=patch("thermalright_lcd.gui.build_gui_sender",return_value=Sender())
    environment.start();sender.start();started=time.perf_counter();window=MainWindow(discovery_provider=provider,startup_discovery=True)
    assert time.perf_counter()-started<.5;assert window.display_count_label.text()=="Displays: scanning…";app.processEvents();assert window._display_scan_thread is not None
    gate.set();wait_until(app,lambda:window._display_scan_thread is None);cleanup(window,(folder,environment,sender))

def test_late_older_generation_cannot_replace_newer_scan_result():
    first_gate=threading.Event();lock=threading.Lock();calls=0
    def provider():
        nonlocal calls
        with lock:calls+=1;call=calls
        if call==1:first_gate.wait(1)
        return (DiscoveredDisplay("old" if call==1 else "new","0416:5408"),)
    app,window,resources=make_window(provider,startup_discovery=False);assert window.scan_for_displays();assert window.scan_for_displays()
    wait_until(app,lambda:window._display_scan_thread is None);assert set(window.card_by_physical_id)=={"new"}
    first_gate.set();wait_until(app,lambda:not window._display_scan_threads);assert set(window.card_by_physical_id)=={"new"};cleanup(window,resources)

def test_result_emitted_after_shutdown_is_ignored():
    gate=threading.Event()
    app,window,resources=make_window(lambda:(gate.wait(1),(DiscoveredDisplay("late","0416:5408"),))[1],startup_discovery=False);assert window.scan_for_displays();window.shutdown();gate.set()
    wait_until(app,lambda:not window._display_scan_threads);assert not window.cards;resources[2].stop();resources[1].stop();resources[0].cleanup()

def test_native_thermalright_enumerator_zero_malformed_and_timeout_are_safe():
    snapshot=parse_windows_metadata_snapshot("[]")
    assert enumerate_connected_candidates(path_enumerator=lambda ids:(),snapshot=snapshot)==()
    assert enumerate_connected_candidates(path_enumerator=lambda ids:(("87ad:70db","malformed"),),snapshot=snapshot)==()
    path=r"\\?\usb#vid_87ad&pid_70db#serial#{12345678-1234-1234-1234-123456789abc}"
    assert enumerate_connected_candidates(path_enumerator=lambda ids:(("87ad:70db",path),),snapshot=snapshot)==()

def test_normal_launcher_is_hidden_and_debug_launcher_remains_console_based():
    root=Path(__file__).resolve().parents[1];normal=(root/"run-gui.bat").read_text(encoding="utf-8").lower();helper=(root/"packaging"/"launch-gui-hidden.vbs").read_text(encoding="utf-8").lower();debug=(root/"run-gui-debug.bat").read_text(encoding="utf-8").lower()
    assert "wscript.exe" in normal and "launch-gui-hidden.vbs" in normal and "pyw.exe" not in debug
    assert 'shell.run "pyw.exe -3.12 -m thermalright_lcd.gui", 1, false' in helper
    assert "-x faulthandler" in debug and "py -3.12 -m thermalright_lcd.gui" in debug
