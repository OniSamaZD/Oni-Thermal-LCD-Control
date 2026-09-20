"""Controlled 60-second USB-impossible low-overhead measurements."""
from __future__ import annotations
import argparse,json,os,statistics,tempfile,time
from pathlib import Path


class OfflineSink:
    enabled=True
    def __init__(self):self.calls=0;self.bytes=0
    def __call__(self,frame):self.calls+=1;self.bytes+=frame.total_bytes;return frame.total_bytes
    def close(self):pass


def percentile(values,p):
    ordered=sorted(values);return ordered[min(len(ordered)-1,max(0,int((len(ordered)-1)*p)))]


def run(scenario:str,duration:float,media_1080:Path,media_4k:Path,output:Path,media_1080_b:Path|None=None):
    if duration<5:raise ValueError("controlled benchmark requires at least 5 seconds")
    os.environ["QT_QPA_PLATFORM"]="offscreen";os.environ["ONI_LCD_HW_DECODE"]="d3d11va"
    import psutil
    from PySide6.QtWidgets import QApplication
    from . import gui
    from .modes import resource_mode
    process=psutil.Process();logical=psutil.cpu_count(logical=True) or 1
    with tempfile.TemporaryDirectory(prefix="oni-low-cpu-") as local:
        old=os.environ.get("LOCALAPPDATA");os.environ["LOCALAPPDATA"]=local;senders=[]
        def sender(_):value=OfflineSink();senders.append(value);return value
        gui.build_gui_sender=sender;gui.thermalright_processes=lambda:[]
        app=QApplication.instance() or QApplication(["oni-low-cpu"]);window=gui.MainWindow();window.apply_resource_mode("Game Mode");window.show();app.processEvents()
        if scenario=="idle_tray":window.hide();app.processEvents()
        elif scenario not in {"idle_visible"}:
            media=media_1080 if "1080" in scenario else media_4k
            cards=(window.left,) if "one" in scenario else (window.left,window.right)
            for index,card in enumerate(cards):card.load(media_1080_b if index and scenario.startswith("different_") and media_1080_b else media)
            if scenario.startswith("same_"):
                window.sync_toggle.setChecked(True);window.left.play()
            else:
                for card in cards:card.play()
            if "tray" in scenario:window.hide();app.processEvents()
        tracked={process.pid:process};samples=[]
        def update_processes():
            for child in process.children(recursive=True):
                if child.pid not in tracked:
                    try:child.cpu_percent(None);tracked[child.pid]=child
                    except psutil.Error:pass
        update_processes()
        for item in tracked.values():
            try:item.cpu_percent(None)
            except psutil.Error:pass
        started=time.monotonic();next_sample=started+.5
        while time.monotonic()-started<duration:
            app.processEvents();now=time.monotonic()
            if now>=next_sample:
                update_processes();raw=0;parent_raw=0;child_raw=0;rss=0;threads=0
                for item in list(tracked.values()):
                    try:
                        value=item.cpu_percent(None);raw+=value
                        if item.pid==process.pid:parent_raw+=value
                        else:child_raw+=value
                        rss+=item.memory_info().rss;threads+=item.num_threads()
                    except psutil.Error:pass
                samples.append({"elapsed":now-started,"cpu_raw":raw,"parent_cpu_normalized":parent_raw/logical,"child_cpu_normalized":child_raw/logical,"cpu_normalized":raw/logical,"rss_mb":rss/1048576,"threads":threads,"child_processes":max(0,len(tracked)-1)});next_sample=now+.5
            time.sleep(.02)
        cards=(window.left,window.right);runtime=window.runtime_diagnostics();shared_active=bool(getattr(window,"shared_hub",None));details=[]
        for card in cards:
            shared=getattr(window,"shared_hub",None);active_scheduler=card.scheduler or (shared.scheduler if shared else None);details.append({"device":card.device_id,"active":bool(active_scheduler),"decoder_backend":getattr(active_scheduler.source,"backend","idle") if active_scheduler else "idle","decode_fps":active_scheduler.metrics.decode_fps if active_scheduler else 0,"preview_target_fps":card.preview_fps,"preview_presented_fps":card.actual_preview_fps(),"prepared_fps":1000/card.pipeline.last_metrics["total_prepare_ms"] if card.pipeline.last_metrics.get("total_prepare_ms") else 0,"encode_fps":1000/card.pipeline.last_metrics["jpeg_encode_ms"] if card.pipeline.last_metrics.get("jpeg_encode_ms") else 0,"transport_fps":card.session.metrics.actual_fps,"frames":card.session.metrics.sent})
        window.exit_application();app.processEvents()
        if old is None:os.environ.pop("LOCALAPPDATA",None)
        else:os.environ["LOCALAPPDATA"]=old
    raw=[x["cpu_raw"] for x in samples];normal=[x["cpu_normalized"] for x in samples]
    report={"schema":1,"scenario":scenario,"duration_seconds":duration,"logical_cpus":logical,"usb_writes":0,"hardware_sender":"OfflineSink","gpu":"unavailable without Windows GPU engine counters","cpu_raw_percent":{"mean":statistics.mean(raw),"p95":percentile(raw,.95),"peak":max(raw)},"parent_cpu_normalized_mean":statistics.mean(x["parent_cpu_normalized"] for x in samples),"child_cpu_normalized_mean":statistics.mean(x["child_cpu_normalized"] for x in samples),"cpu_normalized_percent":{"mean":statistics.mean(normal),"p95":percentile(normal,.95),"peak":max(normal)},"rss_mb":{"mean":statistics.mean(x["rss_mb"] for x in samples),"peak":max(x["rss_mb"] for x in samples)},"threads":{"mean":statistics.mean(x["threads"] for x in samples),"peak":max(x["threads"] for x in samples)},"child_processes":{"peak":max(x["child_processes"] for x in samples)},"shared_decoder":shared_active,"displays":details,"runtime":runtime,"samples":samples}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--scenario",required=True,choices=("idle_visible","idle_tray","1080_one_visible","1080_one_tray","same_1080_two_visible","same_1080_two_tray","different_1080_two_visible","different_1080_two_tray","4k_one","4k_two","same_4k_two"));p.add_argument("--duration",type=float,default=60);p.add_argument("--media-1080",type=Path,required=True);p.add_argument("--media-1080-b",type=Path);p.add_argument("--media-4k",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args(argv);r=run(a.scenario,a.duration,a.media_1080,a.media_4k,a.output,a.media_1080_b);print(json.dumps({"scenario":a.scenario,"cpu_normalized":r["cpu_normalized_percent"],"rss":r["rss_mb"],"usb_writes":0}));return 0
if __name__=="__main__":raise SystemExit(main())
