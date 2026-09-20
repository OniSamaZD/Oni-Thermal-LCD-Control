from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import psutil
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import MainWindow
from thermalright_lcd.hardware_monitor import templates
from thermalright_lcd.output_mode import OutputMode


def pump(app, seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents();time.sleep(.01)


def pump_until(app, predicate, timeout):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return True
        time.sleep(.01)
    return bool(predicate())


def snapshot(card):
    scheduler=card.scheduler
    lease=card.output_ownership.lease()
    return {"completed":card.session.metrics.sent,"content":card.session.metrics.content_sends,"retention":card.session.metrics.keepalive_sends,"error":card.session.metrics.last_error,"session_state":card.session.state.value,"session_worker_alive":bool(card.session._thread and card.session._thread.is_alive()),"hardware_started":card.hardware_started,"transport_queue":len(card.session.queue),"held_source_index":card._last_encoded_source_index,"pipeline_prepares":card.pipeline.total_prepares,"output_mode":lease.mode.value,"output_generation":lease.generation,"lease_matches":card.output_ownership.accepts(card._output_lease,OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY),"fps":card.actual_fps(),"scheduler_creations":card.scheduler_creations,"scheduler_active":bool(scheduler and scheduler.is_active),"scheduler_decoded":scheduler.metrics.decoded if scheduler else 0,"scheduler_delivered":scheduler.metrics.delivered if scheduler else 0,"scheduler_error":scheduler.metrics.last_error if scheduler else "","transform_generation":card.transform_generation}


def delta(before, after):
    cumulative={"completed","content","retention","scheduler_creations","scheduler_decoded","scheduler_delivered","pipeline_prepares","transform_generation"}
    return {key:(after[key]-before[key] if key in cumulative else after[key]) for key in after}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--video",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    if not args.video.is_file():raise FileNotFoundError(args.video)
    os.environ["ONI_LCD_INSTANCE_NAME"]=f"OniPhysicalUi-{os.getpid()}";os.environ["LOCALAPPDATA"]=tempfile.mkdtemp(prefix="oni-ui-physical-")
    asset_dir=args.output.parent/"ui-interaction-assets";asset_dir.mkdir(parents=True,exist_ok=True);photo=asset_dir/"interaction-photo.png";gif=asset_dir/"interaction-animation.gif"
    canvas=Image.new("RGB",(1920,480),(9,20,38));draw=ImageDraw.Draw(canvas);draw.rectangle((20,20,1900,460),outline=(0,220,255),width=10);draw.text((80,190),"ONI LIVE PHOTO TRANSFORM",fill=(255,255,255));canvas.save(photo);canvas.close()
    frames=[]
    for index,color in enumerate(((255,40,100),(20,210,255),(255,210,30))):
        frame=Image.new("RGB",(640,240),color);ImageDraw.Draw(frame).text((40,100),f"ONI GIF {index+1}",fill=(0,0,0));frames.append(frame)
    frames[0].save(gif,save_all=True,append_images=frames[1:],duration=100,loop=0)
    for frame in frames:frame.close()
    app=QApplication([]);app.setQuitOnLastWindowClosed(False);window=MainWindow();process=psutil.Process();logical=psutil.cpu_count() or 1;process.cpu_percent(None);cpu=[];results={}
    fatal_error=""
    try:
        cards=(window.left,window.right)
        if not all(card.hardware_sender.enabled for card in cards):raise RuntimeError("guarded hardware preflight did not enable both validated devices")
        # Static photo: one coalesced content rebuild for each edit burst, while
        # the independent retention worker remains active.
        for card in cards:card.load(photo);card.play(coordinated=True)
        pump(app,2);before={c.device_id:snapshot(c) for c in cards};scheduler_ids={c.device_id:id(c.scheduler) if c.scheduler else None for c in cards}
        for card in cards:
            card.pan_x_box.setValue(80);card.pan_y_box.setValue(-30);card.zoom_box.setValue(1.2);card.rotation.setCurrentIndex(1);card.mode.setCurrentText("Fill");card.brightness_slider.setValue(82)
        pump(app,2)
        for card in cards:window.start_monitor_overlay(card.device_id,templates(card.device_id)["Gaming Dashboard"])
        pump(app,2)
        for card in cards:
            card.quick_edit.setChecked(True);editor=card.home_quick_editor;element=editor.layout.elements[0];editor.scene.controller.select([element.id]);editor.scene.controller.move(20,10);editor.changed.emit()
        pump(app,2);after={c.device_id:snapshot(c) for c in cards};results["photo"]={pid:{"delta":delta(before[pid],after[pid]),"scheduler_unchanged":scheduler_ids[pid]==(id(card.scheduler) if card.scheduler else None)} for pid,card in ((c.device_id,c) for c in cards)}
        for card in cards:card.quick_edit.setChecked(False);card.stop(coordinated=True);window.set_output_mode(card.device_id,OutputMode.MEDIA,False)
        # Video: one shared decoder, no restart while every live transform is changed.
        for card in cards:card.load(args.video);card.fps.setCurrentText("60")
        pre_open={c.device_id:c.session.metrics.sent for c in cards};window.sync_toggle.setChecked(True);window.left.play()
        if not pump_until(app,lambda:all(c.session.metrics.sent>pre_open[c.device_id] for c in cards),18):raise RuntimeError("video did not complete the first post-open frame on both displays")
        pump(app,1);shared=window.shared_hub;before={c.device_id:snapshot(c) for c in cards}
        for value in (20,40,60):
            for card in cards:card.pan_x_box.setValue(value);card.pan_y_box.setValue(-value//2);card.zoom_box.setValue(1+value/200);card.rotation.setCurrentIndex((value//20)%4);card.mode.setCurrentText("Center" if value==40 else "Fill")
            pump(app,1.2);cpu.append(process.cpu_percent(None)/logical)
        after={c.device_id:snapshot(c) for c in cards};results["video"]={pid:{"delta":delta(before[pid],after[pid]),"shared_decoder_unchanged":window.shared_hub is shared,"playing":card.playing} for pid,card in ((c.device_id,c) for c in cards)}
        window.left.stop();pump(app,1)
        # GIF: independent animation workers continue while transforms change.
        window.sync_toggle.setChecked(False)
        dispatch={c.device_id:{"calls":0,"not_playing":0,"lease_rejected":0,"queue_busy":0,"prepared":0} for c in cards}
        for card in cards:
            original=card._deliver_frame;counts=dispatch[card.device_id]
            def traced(frame,_card=card,_original=original,_counts=counts):
                _counts["calls"]+=1
                if not _card.playing:_counts["not_playing"]+=1
                elif not _card.output_ownership.accepts(_card._output_lease,OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY):_counts["lease_rejected"]+=1
                elif _card.hardware_started and _card.hardware_sender.enabled and len(_card.session.queue):_counts["queue_busy"]+=1
                before_prepare=_card.pipeline.total_prepares;_original(frame)
                if _card.pipeline.total_prepares>before_prepare:_counts["prepared"]+=1
            card._deliver_frame=traced
        pre_open={c.device_id:c.session.metrics.sent for c in cards}
        for card in cards:card.load(gif);card.fps.setCurrentText("30");card.play(coordinated=True)
        if not pump_until(app,lambda:all(c.session.metrics.sent>pre_open[c.device_id] for c in cards),18):raise RuntimeError("GIF did not complete the first post-open frame on both displays")
        pump(app,1);schedulers={c.device_id:c.scheduler for c in cards};before={c.device_id:snapshot(c) for c in cards}
        for card in cards:card.pan_x_box.setValue(-25);card.pan_y_box.setValue(15);card.zoom_box.setValue(1.15);card.rotation.setCurrentIndex(2);card.mode.setCurrentText("Fit")
        pump(app,3);after={c.device_id:snapshot(c) for c in cards};results["gif"]={pid:{"delta":delta(before[pid],after[pid]),"dispatch":dispatch[pid],"scheduler_unchanged":card.scheduler is schedulers[pid],"playing":card.playing} for pid,card in ((c.device_id,c) for c in cards)}
        results["cpu_percent_normalized_samples"]=cpu;results["visual_confirmation"]="NOT RECORDED — telemetry/protocol validation only";results["protocol_changes"]=0
    except Exception as exc:
        fatal_error=f"{type(exc).__name__}: {exc}";results["fatal_error"]=fatal_error
    finally:
        window.shutdown()
    args.output.write_text(json.dumps({"schema":2,"scenario":"production-ui-live-interaction","results":results},indent=2),encoding="utf-8");print(json.dumps(results,indent=2))
    if fatal_error:raise SystemExit(2)


if __name__=="__main__":main()
