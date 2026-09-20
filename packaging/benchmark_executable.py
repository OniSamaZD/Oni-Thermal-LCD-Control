"""Measure cold-ish GUI smoke startup and process-tree peak working set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

import psutil


def one_run(executable: Path) -> dict:
    env = os.environ.copy()
    env["ONI_LCD_GUI_SMOKE_TEST"] = "1"
    env["ONI_LCD_INSTANCE_NAME"] = f"OniThermalLcdSmoke-{os.getpid()}-{time.time_ns()}"
    started = time.perf_counter()
    process = subprocess.Popen([str(executable)], env=env)
    peak = 0
    handles = 0
    threads = 0
    try:
        root = psutil.Process(process.pid)
        while process.poll() is None:
            members = [root]
            try:
                members.extend(root.children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            working_set = 0
            for member in members:
                try:
                    working_set += member.memory_info().rss
                    handles = max(handles, member.num_handles())
                    threads = max(threads, member.num_threads())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak = max(peak, working_set)
            if time.perf_counter() - started > 30:
                process.kill()
                raise TimeoutError(f"smoke startup timed out: {executable}")
            time.sleep(0.01)
    finally:
        if process.poll() is None:
            process.kill()
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(f"smoke startup exited {process.returncode}: {executable}")
    return {
        "pid": process.pid,
        "executable_path": str(executable),
        "role": "isolated packaged GUI smoke",
        "exit_code": process.returncode,
        "elapsed_seconds": elapsed,
        "peak_working_set_bytes": peak,
        "peak_handle_count": handles,
        "peak_thread_count": threads,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema": 1, "smoke_duration_seconds": 0.75, "candidates": {}}
    for raw in args.candidate:
        name, value = raw.split("=", 1)
        executable = Path(value).resolve()
        samples = [one_run(executable) for _ in range(args.runs)]
        elapsed = [sample["elapsed_seconds"] for sample in samples]
        memory = [sample["peak_working_set_bytes"] for sample in samples]
        report["candidates"][name] = {
            "path": str(executable),
            "file_size_bytes": executable.stat().st_size,
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "runs": samples,
            "median_elapsed_seconds": statistics.median(elapsed),
            "median_peak_working_set_bytes": statistics.median(memory),
            "max_peak_working_set_bytes": max(memory),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
