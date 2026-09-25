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


class Sender:
    enabled=False
    def close(self):pass

def wait_until(app,predicate,timeout=2):
    deadline=time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert predicate()

def make_window(provider):
    app=QApplication.instance() or QApplication([])
    folder=tempfile.TemporaryDirectory();environment=patch.dict(os.environ,{"LOCALAPPDATA":folder.name});sender=patch("thermalright_lcd.gui.build_gui_sender",return_value=Sender())
    environment.start();sender.start();window=MainWindow(discovery_provider=provider)
    return app,window,(folder,environment,sender)

def cleanup(window,resources):
    window.shutdown();resources[2].stop();resources[1].stop();resources[0].cleanup()

def test_zero_device_scan_is_async_responsive_and_stable():
    gate=threading.Event();calls=[]
    def provider():calls.append(1);return () if len(calls)==1 else (gate.wait(1),())[1]
    app,window,resources=make_window(provider);ticks=[];QTimer.singleShot(10,lambda:ticks.append(True))
    started=time.perf_counter();assert window.scan_for_displays();assert time.perf_counter()-started<.1;assert not window.scan_for_displays()
    wait_until(app,lambda:bool(ticks));assert not window.cards;assert window.display_empty_state.isVisible() or not window.isVisible()
    gate.set();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);assert window.display_count_label.text()=="Displays: 0 connected";cleanup(window,resources)

def test_successful_repeated_scan_reconciles_without_duplicate_session():
    observations=[]
    app,window,resources=make_window(lambda:tuple(observations));observations.append(DiscoveredDisplay("one","0416:5408"))
    assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);card=window.cards[0]
    assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);assert window.cards==[card]
    observations.clear();assert window.scan_for_displays();wait_until(app,lambda:getattr(window,"_display_scan_thread",None) is None);assert window.cards==[];cleanup(window,resources)

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

def test_native_thermalright_enumerator_zero_malformed_and_timeout_are_safe():
    never=lambda *a,**k:(_ for _ in ()).throw(AssertionError("runner should not run without physical paths"))
    assert enumerate_connected_candidates(runner=never,path_enumerator=lambda ids:())==()
    assert enumerate_connected_candidates(runner=never,path_enumerator=lambda ids:(("87ad:70db","malformed"),))==()
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired(args[0],3)
    path=r"\\?\usb#vid_87ad&pid_70db#serial#{12345678-1234-1234-1234-123456789abc}"
    assert enumerate_connected_candidates(runner=timeout,path_enumerator=lambda ids:(("87ad:70db",path),))==()

def test_normal_launcher_is_hidden_and_debug_launcher_remains_console_based():
    root=Path(__file__).resolve().parents[1];normal=(root/"run-gui.bat").read_text(encoding="utf-8").lower();helper=(root/"packaging"/"launch-gui-hidden.vbs").read_text(encoding="utf-8").lower();debug=(root/"run-gui-debug.bat").read_text(encoding="utf-8").lower()
    assert "wscript.exe" in normal and "launch-gui-hidden.vbs" in normal and "pyw.exe" not in debug
    assert 'shell.run "pyw.exe -3.12 -m thermalright_lcd.gui", 1, false' in helper
    assert "-x faulthandler" in debug and "py -3.12 -m thermalright_lcd.gui" in debug
