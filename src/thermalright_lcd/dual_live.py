from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from .live_state import PersistentReplayMachine


def run_dual_persistence(specs: dict[str, dict], duration_seconds: float = 30.0) -> dict:
    """Run two already-authorized transports independently with a shared start gate."""
    if set(specs)!={"0416:5408","0416:5302"}:raise ValueError("exactly both confirmed devices are required")
    gate=threading.Barrier(2,timeout=8)
    def worker(pid):
        spec=specs[pid]
        result=PersistentReplayMachine(spec["target"],spec["sequence"],spec["transport"],
            spec["plan"]["frame_count_hard_max"],spec["policy"].interval_seconds,
            duration_seconds=duration_seconds,start_gate=gate.wait).run()
        if not result["success"]:
            try:gate.abort()
            except Exception:pass
        return result
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix="dual-lcd") as pool:
        futures={pid:pool.submit(worker,pid) for pid in specs}
        results={pid:f.result() for pid,f in futures.items()}
    starts=[r["first_frame_epoch"] for r in results.values() if r["first_frame_epoch"] is not None]
    ends=[r["data_phase_ended_epoch"] for r in results.values() if r["data_phase_ended_epoch"] is not None]
    overlap=max(0.0,min(ends)-max(starts)) if len(starts)==2 and len(ends)==2 else 0.0
    total_bytes=sum(r["written_bytes"] for r in results.values())
    return {"success":all(r["success"] for r in results.values()),"devices":results,
        "combined":{"both_started":len(starts)==2,"first_frame_start_delta_ms":abs(starts[0]-starts[1])*1000 if len(starts)==2 else None,
            "simultaneous_active_seconds":overlap,"combined_written_bytes":total_bytes,
            "combined_usb_bytes_per_second":total_bytes/overlap if overlap>0 else 0,
            "all_handles_closed":all(r["final_state"]=="CLOSED" for r in results.values()),"automatic_retries":0}}
