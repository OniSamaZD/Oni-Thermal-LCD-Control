"""USB-impossible benchmark of final Qt preview presentations."""
from __future__ import annotations
import argparse,json,os,statistics,tempfile,time
from pathlib import Path

class Sink:
    enabled=True
    def __init__(self):self.calls=0;self.bytes=0
    def __call__(self,frame):self.calls+=1;self.bytes+=frame.total_bytes;return frame.total_bytes
    def close(self):pass

def percentile(values,p):
    values=sorted(values);return values[min(len(values)-1,int((len(values)-1)*p))] if values else 0.0

def run(media:Path,duration:float,output:Path):
    os.environ["QT_QPA_PLATFORM"]="offscreen"
    import psutil
    from PySide6.QtWidgets import QApplication
    from . import gui
    gui.thermalright_processes=lambda:[];gui.build_gui_sender=lambda _:Sink()
    app=QApplication.instance() or QApplication(["preview-benchmark"]);logical=psutil.cpu_count() or 1;process=psutil.Process();rows=[]
    for cap in (20.0,30.0):
        with tempfile.TemporaryDirectory(prefix="oni-preview-") as local:
            os.environ["LOCALAPPDATA"]=local;window=gui.MainWindow();card=window.left;card.load(media);card.fps.setCurrentText("60");card.foreground_preview_fps=cap;card.preview_fps=cap;window.show();app.processEvents();card.play();time.sleep(.5);app.processEvents();card._preview_presented.clear();card.preview_intervals.clear();before=[process]+process.children(recursive=True);cpu0={x.pid:sum(x.cpu_times()[:2]) for x in before};started=time.perf_counter()
            while time.perf_counter()-started<duration:
                app.processEvents();time.sleep(.005)
            elapsed=time.perf_counter()-started;tree=[process]+process.children(recursive=True);cpu_delta={x.pid:max(0,sum(x.cpu_times()[:2])-cpu0.get(x.pid,sum(x.cpu_times()[:2]))) for x in tree};parent_cpu=cpu_delta.get(process.pid,0)/elapsed/logical*100;child_cpu=sum(v for pid,v in cpu_delta.items() if pid!=process.pid)/elapsed/logical*100;rows.append({"mode":"foreground","cap_fps":cap,"actual_presented_fps":card.actual_preview_fps(),"presentation_interval_ms":{"mean":statistics.mean(card.preview_intervals) if card.preview_intervals else 0,"p95":percentile(card.preview_intervals,.95)},"parent_cpu_percent_normalized":parent_cpu,"child_cpu_percent_normalized":child_cpu,"total_cpu_percent_normalized":parent_cpu+child_cpu,"total_ram_mb":sum(x.memory_info().rss for x in tree)/1048576,"process_count":len(tree),"child_processes":[x.name() for x in tree[1:]],"threads":sum(x.num_threads() for x in tree),"offline_transport_fps":card.actual_fps(),"usb_writes":0});window.exit_application();app.processEvents()
    with tempfile.TemporaryDirectory(prefix="oni-preview-hidden-") as local:
        os.environ["LOCALAPPDATA"]=local;window=gui.MainWindow();card=window.left;card.load(media);card.fps.setCurrentText("60");window.show();app.processEvents();card.play();window.hide();time.sleep(.5);app.processEvents();card._preview_presented.clear();card.preview_intervals.clear();before=[process]+process.children(recursive=True);cpu0={x.pid:sum(x.cpu_times()[:2]) for x in before};started=time.perf_counter()
        while time.perf_counter()-started<duration:
            app.processEvents();time.sleep(.005)
        elapsed=time.perf_counter()-started;tree=[process]+process.children(recursive=True);cpu_delta={x.pid:max(0,sum(x.cpu_times()[:2])-cpu0.get(x.pid,sum(x.cpu_times()[:2]))) for x in tree};parent_cpu=cpu_delta.get(process.pid,0)/elapsed/logical*100;child_cpu=sum(v for pid,v in cpu_delta.items() if pid!=process.pid)/elapsed/logical*100;rows.append({"mode":"hidden","cap_fps":.1,"actual_presented_fps":card.actual_preview_fps(),"presentation_interval_ms":{"mean":0,"p95":0},"parent_cpu_percent_normalized":parent_cpu,"child_cpu_percent_normalized":child_cpu,"total_cpu_percent_normalized":parent_cpu+child_cpu,"total_ram_mb":sum(x.memory_info().rss for x in tree)/1048576,"process_count":len(tree),"child_processes":[x.name() for x in tree[1:]],"threads":sum(x.num_threads() for x in tree),"offline_transport_fps":card.actual_fps(),"usb_writes":0});window.exit_application();app.processEvents()
    report={"schema":1,"media":str(media),"duration_per_stage_seconds":duration,"metric":"completed DisplayCard._show_image Qt presentations","rows":rows,"hardware":"USB impossible Sink"};output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--media",type=Path,required=True);p.add_argument("--duration",type=float,default=6);p.add_argument("--output",type=Path,required=True);a=p.parse_args(argv);print(json.dumps(run(a.media,a.duration,a.output),indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
