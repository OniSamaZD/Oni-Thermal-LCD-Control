"""Bounded, USB-impossible real-video lifecycle soak for resource regressions."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path


def run_soak(media: Path, duration: float, output: Path) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    import psutil
    from PySide6.QtWidgets import QApplication
    from .device_connection import DisabledHardwareSender
    from . import gui

    if not media.is_file():raise FileNotFoundError(media)
    if duration<60:raise ValueError("resource soak requires at least 60 playback seconds")
    process=psutil.Process();samples=[];process.cpu_percent(None)
    with tempfile.TemporaryDirectory(prefix="oni-resource-soak-") as local:
        old_local=os.environ.get("LOCALAPPDATA");os.environ["LOCALAPPDATA"]=local
        gui.build_gui_sender=lambda _device_id:DisabledHardwareSender()
        gui.thermalright_processes=lambda:[]
        app=QApplication.instance() or QApplication(["oni-resource-soak"]);window=gui.MainWindow();window.show();app.processEvents()

        def sample(phase):
            info=process.memory_info();runtime=window.runtime_diagnostics()
            samples.append({"elapsed_seconds":round(time.monotonic()-started,3),"phase":phase,"rss_mb":round(info.rss/1048576,3),"private_mb":round(getattr(info,"private",info.rss)/1048576,3),"cpu_percent":process.cpu_percent(None),"os_threads":process.num_threads(),**runtime})

        def run_phase(name,seconds,action=None):
            nonlocal next_action
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                app.processEvents()
                if action and time.monotonic()>=next_action:action();next_action=time.monotonic()+2
                if not samples or time.monotonic()-last_sample[0]>=.5:sample(name);last_sample[0]=time.monotonic()
                time.sleep(.02)

        started=time.monotonic();last_sample=[started];next_action=started
        run_phase("baseline_idle",3)
        window.left.load(media);window.left.play();run_phase("display_a",duration/4)
        window.right.load(media);window.right.play();run_phase("display_a_b",duration/4)
        modes=["Fit","Fill","Center","Stretch"];state=[0]
        def transform():
            state[0]+=1
            for card in (window.left,window.right):card.mode.setCurrentText(modes[state[0]%len(modes)]);card.rotation.setCurrentIndex(state[0]%4)
        run_phase("dual_transform_churn",duration/4,transform)
        paused=[False]
        def pause_resume():
            paused[0]=not paused[0]
            for card in (window.left,window.right):(card.pause() if paused[0] else card.play())
        run_phase("dual_pause_resume",duration/4,pause_resume)
        window.left.stop();window.right.stop();window.left.clear();window.right.clear();run_phase("post_stop_clear",3);sample("post_stop_clear")
        window.shutdown();app.processEvents()
        if old_local is None:os.environ.pop("LOCALAPPDATA",None)
        else:os.environ["LOCALAPPDATA"]=old_local

    phases={}
    for name in dict.fromkeys(x["phase"] for x in samples):
        group=[x for x in samples if x["phase"]==name]
        phases[name]={"rss_start_mb":group[0]["rss_mb"],"rss_end_mb":group[-1]["rss_mb"],"rss_peak_mb":max(x["rss_mb"] for x in group),"cpu_mean_percent":sum(x["cpu_percent"] for x in group)/len(group),"cpu_peak_percent":max(x["cpu_percent"] for x in group),"thread_peak":max(x["os_threads"] for x in group),"decoder_peak":max(x["active_decoders"] for x in group),"scheduler_peak":max(x["scheduler_count"] for x in group),"worker_peak":max(x["active_playback_workers"] for x in group),"decoded_queue_peak":max(max(x["decoded_queue_sizes"]) for x in group),"transport_queue_peak":max(max(x["transport_queue_sizes"]) for x in group),"preview_pending_peak":max(max(x["preview_pending"]) for x in group),"retained_full_resolution_peak":max(x["retained_full_resolution_frames"] for x in group),"metrics_history_peak":max(max(x["metrics_history_lengths"]) for x in group)}
    report={"schema":1,"media":str(media),"playback_duration_seconds":duration,"usb_writes":0,"hardware_sender":"DisabledHardwareSender","sync_status":"NOT_IMPLEMENTED_NO_EXTRA_PIPELINE","samples":samples,"phases":phases,"peak_rss_mb":max(x["rss_mb"] for x in samples),"peak_cpu_percent":max(x["cpu_percent"] for x in samples)}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report


def main(argv=None):
    parser=argparse.ArgumentParser(description="USB-free bounded real-video resource soak")
    parser.add_argument("--media",type=Path,required=True);parser.add_argument("--duration",type=float,default=60);parser.add_argument("--output",type=Path,default=Path("analysis/resource-soak.json"));args=parser.parse_args(argv)
    report=run_soak(args.media,args.duration,args.output);print(f"Wrote {args.output}: peak RSS {report['peak_rss_mb']:.1f} MB, USB writes 0");return 0


if __name__=="__main__":raise SystemExit(main())
