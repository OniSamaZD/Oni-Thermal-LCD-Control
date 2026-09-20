from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from unittest.mock import Mock,patch

from thermalright_lcd.encoder import validate_5302, validate_5408
from thermalright_lcd.media import MediaPipeline,QUALITY_PROFILES
from thermalright_lcd.settings import AppSettings, DisplayProfile
from thermalright_lcd.hardware_monitor import MonitorElement, MonitorLayout
from thermalright_lcd.theme_package import export_theme, import_theme, merge_theme
from thermalright_lcd.playback import FrameScheduler,MediaFrame,open_frame_source,timeline_frame_indices
from thermalright_lcd.modes import resource_mode


@pytest.mark.parametrize("device,size", [("0416:5408", (1920,462)), ("0416:5302", (1280,480))])
@pytest.mark.parametrize("quality", ["Quality", "Balanced", "Performance"])
def test_fast_bgr_pipeline_preserves_device_framing(device,size,quality):
    frame=np.zeros((1080,1920,3),dtype=np.uint8)
    frame[:,:,0]=np.arange(1920,dtype=np.uint16).astype(np.uint8)
    prepared,encoded=MediaPipeline().prepare_bgr(frame,device,quality=QUALITY_PROFILES[quality])
    assert prepared.canvas.width <= 720
    assert prepared.canvas.height <= 240
    result=(validate_5408 if device.endswith("5408") else validate_5302)(encoded)
    assert result["valid"] and result["jpeg_soi_eoi_and_dimensions"]


def test_theme_round_trip_with_optional_media(tmp_path):
    media=tmp_path/"pixel.png"
    assert cv2.imwrite(str(media),np.zeros((4,4,3),dtype=np.uint8))
    settings=AppSettings()
    settings.profiles["Fast"]={
        "0416:5408":DisplayProfile(str(media),"Fill",90,"60",True,12,-8,1.4,"Performance"),
        "0416:5302":DisplayProfile("","Fit",0,"Auto",False),
    }
    package=export_theme(tmp_path/"fast.onitheme",settings,include_media=True)
    data,warnings=import_theme(package,tmp_path/"imported")
    assert warnings == []
    target=AppSettings();merge_theme(target,data)
    restored=target.profiles["Fast"]["0416:5408"]
    assert Path(restored.media).is_file()
    assert (restored.fit_mode,restored.rotation,restored.fps,restored.pan_x,restored.zoom,restored.quality)==("Fill",90,"60",12,1.4,"Performance")


def test_theme_package_embeds_and_restores_background_and_image_assets(tmp_path):
    background=tmp_path/"wallpaper.png";logo=tmp_path/"logo.webp"
    assert cv2.imwrite(str(background),np.full((8,12,3),40,dtype=np.uint8))
    assert cv2.imwrite(str(logo),np.full((4,6,3),220,dtype=np.uint8))
    settings=AppSettings();layout=MonitorLayout("Portable","0416:5302",1280,480,background_source="custom_image",background_image=str(background),background_x=17,background_y=-9,background_zoom=1.25,background_rotation=5,background_brightness=72,elements=[MonitorElement("image",20,20,200,100,image=str(logo),opacity=173,brightness=81,rotation=12,z_index=7,visible=False)])
    settings.monitor_layouts={"Default":{"0416:5302":layout.to_dict()}}
    package=export_theme(tmp_path/"portable.onitheme",settings)
    background.unlink();logo.unlink()
    data,warnings=import_theme(package,tmp_path/"restored");assert warnings==[]
    restored=MonitorLayout.from_dict(data["monitor_layouts"]["Default"]["0416:5302"])
    assert Path(restored.background_image).is_file()
    assert Path(restored.elements[0].image).is_file()
    assert "theme-assets" in restored.background_image and "theme-assets" in restored.elements[0].image
    assert (restored.background_x,restored.background_y,restored.background_zoom,restored.background_rotation,restored.background_brightness)==(17,-9,1.25,5,72)
    assert (restored.elements[0].x,restored.elements[0].y,restored.elements[0].opacity,restored.elements[0].brightness,restored.elements[0].rotation,restored.elements[0].z_index,restored.elements[0].visible)==(20,20,173,81,12,7,False)


def test_theme_rejects_wrong_version(tmp_path):
    import json,zipfile
    path=tmp_path/"bad.onitheme"
    with zipfile.ZipFile(path,"w") as z:z.writestr("manifest.json",json.dumps({"format":"oni-thermal-theme","version":99,"profiles":{}}))
    with pytest.raises(ValueError,match="version"):import_theme(path)

