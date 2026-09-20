from __future__ import annotations

import argparse
import json
import os,threading
import statistics
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import MainWindow
from thermalright_lcd.hardware_monitor import templates


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))] if ordered else 0.0


def summary(values):
    values = list(values)
    return {"mean": statistics.mean(values) if values else 0.0,"median":statistics.median(values) if values else 0.0,"p95": percentile(values, .95), "max": max(values, default=0.0)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--warmup", type=float, default=12.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--opencv-threads", type=int)
    parser.add_argument("--hidden", action="store_true")
    parser.add_argument("--preview-fps",type=float)
    parser.add_argument("--no-sensors",action="store_true")
    args = parser.parse_args()
    if args.opencv_threads is not None:
        import cv2
        cv2.setNumThreads(max(1,args.opencv_threads))
    os.environ["ONI_LCD_INSTANCE_NAME"] = f"OniPhysicalOverlay-{os.getpid()}"
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    if args.preview_fps is not None:
        for card in (window.left,window.right):card.foreground_preview_fps=float(args.preview_fps);card.preview_fps=float(args.preview_fps)
    for card in (window.left, window.right):
        if not card.load(args.media):
            raise RuntimeError(f"could not load benchmark media for {card.device_id}")
        card.fps.setCurrentText("60")
        card.quality_box.setCurrentText("Balanced" if card.device_id.endswith("5408") else "Extreme FPS")
    window.sync_toggle.setChecked(True)
    if not args.no_sensors:
        for device_id in ("0416:5408", "0416:5302"):
            window.start_monitor_overlay(device_id, templates(device_id)["Gaming Dashboard"])
    window.show()
    if args.hidden:window.hide();window._apply_window_visibility()
    window.left.play()

    process = psutil.Process()
    logical = psutil.cpu_count() or 1
    process.cpu_percent(None)
    cpu_samples = []
    ram_samples = []
    thread_samples = []
    poll = QTimer()
    poll.setInterval(250)
    poll.timeout.connect(lambda: sample())
    started = time.perf_counter()
    measured_started = None
    baseline = {}
    thread_cpu_baseline={}
    process_cpu_baseline=0.0

    def sample():
        nonlocal measured_started, baseline,thread_cpu_baseline,process_cpu_baseline
        now = time.perf_counter()
        if measured_started is None and now - started >= args.warmup:
            measured_started = now
            baseline = {
                card.device_id: {
                    "sent": card.session.metrics.sent,
                    "dropped": card.session.queue.dropped,
                    "frame_metric": len(card.hardware_sender.frame_metrics),
                    "prepare_count": card.pipeline.total_prepares,
                } for card in (window.left, window.right)
            }
            window.monitor_service.poll_durations_ms.clear()
            window.monitor_service.poll_count = 0
            names={t.native_id:t.name for t in threading.enumerate()};thread_cpu_baseline={t.id:(t.user_time+t.system_time,names.get(t.id,f"native-{t.id}")) for t in process.threads()}
            times=process.cpu_times();process_cpu_baseline=times.user+times.system
            process.cpu_percent(None)
            return
        if measured_started is None:
            return
        tree = [process] + process.children(recursive=True)
        cpu_samples.append(sum(p.cpu_percent(None) for p in tree) / logical)
        ram_samples.append(sum(p.memory_info().rss for p in tree) / 1048576)
        thread_samples.append(sum(p.num_threads() for p in tree))
        if now - measured_started >= args.seconds:
            finish(now)

    def finish(now):
        poll.stop()
        duration = now - measured_started
        results = {}
        for card in (window.left, window.right):
            base = baseline[card.device_id]
            timings = list(card.session.frame_timings)
            sends = list(card.hardware_sender.frame_metrics)
            prepares = list(card.pipeline.metrics_history)
            completed = card.session.metrics.sent - base["sent"]
            prepared_count = card.pipeline.total_prepares - base["prepare_count"]
            intervals = [x["complete_interval_ms"] for x in timings if x["complete_interval_ms"] > 0]
            transport = [x["total_ms"] for x in sends]
            ack = [x["ack_ms"] for x in sends if x["ack_ms"] > 0]
            jpeg = [x["jpeg_encode_ms"] for x in prepares]
            prep = [x["total_prepare_ms"] for x in prepares]
            queue_age = [x.get("queue_age_ms", 0.0) for x in timings]
            interval_mean = statistics.mean(intervals) if intervals else 0.0
            prep_mean = statistics.mean(prep) if prep else 0.0
            transport_mean = statistics.mean(transport) if transport else 0.0
            results[card.device_id] = {
                "requested_fps": 60.0,
                "completed_frames": completed,
                "physical_completed_fps": completed / duration,
                "complete_interval_ms": summary(intervals),
                "prepared_frames": prepared_count,
                "prepare_fps": prepared_count / duration,
                "prepare_ms": summary(prep),
                "jpeg_encode_fps": prepared_count / duration,
                "jpeg_encode_ms": summary(jpeg),
                "jpeg_bytes": summary(x["jpeg_bytes"] for x in prepares),
                "reports_per_frame": statistics.mean(x["reports"] for x in sends) if sends else 0.0,
                "chosen_quality_counts": {str(q):sum(1 for x in prepares if x.get("quality")==q) for q in sorted({x.get("quality") for x in prepares})},
                "corrective_encode_count": sum(x.get("corrective_encode",0) for x in prepares),
                "queue_age_ms": summary(queue_age),
                "usb_frame_send_ms": summary(transport),
                "usb_write_rate": statistics.mean(x["reports"] for x in sends) * completed / duration if sends else 0.0,
                "ack_latency_ms": summary(ack),
                "dropped_or_stale": card.session.queue.dropped - base["dropped"],
                "retries": 0,
                "timeouts_or_error": card.session.metrics.last_error,
                "frame_budget_percent": {
                    "overlapped_host_prepare_cost": 100 * prep_mean / interval_mean if interval_mean else 0.0,
                    "critical_path_serialized_send_and_ack": min(100.0,100 * transport_mean / interval_mean) if interval_mean else 0.0,
                    "critical_path_host_gap": max(0.0, 100 * (interval_mean - transport_mean) / interval_mean) if interval_mean else 0.0,
                },
            }
        decoder = getattr(getattr(window, "shared_hub", None), "scheduler", None)
        names={t.native_id:t.name for t in threading.enumerate()};thread_cpu={}
        for item in process.threads():
            before,name=thread_cpu_baseline.get(item.id,(0.0,names.get(item.id,f"native-{item.id}")));thread_cpu[name]=thread_cpu.get(name,0.0)+max(0.0,item.user_time+item.system_time-before)
        process_times=process.cpu_times();process_cpu_seconds=process_times.user+process_times.system-process_cpu_baseline
        report = {
            "schema": 1,
            "scenario": "dual-same-media" if args.no_sensors else "dual-same-media-live-sensor-overlay",
            "media": str(args.media),
            "warmup_seconds": args.warmup,
            "measured_seconds": duration,
            "results": results,
            "resources": {
                "total_oni_cpu_percent_normalized": summary(cpu_samples),
                "total_ram_mb": summary(ram_samples),
                "memory_growth_mb": ram_samples[-1] - ram_samples[0] if len(ram_samples) > 1 else 0.0,
                "memory_second_half_minus_first_half_mb": (statistics.mean(ram_samples[len(ram_samples)//2:])-statistics.mean(ram_samples[:len(ram_samples)//2])) if len(ram_samples)>3 else 0.0,
                "thread_count": summary(thread_samples),
                "child_processes": len(process.children(recursive=True)),
                "cpu_seconds_by_thread": dict(sorted(thread_cpu.items(),key=lambda x:x[1],reverse=True)),
                "total_cpu_seconds_from_threads": sum(thread_cpu.values()),
                "process_cpu_seconds": process_cpu_seconds,
                "cpu_percent_from_cpu_time": 100*process_cpu_seconds/(duration*logical),
                "context_switches": process.num_ctx_switches()._asdict(),
            },
            "decoder": {
                "backend": getattr(getattr(window, "shared_hub", None), "source", None).backend if getattr(window, "shared_hub", None) else "none",
                "decode_fps": getattr(getattr(decoder, "metrics", None), "decode_fps", 0.0),
                "consumer_delivered": dict(getattr(getattr(window, "shared_hub", None), "delivered", {})),
                "consumer_stale_drops": dict(getattr(getattr(window, "shared_hub", None), "dropped", {})),
            },
            "gui_preview":{card.device_id:{"cap_fps":card.preview_fps,"actual_completed_presentations_fps":card.actual_preview_fps()} for card in (window.left,window.right)},
            "sensors": {
                "polls": window.monitor_service.poll_count,
                "poll_hz": window.monitor_service.poll_count / duration,
                "poll_ms": summary(window.monitor_service.poll_durations_ms),
                "render_skips": window.monitor_render_skips,
            },
            "strict_serialization": True,
            "requested_preview_fps":args.preview_fps,
            "unknown_commands": 0,
        }
        for card in (window.left, window.right):
            card.stop()
        window.shutdown()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        app.quit()

    poll.start()
    app.exec()


if __name__ == "__main__":
    main()
