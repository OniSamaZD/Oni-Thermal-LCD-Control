from __future__ import annotations

import argparse,json,statistics,time
from pathlib import Path

import psutil
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import DisplayCard
from thermalright_lcd.hardware_monitor import MonitorRenderer,templates
from thermalright_lcd.media import cache_overlay
from thermalright_lcd.output_mode import OutputMode


class CountingSender:
    enabled=True
    def __init__(self):self.calls=[];self.frame_metrics=[]
    def __call__(self,frame):
        now=time.perf_counter();self.calls.append(now);self.frame_metrics.append({"total_ms":0.0,"ack_ms":0.0,"reports":1});return int(getattr(frame,"total_bytes",1))
    def close(self):pass


def summary(values):
    values=list(values)
    if not values:return {"mean":0.0,"median":0.0,"p95":0.0,"peak":0.0}
    ordered=sorted(values);return {"mean":statistics.mean(values),"median":statistics.median(values),"p95":ordered[min(len(ordered)-1,round((len(ordered)-1)*.95))],"peak":max(values)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--fps",default="0.1");parser.add_argument("--seconds",type=float,default=60);parser.add_argument("--warmup",type=float,default=5);parser.add_argument("--sensors",action="store_true");parser.add_argument("--output",type=Path,required=True);parser.add_argument("--image",type=Path)
    args=parser.parse_args();app=QApplication.instance() or QApplication([]);sender=CountingSender();card=DisplayCard("Static benchmark",(1280,480),"0416:5302",hardware_sender=sender)
    image=args.image or args.output.with_suffix(".png")
    if not image.exists():image.parent.mkdir(parents=True,exist_ok=True);Image.new("RGB",(1280,480),(20,35,60)).save(image)
    card.load(image);card.fps.setCurrentText(args.fps)
    if args.sensors:card._output_lease=card.output_ownership.transition(OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
    card.play();renderer=MonitorRenderer(templates("0416:5302")["Gaming Dashboard"]);sensor_generation=0;next_sensor=time.monotonic()+1.5
    process=psutil.Process();logical=psutil.cpu_count() or 1;process.cpu_percent(None);cpu=[];ram=[];threads=[];started=time.monotonic();measured=started+args.warmup;end=measured+args.seconds;baseline=None;cs0=None
    while time.monotonic()<end:
        app.processEvents();now=time.monotonic()
        if args.sensors and now>=next_sensor:
            next_sensor+=1.5;sensor_generation+=1
            if card.static_generation_due(now):
                overlay=renderer.render_overlay({"game.fps":100+sensor_generation,"cpu.usage":40+sensor_generation%5,"gpu.usage":70})
                cached=cache_overlay(overlay,card.size_target);overlay.close()
                with card._overlay_lock:
                    old=card._sensor_overlay;card._sensor_overlay=cached
                if old is not None:old.image.close()
                card.refresh()
        if now>=measured:
            if baseline is None:baseline={"sent":card.session.metrics.sent,"prepares":card.pipeline.total_prepares,"qimages":card.qimage_count,"preview":len(card._preview_presented)};cs0=process.num_ctx_switches();process.cpu_percent(None)
            cpu.append(process.cpu_percent(None)/logical);ram.append(process.memory_info().rss/1048576);threads.append(process.num_threads())
        time.sleep(.25)
    duration=max(.001,time.monotonic()-measured);cs1=process.num_ctx_switches();sent=card.session.metrics.sent-baseline["sent"];prepares=card.pipeline.total_prepares-baseline["prepares"]
    measured_calls=[x for x in sender.calls if x>=measured];intervals=[(b-a)*1000 for a,b in zip(measured_calls,measured_calls[1:])]
    report={"scenario":"static-sensors" if args.sensors else "static-image","selected_rate":args.fps,"measured_seconds":duration,"activation_sends":baseline["sent"],"periodic_or_event_sends":sent,"completed_frames":sent,"scheduled_refresh_opportunities":card.session.metrics.refresh_opportunities,"physical_send_interval_ms":summary(intervals),"render_or_prepare_count":prepares,"jpeg_count":prepares,"preview_presentations":len(card._preview_presented)-baseline["preview"],"cache":dict(card.pipeline.cache_metrics),"usb_send_skips":card.session.metrics.usb_send_skips,"cpu_percent_normalized":summary(cpu),"ram_mb":summary(ram),"threads":summary(threads),"context_switches_per_second":{"voluntary":(cs1.voluntary-cs0.voluntary)/duration,"involuntary":(cs1.involuntary-cs0.involuntary)/duration}}
    card.shutdown();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