def test_theme_rejects_traversal_and_executable_members(tmp_path):
    import json,zipfile
    manifest=json.dumps({"format":"oni-thermal-theme","version":1,"profiles":{}})
    for member in ("../escape.png","assets/payload.exe"):
        path=tmp_path/(member.replace("/","-").replace(".","_")+".onitheme")
        with zipfile.ZipFile(path,"w") as z:z.writestr("manifest.json",manifest);z.writestr(member,b"x")
        with pytest.raises(ValueError):import_theme(path)

def test_theme_rejects_unsafe_or_missing_asset_references(tmp_path):
    import json,zipfile
    for reference in ("../escape.png","C:/Windows/system.ini","/etc/passwd","assets/missing.png"):
        manifest={"format":"oni-thermal-theme","version":1,"profiles":{},"monitor_layouts":{"Default":{"0416:5302":{"name":"x","target":"0416:5302","width":1280,"height":480,"background_image":reference,"elements":[]}}}}
        path=tmp_path/(str(abs(hash(reference)))+".onitheme")
        with zipfile.ZipFile(path,"w") as z:z.writestr("manifest.json",json.dumps(manifest))
        with pytest.raises(ValueError):import_theme(path,tmp_path/"managed")


def test_two_fast_pipelines_have_no_shared_lock():
    frame=np.zeros((720,1280,3),dtype=np.uint8)
    first,second=MediaPipeline(),MediaPipeline()
    assert first._lock is not second._lock
    # Each pipeline keeps only its tiny bounded cache; no historical frames.
    for index in range(8):
        frame[0,0,0]=index
        first.prepare_bgr(frame,"0416:5408")
        second.prepare_bgr(frame,"0416:5302")
    assert first.cache_entries <= 2 and second.cache_entries <= 2


def test_sequential_decoder_drops_deadline_without_decoding_stale_frames():
    class Source:
        sequential_stream=True
        def __init__(self):self.skip_calls=0
        def skip(self,count):self.skip_calls+=1;return count
        def close(self):pass
    source=Source();scheduler=FrameScheduler(source,lambda _:None)
    assert scheduler._skip(50)==0 and source.skip_calls==0


def test_hardware_decode_failure_reports_cpu_fallback(tmp_path):
    media=tmp_path/"video.mp4";media.write_bytes(b"fixture")
    fallback=Mock();fallback.backend="CPU fallback"
    with patch("thermalright_lcd.playback.shutil.which",return_value="ffmpeg"),patch("thermalright_lcd.playback.FfmpegScaledVideoSource",side_effect=ValueError("D3D11 unavailable")),patch("thermalright_lcd.playback.OpenCvVideoSource",return_value=fallback):
        source=open_frame_source(media,decode_size=(1920,462))
    assert "D3D11 unavailable" in source.backend and "CPU fallback" in source.backend

def test_pyav_in_process_early_scale_has_no_helper_process(tmp_path):
    pytest.importorskip("av")
    media=tmp_path/"tiny.avi";writer=cv2.VideoWriter(str(media),cv2.VideoWriter_fourcc(*"MJPG"),10,(64,36));writer.write(np.zeros((36,64,3),dtype=np.uint8));writer.release()
    source=open_frame_source(media,decode_size=(32,18),decode_cover=False,decoder_backend="pyav");frame=source.next_frame()
    assert source.backend.startswith("In-process PyAV") and frame.native_bgr.shape[1::-1]==(32,18)
    assert not hasattr(source,"process");source.close()


def test_game_mode_reduces_preview_and_metrics_frequency():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    app=QApplication.instance() or QApplication([])
    card=DisplayCard("offline",(1280,480),"0416:5302")
    card.set_resource_mode(resource_mode("Normal"));normal=(card.preview_fps,card.timer.interval())
    card.set_resource_mode(resource_mode("Game Mode"));gaming=(card.preview_fps,card.timer.interval())
    assert gaming[0]<normal[0] and gaming[1]>normal[1]
    card.shutdown()


def test_hidden_hardware_preview_skips_preview_allocation_and_stale_encode():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    class Sender:
        enabled=True
        def __call__(self,frame):return frame.total_bytes
        def close(self):pass
    app=QApplication.instance() or QApplication([]);card=DisplayCard("offline",(1280,480),"0416:5302",hardware_sender=Sender());card.playing=True;card.hardware_started=True;card.set_preview_enabled(False)
    bgr=np.zeros((480,1280,3),dtype=np.uint8);frame=MediaFrame(None,1/60,0,0,bgr)
    real=card.pipeline.prepare_bgr;calls=[]
    def tracked(*args,**kwargs):calls.append(kwargs.get("generate_preview",args[8] if len(args)>8 else True));return real(*args,**kwargs)
    card.pipeline.prepare_bgr=tracked;card._deliver_frame(frame);card._deliver_frame(frame)
    assert calls==[False] and card.bridge.pending==0
    card.shutdown()


