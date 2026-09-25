import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import tracemalloc
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.device_discovery import DiscoveredDisplay
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.hardware_monitor import MonitorElement, MonitorLayout
from thermalright_lcd.output_mode import OutputMode
from thermalright_lcd.sensor_theme import SensorTheme, ThemeCanvas, ThemeElement


def _rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0


def _private_mb():
    try:
        import psutil
        info=psutil.Process().memory_full_info()
        return getattr(info,"private",info.rss)/1024/1024
    except (ImportError,AttributeError):
        return 0.0

def _wait_scan(window,app):
    deadline=time.monotonic()+2
    while getattr(window,"_display_scan_thread",None) is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.002)
    assert getattr(window,"_display_scan_thread",None) is None


def test_repeated_mode_media_theme_hotplug_soak_is_bounded_and_cleans_up():
    app=QApplication.instance() or QApplication([]);observations=[DiscoveredDisplay("wide","0416:5408")]
    with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"LOCALAPPDATA":folder}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _device:DisabledHardwareSender()):
        root=Path(folder);photo=root/"photo.png";gif=root/"clip.gif";Image.new("RGB",(64,32),"navy").save(photo);frames=[Image.new("RGB",(32,16),c) for c in ("red","green")];frames[0].save(gif,save_all=True,append_images=frames[1:],duration=40,loop=0)
        window=MainWindow(discovery_provider=lambda:tuple(observations));window.cards[0].set_preview_enabled(True);theme=SensorTheme("soak","Soak",ThemeCanvas(320,120),[ThemeElement("value","Value","sensor_value",10,10,120,40,sensor_binding="cpu.usage")])
        monitor=MonitorLayout("Soak Monitor","0416:5408",1920,462,elements=[MonitorElement("label + value",10,10,sensor_id="cpu.usage")])
        legitimate={window,window.tray_menu};top_before={widget for widget in app.topLevelWidgets() if widget.parent() is None};sessions={id(window.cards[0].session)}
        tracemalloc.start();gc.collect();heap_before=tracemalloc.get_traced_memory()[0];rss_before=_rss_mb();private_before=_private_mb();threads_before=threading.active_count()
        for index in range(120):
            card=window.cards[0];card.load(photo if index%3==0 else gif);card.play(coordinated=True);card.stop(coordinated=True)
            window.apply_sensor_theme(theme,None,(card.device_id,),1)
            window.start_monitor_overlay(card.device_id,monitor);card.stop(coordinated=True)
            if index%4==0:window.start_monitor_layout(card.device_id,monitor);window.stop_monitor_layout(card.device_id)
            card.set_output_mode_val(OutputMode.MEDIA.value)
            if index%10==0:
                window.open_theme_gallery();window.select_page(0);window.save_all_profile("Default");card.apply_profile(window.settings.profiles["Default"][card.device_id])
            if index%8==0:
                observations.append(DiscoveredDisplay(f"small-{index}","0416:5302"));window.scan_for_displays();_wait_scan(window,app);observations.pop();window.scan_for_displays();_wait_scan(window,app)
                sessions.update(id(item.session) for item in window.cards)
            app.processEvents()
        gc.collect();app.processEvents();heap_after=tracemalloc.get_traced_memory()[0];rss_after=_rss_mb();private_after=_private_mb();threads_after=threading.active_count();top_after={widget for widget in app.topLevelWidgets() if widget.parent() is None};active_timers=sum(timer.isActive() for timer in window.findChildren(type(window.monitor_timer)));active_sessions=sum(card.session._thread is not None for card in window.cards);active_decoders=sum(card.scheduler is not None for card in window.cards);active_sensor_runtimes=len(getattr(getattr(window,"sensor_theme_runtime",None),"active_device_ids",()));tracemalloc.stop();cards=tuple(window.cards);window.shutdown();app.processEvents();gc.collect()
        print({"iterations":120,"python_heap_before_mb":round(heap_before/1024/1024,2),"python_heap_after_mb":round(heap_after/1024/1024,2),"rss_before_mb":round(rss_before,2),"rss_after_mb":round(rss_after,2),"private_before_mb":round(private_before,2),"private_after_mb":round(private_after,2),"threads_before":threads_before,"threads_after_workload":threads_after,"top_level_before":len(top_before),"top_level_after":len(top_after),"active_timers_before_shutdown":active_timers,"active_sessions_before_shutdown":active_sessions,"active_decoders_before_shutdown":active_decoders,"active_sensor_runtimes_before_shutdown":active_sensor_runtimes,"session_objects_seen":len(sessions)})
        assert heap_after-heap_before<12*1024*1024
        if rss_before and rss_after:assert rss_after-rss_before<96
        if private_before and private_after:assert private_after-private_before<96
        assert not [widget for widget in top_after-top_before if widget not in legitimate]
        assert not [thread for thread in threading.enumerate() if thread.name.startswith(("display-","media-decoder","media-delivery"))]
        assert all(not timer.isActive() for timer in window.findChildren(type(window.monitor_timer)))
        assert all(card.scheduler is None and card.session._thread is None for card in cards)
