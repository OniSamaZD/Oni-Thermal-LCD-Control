from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from thermalright_lcd.gui import MainWindow


MODES = {
    # The normal variants deliberately traverse the ordinary full static
    # composition/JPEG/submission path at every content deadline.
    "normal-0.5": {"label": "0.5", "content_interval": 2.0, "cached_interval": 3600.0},
    "normal-1": {"label": "1", "content_interval": 1.0, "cached_interval": 3600.0},
    # These reproduce the historical low-update behavior rather than silently
    # inheriting the newer two-second physical commit floor.
    "event-driven": {"label": "Event-driven", "content_interval": None, "cached_interval": 3600.0},
    "low-0.1": {"label": "0.1", "content_interval": 10.0, "cached_interval": 3600.0},
    # Current production hypothesis: reuse JPEG pixels but reconstruct a fresh
    # protocol transaction through the normal send/ACK path every two seconds.
    "fresh-cached": {"label": "Event-driven", "content_interval": None, "cached_interval": 2.0},
}


class Evidence:
    def __init__(self, path: Path, mode: str):
        self.path = path
        self.mode = mode
        self.origin = time.perf_counter()
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.observations: dict[str, list[dict]] = {}
        self.final: dict = {}

    def add(self, event: str, **fields) -> None:
        now = time.perf_counter()
        row = {
            "event": event,
            "elapsed_seconds": now - self.origin,
            "monotonic": now,
            "wall_utc": datetime.now(timezone.utc).isoformat(),
            "thread": threading.current_thread().name,
        }
        row.update(fields)
        with self.lock:
            self.events.append(row)

    def hook(self, event: str, **fields) -> None:
        self.add(event, **fields)

    def snapshot(self) -> None:
        with self.lock:
            payload = {
                "schema": 1,
                "scenario": "dual-splash-fallback",
                "mode": self.mode,
                "started_wall_utc": self.events[0]["wall_utc"] if self.events else None,
                "events": list(self.events),
                "physical_observations": {key: list(value) for key, value in self.observations.items()},
                "final": dict(self.final),
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)


class Observer(QWidget):
    def __init__(self, evidence: Evidence, cards: dict, minimum_seconds: float, timeout_seconds: float):
        super().__init__()
        self.evidence = evidence
        self.cards = cards
        self.minimum_seconds = minimum_seconds
        self.timeout_seconds = timeout_seconds
        self.minimum_elapsed = False
        self.eligible: set[str] = set()
        self.end_observed: set[str] = set()
        self.setWindowTitle(f"Oni LCD splash observer — {evidence.mode}")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        self.instructions = QLabel(
            "For EACH LCD, click CONTENT APPEARED when the test image first becomes visible. Then click "
            "SPLASH NOW immediately if it returns to the Thermalright logo. After the five-minute gate, "
            "record each panel's current state."
        )
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)
        self.clock = QLabel("Starting…")
        layout.addWidget(self.clock)
        grid = QGridLayout()
        for column, device_id in enumerate(("0416:5408", "0416:5302")):
            title = "9.16 / PID 5408" if device_id.endswith("5408") else "6.86 / PID 5302"
            grid.addWidget(QLabel(title), 0, column)
            appeared = QPushButton("CONTENT APPEARED")
            appeared.clicked.connect(lambda _=False, d=device_id: self.observe(d, "content_appeared"))
            grid.addWidget(appeared, 1, column)
            splash = QPushButton("SPLASH NOW")
            splash.clicked.connect(lambda _=False, d=device_id: self.observe(d, "splash"))
            grid.addWidget(splash, 2, column)
            visible = QPushButton("CONTENT STILL VISIBLE")
            visible.setEnabled(False)
            visible.clicked.connect(lambda _=False, d=device_id: self.observe(d, "content_visible"))
            grid.addWidget(visible, 3, column)
            setattr(self, f"visible_{device_id[-4:]}", visible)
        layout.addLayout(grid)
        self.resize(620, 210)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def observe(self, device_id: str, result: str) -> None:
        now = time.perf_counter()
        events = [e for e in self.evidence.events if e.get("device_id") == device_id and e["event"] == "transport_complete"]
        last = events[-1] if events else None
        observation = {
            "result": result,
            "elapsed_seconds": now - self.evidence.origin,
            "wall_utc": datetime.now(timezone.utc).isoformat(),
            "seconds_since_last_transport_complete": None if last is None else now - last["monotonic"],
            "last_transport_event": last,
        }
        self.evidence.observations.setdefault(device_id, []).append(observation)
        self.evidence.add("physical_observation", device_id=device_id, **observation)
        self.evidence.snapshot()
        if device_id in self.eligible and result in {"splash", "content_visible"}:
            self.end_observed.add(device_id)
        if len(self.end_observed) == 2:
            QApplication.instance().quit()

    def tick(self) -> None:
        elapsed = time.perf_counter() - self.evidence.origin
        states = " · ".join(
            f"{device_id[-4:]} {card.session.state.value} commits={card.session.metrics.sent} error={card.session.metrics.last_error or 'none'}"
            for device_id, card in self.cards.items()
        )
        self.clock.setText(f"Elapsed {elapsed:.1f}s / minimum {self.minimum_seconds:.0f}s\n{states}")
        for device_id in self.cards:
            appeared = next((row for row in self.evidence.observations.get(device_id, []) if row["result"] == "content_appeared"), None)
            if appeared and elapsed - appeared["elapsed_seconds"] >= self.minimum_seconds and device_id not in self.eligible:
                self.eligible.add(device_id)
                getattr(self, f"visible_{device_id[-4:]}").setEnabled(True)
                self.evidence.add("device_minimum_observation_elapsed", device_id=device_id,minimum_seconds=self.minimum_seconds,content_appeared_elapsed=appeared["elapsed_seconds"])
                self.evidence.snapshot()
        if len(self.eligible) == 2 and not self.minimum_elapsed:
            self.minimum_elapsed = True
            self.evidence.add("minimum_observation_elapsed", minimum_seconds=self.minimum_seconds)
            self.instructions.setText("Five continuous minutes since appearance reached. Record each panel's CURRENT state.")
            self.evidence.snapshot()
        if elapsed >= self.timeout_seconds:
            self.evidence.add("observer_timeout", timeout_seconds=self.timeout_seconds)
            QApplication.instance().quit()


