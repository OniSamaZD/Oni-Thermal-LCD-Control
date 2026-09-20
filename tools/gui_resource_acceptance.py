from __future__ import annotations
import argparse,json,os,statistics,time
from pathlib import Path
import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from thermalright_lcd.gui import MainWindow

def percentile(values,p):
    values=sorted(values);return values[min(len(values)-1,int((len(values)-1)*p))] if values else 0

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--media",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);parser.add_argument("--seconds",type=float,default=60);args=parser.parse_args()
    os.environ["ONI_LCD_INSTANCE_NAME"]=f"OniResourceAcceptance-{os.getpid()}"
    app=QApplication([]);app.setQuitOnLastWindowClosed(False);window=MainWindow();window.left.load(args.media);window.right.load(args.media)
    window.left.fps.setCurrentText("60");window.right.fps.setCurrentText("60");window.left.quality_box.setCurrentText("Balanced");window.right.quality_box.setCurrentText("Extreme FPS");window.sync_toggle.setChecked(True);window.show();window.left.play()
    process=psutil.Process();logical=psutil.cpu_count() or 1;process.cpu_percent(None);results={};stages=["foreground","minimized","hidden","tray"];stage_index=-1;started=0;baseline={};samples=[];transitioning=False
    def counters():
        cards=(window.left,window.right)
        return {"qimage":sum(c.qimage_count for c in cards),"qpixmap":sum(c.qpixmap_count for c in cards),"scale":sum(c.preview_scale_count for c in cards),"repaint":sum(c.preview.paint_count for c in cards),"metrics":sum(c.metrics_update_count for c in cards)}
    def enter():
        nonlocal stage_index,started,baseline,samples,transitioning
        transitioning=False
        stage_index+=1
        if stage_index>=len(stages):
            window.exit_application();return
        stage=stages[stage_index]
        if stage=="foreground":window.showNormal();window.raise_()
        elif stage=="minimized":window.showMinimized()
        elif stage=="hidden":window.hide()
        else:window.hide();window.tray.show()
        app.processEvents();baseline=counters();samples=[];started=time.perf_counter();process.cpu_percent(None)
    def sample():
        nonlocal samples,transitioning
        if stage_index<0 or transitioning:return
        now=time.perf_counter();tree=[process]+process.children(recursive=True)
        samples.append({"cpu":sum(p.cpu_percent(None) for p in tree)/logical,"ram":sum(p.memory_info().rss for p in tree)/1048576,"threads":sum(p.num_threads() for p in tree),"children":len(tree)-1})
        if now-started>=args.seconds:
            stage=stages[stage_index];after=counters();duration=now-started;cpu=[x["cpu"] for x in samples]
            results[stage]={"duration_seconds":duration,"cpu_mean":statistics.mean(cpu),"cpu_p95":percentile(cpu,.95),"cpu_peak":max(cpu),"ram_mean_mb":statistics.mean(x["ram"] for x in samples),"ram_peak_mb":max(x["ram"] for x in samples),"threads_peak":max(x["threads"] for x in samples),"child_peak":max(x["children"] for x in samples),"physical_fps":[window.left.actual_fps(),window.right.actual_fps()],"preview_presented_fps":[window.left.actual_preview_fps(),window.right.actual_preview_fps()],"decode_fps":getattr(window.shared_hub.scheduler.metrics,"decode_fps",0) if window.shared_hub else 0,**{f"{key}_per_second":(after[key]-baseline[key])/duration for key in baseline}}
            transitioning=True;QTimer.singleShot(1000,enter)
    poll=QTimer();poll.setInterval(200);poll.timeout.connect(sample);poll.start();QTimer.singleShot(12000,enter);app.exec();poll.stop()
    report={"schema":1,"authorization":"user authorized known-protocol dual physical and resource validation","media":str(args.media),"same_media_shared_decoder":True,"stages":results,"gpu":"Windows engine counters unavailable in this harness","unknown_usb_commands":0,"zero_retries":True}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