def test_lcd_preparation_has_no_second_relative_fps_gate():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    class Sender:
        enabled=True
        def __call__(self,frame):return frame.total_bytes
        def close(self):pass
    class EmptyQueue:
        def __len__(self):return 0
    class Session:
        refresh_interval=1/60
        queue=EmptyQueue()
        def set_media(self,_):pass
        def play(self):pass
    app=QApplication.instance() or QApplication([]);card=DisplayCard("offline",(1280,480),"0416:5302",hardware_sender=Sender());card.playing=True;card.hardware_started=True;card.set_preview_enabled(False);card.session=Session()
    calls=[];real=card.pipeline.prepare_bgr
    def tracked(*args,**kwargs):calls.append(args[0].shape);return real(*args,**kwargs)
    card.pipeline.prepare_bgr=tracked;bgr=np.zeros((480,1280,3),dtype=np.uint8)
    for index in range(8):card._deliver_frame(MediaFrame(None,1/59.94,index,index/59.94,bgr))
    assert len(calls)==8
    card.timer.stop()


def test_preview_metric_counts_final_qt_presentations_only(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    app=QApplication.instance() or QApplication([]);card=DisplayCard("offline",(1280,480),"0416:5302")
    ticks=iter((10.0,10.05,10.10));monkeypatch.setattr("thermalright_lcd.gui.time.perf_counter",lambda:next(ticks))
    image=QImage(8,8,QImage.Format_RGB32)
    for _ in range(3):card._show_image(image)
    assert card.actual_preview_fps()==pytest.approx(20.0)
    card.shutdown()


@pytest.mark.parametrize("cap",[20.0,30.0])
def test_preview_cap_limits_completed_qt_presentations(cap):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    app=QApplication.instance() or QApplication([]);card=DisplayCard("offline",(1280,480),"0416:5302");card.playing=True;card.preview_fps=cap
    bgr=np.zeros((120,320,3),dtype=np.uint8);started=time.monotonic();index=0
    while time.monotonic()-started<1.2:
        card._deliver_frame(MediaFrame(None,1/59.94,index,index/59.94,bgr));app.processEvents();index+=1;time.sleep(1/59.94)
    assert 0<card.actual_preview_fps()<=cap*1.06
    assert len(card.preview_intervals)>5
    card.shutdown()


def test_hidden_preview_is_suspended_without_affecting_transport_submission():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    class Sender:
        enabled=True
        def __init__(self):self.calls=0
        def __call__(self,frame):self.calls+=1;return frame.total_bytes
        def close(self):pass
    app=QApplication.instance() or QApplication([]);sender=Sender();card=DisplayCard("offline",(1280,480),"0416:5302",hardware_sender=sender);card.playing=True;card.hardware_started=True;card.set_preview_enabled(False)
    bgr=np.zeros((120,320,3),dtype=np.uint8)
    for index in range(8):card._deliver_frame(MediaFrame(None,1/60,index,index/60,bgr));time.sleep(.02)
    time.sleep(.08);assert sender.calls>0 and card.actual_preview_fps()==0 and card.bridge.pending==0
    card.shutdown()


def test_minimized_visibility_cuts_preview_off_before_qimage_creation():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import DisplayCard
    class Sender:
        enabled=True
        def __call__(self,frame):return frame.total_bytes
        def close(self):pass
    app=QApplication.instance() or QApplication([]);card=DisplayCard("offline",(1280,480),"0416:5302",hardware_sender=Sender());card.playing=True;card.hardware_started=True;card.set_window_visible(False)
    before=(card.qimage_count,card.qpixmap_count,card.preview_scale_count,card.preview.paint_count)
    bgr=np.zeros((120,320,3),dtype=np.uint8)
    for index in range(20):card._deliver_frame(MediaFrame(None,1/60,index,index/60,bgr));app.processEvents()
    assert (card.qimage_count,card.qpixmap_count,card.preview_scale_count,card.preview.paint_count)==before
    assert not card.preview_enabled and card.actual_preview_fps()==0
    card.shutdown()


@pytest.mark.parametrize("target",[10,20,30,45,60])
def test_fps_selection_preserves_sixty_second_timeline(target):
    selected=timeline_frame_indices(60,target,60)
    assert len(selected)==60*target
    assert selected[0]==0
    assert selected[-1]>=3600-round(60/target)-1
    assert all(a<b for a,b in zip(selected,selected[1:]))
