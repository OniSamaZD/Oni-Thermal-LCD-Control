from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import MainWindow
from thermalright_lcd.hardware_monitor import templates


def main():
    root = Path(__file__).resolve().parents[1]
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    started = time.perf_counter()
    window.start_monitor_layout("0416:5408", templates("0416:5408")["Gaming Dashboard"])
    window.start_monitor_layout("0416:5302", templates("0416:5302")["Gaming Dashboard"])
    result = {}

    def finish():
        nonlocal result
        for card in (window.left, window.right):
            timings = list(card.session.frame_timings)
            result[card.device_id] = {
                "state": card.session.state.value,
                "completed_frames": card.session.metrics.sent,
                "actual_fps": card.session.metrics.actual_fps,
                "bytes": card.session.metrics.bytes,
                "last_error": card.session.metrics.last_error,
                "transport_ms": card.session.metrics.last_send_ms,
                "ack_ms": card.session.metrics.ack_latency_ms,
                "complete_interval_ms": card.session.metrics.complete_interval_ms,
                "scheduler_overruns": card.session.metrics.scheduler_overruns,
                "bounded_queue_depth": len(card.session.queue),
                "timing_samples": len(timings),
            }
        window.stop_monitor_layout("0416:5408")
        window.stop_monitor_layout("0416:5302")
        window.shutdown()
        report = {
            "schema": 1,
            "scenario": "physical-dual-gaming-dashboard",
            "duration_seconds": time.perf_counter() - started,
            "sensor_poll_interval_ms": window.settings.sensor_interval_ms,
            "template": "Gaming Dashboard",
            "results": result,
        }
        (root / "analysis" / "physical-monitor-output-20260829.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        app.quit()

    QTimer.singleShot(15000, finish)
    app.exec()


if __name__ == "__main__":
    main()