def make_image(path: Path, mode: str) -> None:
    colors = {
        "normal-0.5": (0, 120, 230), "normal-1": (0, 185, 110),
        "event-driven": (160, 45, 210), "low-0.1": (220, 75, 35),
        "fresh-cached": (215, 170, 0),
    }
    canvas = Image.new("RGB", (1920, 480), colors[mode])
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((16, 16, 1903, 463), outline=(255, 255, 255), width=10)
    draw.text((70, 170), f"ONI RETENTION TEST: {mode}", fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    draw.text((70, 230), "CLICK SPLASH NOW IMMEDIATELY IF THIS DISAPPEARS", fill=(255, 255, 255))
    canvas.save(path)
    canvas.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=tuple(MODES), required=True)
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--observation-timeout", type=float, default=600.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 300:
        raise ValueError("physical splash-fallback runs must be at least 300 seconds")
    if args.observation_timeout <= args.seconds:
        raise ValueError("observation timeout must exceed the minimum duration")

    os.environ["ONI_LCD_INSTANCE_NAME"] = f"OniSplashFallback-{os.getpid()}"
    os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="oni-splash-fallback-")
    image = args.output.with_suffix(".png")
    make_image(image, args.mode)
    evidence = Evidence(args.output, args.mode)
    evidence.add("test_started", configuration=MODES[args.mode], minimum_seconds=args.seconds)

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    cards = {card.device_id: card for card in (window.left, window.right)}
    for card in cards.values():
        card.session.trace_hook = evidence.hook
        card.hardware_sender.trace_hook = evidence.hook
        card.load(image)
        card.fps.setCurrentText(MODES[args.mode]["label"])
        card.session.keepalive_interval = MODES[args.mode]["cached_interval"]
        evidence.add(
            "mode_configured", device_id=card.device_id,
            content_interval_seconds=MODES[args.mode]["content_interval"],
            cached_commit_interval_seconds=card.session.keepalive_interval,
        )
        card.play(coordinated=True)

    # Normal variants exercise the complete ordinary composition/JPEG/content
    # submission path. Cached variants intentionally do not regenerate pixels.
    content_timer = QTimer()
    interval = MODES[args.mode]["content_interval"]
    if interval is not None:
        content_timer.setInterval(round(interval * 1000))
        def refresh_content():
            for card in cards.values():
                evidence.add("content_refresh_begin", device_id=card.device_id,prepares=card.pipeline.total_prepares)
                # The normal-path control must exercise a genuinely new full
                # composition/JPEG submission. MediaPipeline intentionally
                # returns the same cached EncodedFrame for unchanged pixels,
                # and DisplaySession correctly suppresses that duplicate.
                # Clearing only the host-side image cache here prevents the
                # control from silently degenerating into a single-send test.
                card.pipeline.clear()
                card.refresh()
                evidence.add("content_refresh_end", device_id=card.device_id,prepares=card.pipeline.total_prepares)
        content_timer.timeout.connect(refresh_content)
        content_timer.start()

    observer = Observer(evidence, cards, args.seconds, args.observation_timeout)
    observer.show()
    checkpoint = QTimer()
    checkpoint.timeout.connect(evidence.snapshot)
    checkpoint.start(1000)
    exit_code = app.exec()

    content_timer.stop()
    checkpoint.stop()
    evidence.add("shutdown_begin")
    for device_id, card in cards.items():
        evidence.final[device_id] = {
            "state_before_shutdown": card.session.state.value,
            "completed_commits": card.session.metrics.sent,
            "content_sends": card.session.metrics.content_sends,
            "cached_commits": card.session.metrics.keepalive_sends,
            "fresh_transaction_frames": card.session.metrics.transport_frames_rebuilt,
            "acks": getattr(card.hardware_sender, "acks", 0),
            "last_error": card.session.metrics.last_error,
            "prepares": card.pipeline.total_prepares,
            "sender_open_before_shutdown": bool(getattr(card.hardware_sender, "_opened", False)),
        }
    window.shutdown()
    evidence.add("shutdown_complete", exit_code=exit_code)
    evidence.snapshot()
    print(json.dumps({"output": str(args.output), "observations": evidence.observations, "final": evidence.final}, indent=2))


if __name__ == "__main__":
    main()
