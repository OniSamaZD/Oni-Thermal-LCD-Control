from __future__ import annotations

import argparse,json,os,statistics,tempfile,time
from pathlib import Path

import psutil
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import MainWindow
from thermalright_lcd.hardware_monitor import templates


def summary(values):
    values=list(values)
    if not values:return {"mean":0.0,"median":0.0,"p95":0.0,"peak":0.0}
    ordered=sorted(values);return {"mean":statistics.mean(values),"median":statistics.median(values),"p95":ordered[min(len(ordered)-1,round((len(ordered)-1)*.95))],"peak":max(values)}


def main():
    p=argparse.ArgumentParser();p.add_argument("--fps",default="0.1");p.add_argument("--seconds",type=float,default=60);p.add_argument("--sensors",action="store_true");p.add_argument("--device",choices=("both","0416:5408","0416:5302"),default="both");p.add_argument("--keepalive",type=float);p.add_argument("--image",type=Path);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    os.environ["ONI_LCD_INSTANCE_NAME"]=f"OniPhysicalStatic-{os.getpid()}";profile=Path(tempfile.mkdtemp(prefix="oni-static-bench-"));os.environ["LOCALAPPDATA"]=str(profile);image=args.image or args.output.with_suffix(".png");image.parent.mkdir(parents=True,exist_ok=True)
    if args.image is None:
        canvas=Image.new("RGB",(1920,480),(8,28,46));draw=ImageDraw.Draw(canvas);draw.rectangle((20,20,1900,460),outline=(0,220,255),width=8);draw.text((80,180),f"ONI STATIC {args.fps} FPS",fill=(255,255,255));canvas.save(image);canvas.close()
    elif not image.is_file():raise FileNotFoundError(image)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False);window=MainWindow()
    cards=tuple(card for card in (window.left,window.right) if args.device=="both" or card.device_id==args.device)
    for card in cards:
        card.load(image);card.fps.setCurrentText(args.fps)
        if args.keepalive is not None:
            if args.keepalive<=0:raise ValueError("--keepalive must be positive")
            card.session.keepalive_interval=float(args.keepalive)
    if args.sensors:
        for card in cards:window.start_monitor_overlay(card.device_id,templates(card.device_id)["Gaming Dashboard"])
    else:
        for card in cards:card.play(coordinated=True)
    activation_deadline=time.monotonic()+15
    while time.monotonic()<activation_deadline and any(card.session.metrics.sent<1 and not card.session.metrics.last_error for card in cards):app.processEvents();time.sleep(.02)
    activation={card.device_id:card.session.metrics.sent for card in cards};baseline={card.device_id:{"sent":card.session.metrics.sent,"prepare":card.pipeline.total_prepares,"preview":len(card._preview_presented),"opportunities":card.session.metrics.refresh_opportunities,"timings":len(card.session.frame_timings),"content":card.session.metrics.content_sends,"keepalive":card.session.metrics.keepalive_sends,"held":card.session.metrics.held_frame_generation,"worker_starts":card.session.worker_starts} for card in cards}
    process=psutil.Process();logical=psutil.cpu_count() or 1;process.cpu_percent(None);cs0=process.num_ctx_switches();cpu=[];ram=[];threads=[];started=time.monotonic();next_sample=started
    while time.monotonic()-started<args.seconds:
        app.processEvents();now=time.monotonic()
        if now>=next_sample:next_sample+=.25;cpu.append(process.cpu_percent(None)/logical);ram.append(process.memory_info().rss/1048576);threads.append(process.num_threads())
        time.sleep(.01)
    duration=time.monotonic()-started;cs1=process.num_ctx_switches();results={}
    for card in cards:
        base=baseline[card.device_id];timings=list(card.session.frame_timings)[base["timings"]:];intervals=[x["complete_interval_ms"] for x in timings if x["complete_interval_ms"]];results[card.device_id]={"activation_sends":activation[card.device_id],"completed_frames":card.session.metrics.sent-base["sent"],"refresh_opportunities":card.session.metrics.refresh_opportunities-base["opportunities"],"prepare_and_jpeg_count":card.pipeline.total_prepares-base["prepare"],"preview_presentations":len(card._preview_presented)-base["preview"],"completion_interval_ms":summary(intervals),"transport_ms":summary(x["transport_ms"] for x in timings),"ack_ms":summary(x["ack_ms"] for x in timings if x["ack_ms"]),"error":card.session.metrics.last_error,"queue_dropped":card.session.queue.dropped-base.get("dropped",0)}
        results[card.device_id].update({"content_sends":card.session.metrics.content_sends-base["content"],"keepalive_sends":card.session.metrics.keepalive_sends-base["keepalive"],"fresh_transaction_frames":card.session.metrics.transport_frames_rebuilt,"held_frame_generation_start":base["held"],"held_frame_generation_end":card.session.metrics.held_frame_generation,"worker_starts_start":base["worker_starts"],"worker_starts_end":card.session.worker_starts,"session_state_end":card.session.state.value,"sender_enabled":card.hardware_sender.enabled,"sender_open":bool(getattr(card.hardware_sender,"_opened",False)),"sender_frames":getattr(card.hardware_sender,"frames",0),"send_timeline":timings})
    report={"scenario":"physical-static-sensors" if args.sensors else "physical-static","selected_rate":args.fps,"selected_device":args.device,"source_image":str(image),"keepalive_interval_seconds":args.keepalive,"duration_seconds":duration,"results":results,"resources":{"cpu_percent_normalized":summary(cpu),"ram_mb":summary(ram),"threads":summary(threads),"context_switches_per_second":{"voluntary":(cs1.voluntary-cs0.voluntary)/duration,"involuntary":(cs1.involuntary-cs0.involuntary)/duration}},"sensors":window.monitor_service.diagnostics()}
    window.shutdown();args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
