"""Repeatable, USB-free process profiling for Oni Thermal LCD Control.

The public controller intentionally imports only the standard library.  PySide6,
Pillow and media/protocol modules are loaded inside an isolated worker process so
the report can prove which scenarios caused heavyweight modules to load.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


SCENARIOS = {
    "idle_disconnected": "GUI idle, both LCDs disconnected",
    "idle_connected": "GUI idle, both LCDs simulated connected",
    "dual_static": "Two cached static images",
    "static_gif": "Static image plus synthetic GIF",
    "dual_gif": "Two synthetic GIF streams",
    "static_video": "Static image plus synthetic video",
    "dual_video": "Two synthetic video streams",
    "monitor_overlays": "Simulated hardware-monitor overlays",
    "all_integrations": "Media and simulated integrations enabled",
}


@dataclass(frozen=True)
class ProcessSample:
    seconds: float
    working_set_mb: float
    private_bytes_mb: float
    committed_virtual_mb: float
    cpu_percent: float
    handles: int
    threads: int


def _linear_growth_mb_per_minute(samples: list[ProcessSample], field: str) -> float:
    if len(samples) < 2:
        return 0.0
    xs = [x.seconds for x in samples]
    ys = [getattr(x, field) for x in samples]
    xmean, ymean = statistics.mean(xs), statistics.mean(ys)
    denominator = sum((x - xmean) ** 2 for x in xs)
    return 0.0 if denominator == 0 else 60 * sum((x-xmean)*(y-ymean) for x, y in zip(xs, ys)) / denominator


class _NullHardwareSender:
    """DisplaySession-compatible sink. It cannot open a device or issue I/O."""
    enabled = False
    def __init__(self):
        self.calls = 0
        self.bytes = 0
        self.closed = False
    def __call__(self, frame):
        self.calls += 1
        amount = int(getattr(frame, "total_bytes", 0))
        self.bytes += amount
        return amount
    def close(self):
        self.closed = True


class _SyntheticSource:
    def __init__(self, size, fps: float, kind: str):
        self.size, self.fps, self.kind = size, fps, kind
        self.index = 0
        self.closed = False
    def next_frame(self):
        from PIL import Image, ImageDraw
        from .playback import MediaFrame
        i = self.index
        base = (i * 11 % 255, i * 23 % 255, i * 37 % 255)
        image = Image.new("RGB", self.size, base)
        ImageDraw.Draw(image).rectangle((i % max(1, self.size[0]-80), 10,
                                         i % max(1, self.size[0]-80)+64, 74), fill="white")
        self.index += 1
        return MediaFrame(image, 1/self.fps, i, i/self.fps)
    def close(self):
        self.closed = True


class _Workload:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.app = self.window = None
        self.sessions = []
        self.schedulers = []
        self.senders = []
        self.overlay_updates = 0
        self._next_overlay = 0.0
        self.gui_shell_fallback = ""
        self.requested_fps = []

    def start(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # Construct the real GUI shell, but substitute a sink before cards are
        # created. Merely launching the profiler can therefore never access USB.
        from PySide6.QtWidgets import QApplication
        from . import gui
        gui.build_gui_sender = lambda _device_id: _NullHardwareSender()
        gui.thermalright_processes = lambda: []
        self.app = QApplication.instance() or QApplication(["oni-performance-profile"])
        try:
            self.window = gui.MainWindow()
            self.cards = (self.window.left, self.window.right)
        except Exception as exc:
            # Keep profiling available while a GUI branch is under development.
            # Two real DisplayCards still account for the dominant preview/card
            # allocations, while the report makes the fallback explicit.
            from PySide6.QtWidgets import QWidget, QHBoxLayout
            self.gui_shell_fallback = f"{type(exc).__name__}: {exc}"
            self.window = QWidget(); layout = QHBoxLayout(self.window)
            left = gui.DisplayCard('9.16" LCD', (1920,462), "0416:5408", hardware_sender=_NullHardwareSender())
            right = gui.DisplayCard('6" LCD', (1280,480), "0416:5302", hardware_sender=_NullHardwareSender())
            layout.addWidget(left); layout.addWidget(right); self.cards = (left, right)
        self.window.hide()
        if self.scenario == "idle_connected":
            for card in self.cards:
                card.connection.setText("Connected (simulated)")
        if self.scenario not in {"idle_disconnected", "idle_connected"}:
            self._start_media()

    def _static(self, vid_pid: str, colour: str):
        from PIL import Image
        from .media import MediaPipeline
        pipe = MediaPipeline(1)
        prepared, encoded = pipe.prepare_image(Image.new("RGB", (320, 180), colour), vid_pid)
        # Drop the preview-sized intermediate immediately; retain only the exact
        # encoded frame, matching steady-state static playback.
        del prepared
        return pipe, encoded

    def _session(self, name, frame, fps):
        from .runtime import DisplaySession
        sender = _NullHardwareSender()
        session = DisplaySession(name, sender, refresh_interval=1/fps)
        session.set_media(frame)
        session.play()
        self.requested_fps.append(fps)
        self.senders.append(sender); self.sessions.append(session)

    def _animation(self, name, vid_pid, size, fps, kind):
        from .media import MediaPipeline
        from .playback import FrameScheduler
        pipe = MediaPipeline(1)
        source = _SyntheticSource(size, fps, kind)
        sender = _NullHardwareSender()
        from .runtime import DisplaySession
        session = DisplaySession(name, sender, refresh_interval=1/fps)
        session.play()
        def deliver(media_frame):
            _prepared, encoded = pipe.prepare_image(media_frame.image, vid_pid)
            session.submit(encoded)
        scheduler = FrameScheduler(source, deliver, target_fps=fps)
        scheduler.start()
        self.requested_fps.append(fps)
        self.senders.append(sender); self.sessions.append(session); self.schedulers.append(scheduler)

    def _start_media(self):
        scenario = self.scenario
        if scenario in {"dual_static", "static_gif", "static_video", "monitor_overlays", "all_integrations"}:
            self._static_pipe, frame = self._static("0416:5408", "#13a8c7")
            self._session("static-5408", frame, 6.0)
        if scenario == "dual_static":
            self._static_pipe_2, frame = self._static("0416:5302", "#ddb72b")
            self._session("static-5302", frame, 11.696249)
        if scenario in {"static_gif", "dual_gif", "all_integrations"}:
            self._animation("gif-5302", "0416:5302", (320, 120), 10.0, "gif")
        if scenario == "dual_gif":
            self._animation("gif-5408", "0416:5408", (384, 92), 6.0, "gif")
        if scenario in {"static_video", "dual_video", "all_integrations"}:
            self._animation("video-5302", "0416:5302", (426, 160), 12.0, "video")
        if scenario == "dual_video":
            self._animation("video-5408", "0416:5408", (480, 116), 6.0, "video")

    def tick(self):
        self.app.processEvents()
        if self.scenario in {"monitor_overlays", "all_integrations"} and time.monotonic() >= self._next_overlay:
            # Read-only synthetic values at 4 Hz model bounded provider/render work.
            self._next_overlay = time.monotonic() + .25
            self.overlay_updates += 1

    def metrics(self):
        sched = self.schedulers
        return {
            "frame_queues": [len(x.queue) for x in self.sessions],
            "max_queue_depth": max([len(x.queue) for x in self.sessions] or [0]),
            "actual_fps": [round(x.metrics.actual_fps, 3) for x in self.sessions],
            "requested_fps": self.requested_fps,
            "delivered_frames": [x.metrics.sent for x in self.sessions],
            "dropped_frames": sum(x.metrics.dropped for x in self.sessions) + sum(x.metrics.dropped for x in sched),
            "scheduler_decoded": sum(x.metrics.decoded for x in sched),
            "scheduler_delivered": sum(x.metrics.delivered for x in sched),
            "overlay_updates": self.overlay_updates,
            "usb_open_calls": 0,
            "usb_writes": 0,
            "sink_calls": sum(x.calls for x in self.senders),
            "gui_shell_fallback": self.gui_shell_fallback or None,
        }

    def stop(self):
        for scheduler in self.schedulers: scheduler.stop()
        for session in self.sessions: session.stop()
        if self.window:
            if hasattr(self.window, "tray"): self.window.tray.hide()
            for card in getattr(self, "cards", ()): card.stop()
            self.window.deleteLater()
        if self.app: self.app.processEvents()


def _worker(scenario: str, duration: float, interval: float) -> dict:
    import gc
    import psutil
    process = psutil.Process()
    workload = _Workload(scenario)
    workload.start()
    # Settle startup allocations before treating samples as a short leak signal.
    settle_until = time.monotonic() + min(1.0, max(.1, duration * .2))
    while time.monotonic() < settle_until:
        workload.tick(); time.sleep(.02)
    process.cpu_percent(None)
    started = time.monotonic(); samples = []
    while time.monotonic() - started < duration:
        workload.tick()
        info = process.memory_info()
        samples.append(ProcessSample(
            time.monotonic()-started, info.rss/1048576,
            getattr(info, "private", info.rss)/1048576,
            info.vms/1048576,
            process.cpu_percent(None), process.num_handles() if hasattr(process, "num_handles") else -1,
            process.num_threads()))
        time.sleep(interval)
    runtime = workload.metrics()
    workload.stop(); gc.collect(); time.sleep(.1)
    final = process.memory_info()
    final_handles = process.num_handles() if hasattr(process, "num_handles") else -1
    final_threads = process.num_threads()
    loaded = sorted(name for name in ("PySide6", "PIL", "cv2") if name in sys.modules)
    result = {
        "scenario": scenario, "description": SCENARIOS[scenario], "duration_seconds": duration,
        "sample_count": len(samples), "samples": [asdict(x) for x in samples],
        "working_set_mb": {"start": samples[0].working_set_mb, "end": samples[-1].working_set_mb,
                           "peak": max(x.working_set_mb for x in samples),
                           "growth_mb_per_minute": _linear_growth_mb_per_minute(samples, "working_set_mb")},
        "private_bytes_mb": {"start": samples[0].private_bytes_mb, "end": samples[-1].private_bytes_mb,
                             "peak": max(x.private_bytes_mb for x in samples),
                             "growth_mb_per_minute": _linear_growth_mb_per_minute(samples, "private_bytes_mb")},
        "committed_virtual_mb": {"start": samples[0].committed_virtual_mb,
                                 "end": samples[-1].committed_virtual_mb,
                                 "peak": max(x.committed_virtual_mb for x in samples)},
        "cpu_percent": {"mean": statistics.mean(x.cpu_percent for x in samples),
                        "peak": max(x.cpu_percent for x in samples)},
        "handles": {"start": samples[0].handles, "end": samples[-1].handles,
                    "peak": max(x.handles for x in samples)},
        "threads": {"start": samples[0].threads, "end": samples[-1].threads,
                    "peak": max(x.threads for x in samples)},
        "post_cleanup_working_set_mb": final.rss/1048576,
        "post_cleanup_private_bytes_mb": getattr(final, "private", final.rss)/1048576,
        "post_cleanup_handles": final_handles,
        "post_cleanup_threads": final_threads,
        "loaded_heavy_roots": loaded,
        "opencv_loaded": "cv2" in sys.modules,
        "live_usb_permitted": False,
        "gpu_metrics": {"status": "NOT_AVAILABLE_OFFSCREEN",
                        "reason": "psutil exposes no portable per-process GPU counters; collect packaged visible-run ETW evidence later"},
        **runtime,
    }
    working_delta = samples[-1].working_set_mb - samples[0].working_set_mb
    private_delta = samples[-1].private_bytes_mb - samples[0].private_bytes_mb
    result["short_leak_check"] = {
        "status": "PASS_NO_OBVIOUS_GROWTH" if (
            working_delta < 8 and private_delta < 8 and
            samples[-1].handles <= samples[0].handles + 2 and
            samples[-1].threads <= samples[0].threads and
            runtime["max_queue_depth"] <= 1) else "INVESTIGATE",
        "working_set_delta_mb": working_delta,
        "private_bytes_delta_mb": private_delta,
        # Qt/Windows may fluctuate by one or two event/notifier handles. Treat
        # bounded jitter as stable, but never conceal sustained positive growth.
        "handles_stable_during_sample": samples[-1].handles <= samples[0].handles + 2,
        "threads_stable_during_sample": samples[-1].threads <= samples[0].threads,
        "queue_bounded": runtime["max_queue_depth"] <= 1,
        "note": "Short-window screen only; run the prepared soak command before release.",
    }
    return result


def run_profile(output: Path, duration: float = 5.0, interval: float = .25,
                scenarios=None) -> dict:
    selected = list(scenarios or SCENARIOS)
    results = []
    env = os.environ.copy(); env["QT_QPA_PLATFORM"] = "offscreen"
    for scenario in selected:
        if scenario not in SCENARIOS: raise ValueError(f"unknown scenario: {scenario}")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            command = [sys.executable, "-m", "thermalright_lcd.performance", "--worker", scenario,
                       "--duration", str(duration), "--interval", str(interval), "--output", str(temp_path)]
            completed = subprocess.run(command, env=env, text=True, capture_output=True, timeout=duration+30)
            if completed.returncode:
                raise RuntimeError(f"scenario {scenario} failed: {completed.stderr.strip()}")
            results.append(json.loads(temp_path.read_text(encoding="utf-8")))
        finally:
            temp_path.unlink(missing_ok=True)
    report = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "profile_kind": "short isolated offline measurements",
        "usb_writes": 0,
        "limitations": [
            "Connected state and sensor providers are simulated; no USB handles are opened.",
            "Synthetic video exercises the same bounded scheduler/encoding path without importing OpenCV.",
            "Short-run growth slopes expose obvious leaks but do not replace a multi-hour soak test.",
            "Offscreen Qt measurements can differ from a visible Windows desktop compositor session.",
        ],
        "scenarios": results,
    }
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="USB-free Oni performance profiler")
    parser.add_argument("--output", type=Path, default=Path("analysis/performance-profile.json"))
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--interval", type=float, default=.25)
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    parser.add_argument("--worker", choices=SCENARIOS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.interval <= 0: parser.error("duration and interval must be positive")
    if args.worker:
        result = _worker(args.worker, args.duration, args.interval)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    else:
        report = run_profile(args.output, args.duration, args.interval, args.scenario)
        print(f"Wrote {args.output} ({len(report['scenarios'])} scenarios, USB writes 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
