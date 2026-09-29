from __future__ import annotations

import argparse
from collections import deque
import json
import os,threading
import statistics
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermalright_lcd import gui as gui_module
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.playback import PyAvVideoSource
from thermalright_lcd.hardware_monitor import MonitorElement, MonitorLayout


def benchmark_layout(device_id):
    width, height = ((1920, 462) if device_id == "0416:5408" else (1280, 480))
    return MonitorLayout(
        "Benchmark overlay", device_id, width, height,
        background_source="current_media",
        elements=[
            MonitorElement("label + value", 30, 24, 330, 78, text="CPU", sensor_id="cpu.usage", suffix="%"),
            MonitorElement("label + value", 390, 24, 330, 78, text="GPU", sensor_id="gpu.usage", suffix="%"),
            MonitorElement("line graph", 30, height - 130, width - 60, 95, sensor_id="cpu.usage"),
        ],
    )


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))] if ordered else 0.0


def summary(values):
    values = list(values)
    return {"mean": statistics.mean(values) if values else 0.0,"median":statistics.median(values) if values else 0.0,"p95": percentile(values, .95), "max": max(values, default=0.0)}


def trend(values):
    values = list(values)
    return {**summary(values), "initial": values[0] if values else 0.0,
            "final": values[-1] if values else 0.0,
            "net_growth": values[-1] - values[0] if len(values) > 1 else 0.0}


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
    parser.add_argument("--device", choices=("both", "0416:5408", "0416:5302"), default="both")
    parser.add_argument("--decoder", choices=("pyav", "pyav-software", "pyav-d3d11va"), default="pyav")
    args = parser.parse_args()
    if args.opencv_threads is not None:
        import cv2
        cv2.setNumThreads(max(1,args.opencv_threads))
    os.environ["ONI_LCD_INSTANCE_NAME"] = f"OniPhysicalOverlay-{os.getpid()}"
    os.environ["ONI_LCD_PROFILE_STAGES"] = "1"
    if args.decoder != "pyav":
        def benchmark_source(path,loop=True,decode_size=None,prefer_scaled_ffmpeg=True,output_fps=None,decode_cover=True,decoder_backend=None):
            return PyAvVideoSource(path,decode_size,loop,cover=decode_cover,hardware_acceleration=None if args.decoder=="pyav-software" else "d3d11va",allow_hardware_fallback=False)
        gui_module.open_frame_source=benchmark_source
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    cards = tuple(card for card in (window.left, window.right) if args.device == "both" or card.device_id == args.device)
    if args.preview_fps is not None:
        for card in cards:card.foreground_preview_fps=float(args.preview_fps);card.preview_fps=float(args.preview_fps)
    for card in cards:
        if not card.load(args.media):
            raise RuntimeError(f"could not load benchmark media for {card.device_id}")
        card.fps.setCurrentText("60")
        card.quality_box.setCurrentText("Balanced" if card.device_id.endswith("5408") else "Extreme FPS")
    window.sync_toggle.setChecked(len(cards) == 2)
    window.sync_controller.set_enabled(len(cards) == 2)
    if not args.no_sensors:
        for card in cards:
            window.start_monitor_overlay(card.device_id, benchmark_layout(card.device_id))
    window.show()
    if args.hidden:window.hide();window._apply_window_visibility()
    cards[0].play()

    process = psutil.Process()
    logical = psutil.cpu_count() or 1
    process.cpu_percent(None)
    cpu_samples = []
    ram_samples = []
    thread_samples = []
    handle_samples = []
    decoder_pending_samples = []
    consumer_pending_samples = {card.device_id: [] for card in cards}
    session_queue_samples = {card.device_id: [] for card in cards}
    state_changes = {card.device_id: deque(maxlen=64) for card in cards}
    reconnect_events = {card.device_id: 0 for card in cards}
    last_states = {card.device_id: card.session.state.value for card in cards}
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
                    "sender_frames": card.hardware_sender.frames,
                } for card in cards
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
        handle_samples.append(sum(p.num_handles() for p in tree))
        hub = getattr(window, "shared_hub", None)
        scheduler = getattr(hub, "scheduler", None)
        decoder_pending_samples.append(getattr(scheduler, "pending_frames", 0))
        for card in cards:
            consumer_pending_samples[card.device_id].append(int(bool(getattr(hub, "_latest", {}).get(card.device_id))) if hub else 0)
            session_queue_samples[card.device_id].append(len(card.session.queue))
            state = card.session.state.value
            if state != last_states[card.device_id]:
                if state in {"Disconnected", "Reconnecting", "Device Busy", "Error"}:
                    state_changes[card.device_id].append({"at_seconds": now - measured_started, "from": last_states[card.device_id], "to": state})
                    reconnect_events[card.device_id] += int(state == "Reconnecting")
                last_states[card.device_id] = state
        if now - measured_started >= args.seconds:
            finish(now)

    def finish(now):
        poll.stop()
        duration = now - measured_started
        results = {}
        for card in cards:
            base = baseline[card.device_id]
            timings = [x for x in card.session.frame_timings if x["physical_completion"] >= measured_started]
            sends = [x for x in card.hardware_sender.frame_metrics if x["frame"] > base["sender_frames"]]
            prepares = [x for x in card.pipeline.metrics_history if x["timestamp"] >= measured_started]
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
        decoder_source = getattr(getattr(window, "shared_hub", None), "source", None)
        names={t.native_id:t.name for t in threading.enumerate()};thread_cpu={}
        for item in process.threads():
            before,name=thread_cpu_baseline.get(item.id,(0.0,names.get(item.id,f"native-{item.id}")));thread_cpu[name]=thread_cpu.get(name,0.0)+max(0.0,item.user_time+item.system_time-before)
        process_times=process.cpu_times();process_cpu_seconds=process_times.user+process_times.system-process_cpu_baseline
        report = {
            "schema": 1,
            "scenario": ("dual" if len(cards) == 2 else "single") + ("-media" if args.no_sensors else "-media-live-sensor-overlay"),
            "media": str(args.media),
            "warmup_seconds": args.warmup,
            "measured_seconds": duration,
            "results": results,
            "resources": {
                "total_oni_cpu_percent_normalized": summary(cpu_samples),
                "total_ram_mb": trend(ram_samples),
                "memory_growth_mb": ram_samples[-1] - ram_samples[0] if len(ram_samples) > 1 else 0.0,
                "memory_second_half_minus_first_half_mb": (statistics.mean(ram_samples[len(ram_samples)//2:])-statistics.mean(ram_samples[:len(ram_samples)//2])) if len(ram_samples)>3 else 0.0,
                "thread_count": trend(thread_samples),
                "handle_count": trend(handle_samples),
                "handle_growth": handle_samples[-1] - handle_samples[0] if len(handle_samples) > 1 else 0,
                "sample_count": len(cpu_samples),
                "child_processes": len(process.children(recursive=True)),
                "cpu_seconds_by_thread": dict(sorted(thread_cpu.items(),key=lambda x:x[1],reverse=True)),
                "total_cpu_seconds_from_threads": sum(thread_cpu.values()),
                "process_cpu_seconds": process_cpu_seconds,
                "cpu_percent_from_cpu_time": 100*process_cpu_seconds/(duration*logical),
                "context_switches": process.num_ctx_switches()._asdict(),
            },
            "decoder": {
                "backend": decoder_source.backend if decoder_source else "none",
                "requested": args.decoder,
                "hardware_active": bool(getattr(decoder_source, "hardware_active", False)),
                "decoded_frame_format": getattr(decoder_source, "decoded_frame_format", ""),
                "transfer_conversion_ms": summary(getattr(decoder_source, "transfer_conversion_ms", ()) or ()),
                "decode_fps": getattr(getattr(decoder, "metrics", None), "decode_fps", 0.0),
                "decoded": getattr(getattr(decoder, "metrics", None), "decoded", 0),
                "scheduler_delivered": getattr(getattr(decoder, "metrics", None), "delivered", 0),
                "scheduler_dropped": getattr(getattr(decoder, "metrics", None), "dropped", 0),
                "scheduler_error": getattr(getattr(decoder, "metrics", None), "last_error", ""),
                "scheduler_active": bool(getattr(decoder, "is_active", False)),
                "inline_delivery": bool(getattr(decoder, "inline_delivery", False)),
                "consumer_delivered": dict(getattr(getattr(window, "shared_hub", None), "delivered", {})),
                "consumer_stale_drops": dict(getattr(getattr(window, "shared_hub", None), "dropped", {})),
                "consumer_errors": dict(getattr(getattr(window, "shared_hub", None), "errors", {})),
                "decode_ms": summary(getattr(decoder, "decode_durations_ms", ()) or ()),
                "delivery_ms": summary(getattr(decoder, "delivery_durations_ms", ()) or ()),
                "decoder_pending_depth": trend(decoder_pending_samples),
                "consumer_pending_depth": {key: trend(values) for key, values in consumer_pending_samples.items()},
                "session_queue_depth": {key: trend(values) for key, values in session_queue_samples.items()},
                "session_state_changes": {key: list(values) for key, values in state_changes.items()},
                "reconnect_events": reconnect_events,
            },
            "gui_preview":{card.device_id:{"cap_fps":card.preview_fps,"actual_completed_presentations_fps":card.actual_preview_fps()} for card in cards},
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
        for card in cards:
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
