from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor


@dataclass(frozen=True)
class PersistencePolicy:
    """Evidence-backed policy for refreshing a cached, already encoded frame."""

    device_id: str
    requested_fps: float
    observed_fps: float
    interval_seconds: float
    requires_continuous_frames: bool
    expected_response: str
    confidence: str
    evidence: tuple[str, ...]
    # Physical 60-second threshold tests on both exact panels proved that
    # 0.5 FPS is continuously visible while 0.2 FPS and below flicker.  This
    # is a cached full-frame commit floor, not a content/render cadence.
    keepalive_interval_seconds: float = 2.0


class PersistencePolicy5408(PersistencePolicy):
    def __init__(self):
        super().__init__(
            device_id="0416:5408",
            requested_fps=6.0,
            observed_fps=6.405121282275257,
            interval_seconds=1.0 / 6.0,
            requires_continuous_frames=True,
            expected_response="exact 512-byte FRAME_ACK after every frame",
            confidence="HIGH CONFIDENCE",
            evidence=(
                "20-frame vendor capture: median start interval 156.125 ms; timer-quantized clusters around 6 FPS",
                "same-session lifecycle: next frame 170.758 ms after prior frame start",
                "no post-ACK commit or keepalive payload observed",
            ),
        )


class PersistencePolicy5302(PersistencePolicy):
    def __init__(self):
        super().__init__(
            device_id="0416:5302",
            requested_fps=11.696248631841662,
            observed_fps=11.696248631841662,
            interval_seconds=0.08549749851226807,
            requires_continuous_frames=True,
            expected_response="none after frame; readiness response occurs only after initialization",
            confidence="CONFIRMED",
            evidence=(
                "physical test: one captured frame appeared briefly and vanished during a zero-write handle hold",
                "Thermal Engine 0.8.2-pre: 30 FPS QTimer renders and calls send_frame for every tick, including static scenes",
                "43-frame vendor capture: median start interval 85.497 ms and median write duration 85.249 ms",
            ),
        )


POLICIES = {p.device_id: p for p in (PersistencePolicy5408(), PersistencePolicy5302())}

# Physically validated 2026-08-27 with distinct timeline-correct video frames.
# These are video submission targets, not replacements for cached/static
# persistence evidence. Actual transport remains measured independently.
VIDEO_TRANSPORT_TARGETS={"0416:5408":45.0,"0416:5302":30.0}

def video_transport_target(device_id:str,quality_profile:str="Balanced")->float:
    """Measured Auto target; quality affects report-bound PID 5302 throughput."""
    if device_id=="0416:5302":return {"Quality":20.0,"Balanced":30.0,"Performance":43.0,"Extreme FPS":54.0}.get(quality_profile,30.0)
    return VIDEO_TRANSPORT_TARGETS[device_id]


def bounded_test_plan(device_id: str, duration_seconds: float = 30.0) -> dict:
    """Return an offline-only hard budget for a repeated captured-frame test."""
    policy = POLICIES[device_id]
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    if device_id == "0416:5302":
        # The blocking HID frame duration, not the faster requested timer, bounds
        # actual delivery. First frame starts at t=0.
        # Floor guarantees the final blocking frame can complete within the
        # hard wall-clock window at the observed start-to-start cadence.
        frames = floor(duration_seconds * policy.observed_fps)
        frame_writes, frame_bytes = 335, 171_520
        init_writes, init_bytes = 1, 512
        sequence = "0416:5302/pid5302-same-session-first-frame-transaction-1"
    elif device_id == "0416:5408":
        frames = floor(duration_seconds * policy.requested_fps)
        frame_writes, frame_bytes = 45, 182_272
        init_writes, init_bytes = 1, 2_048
        sequence = "0416:5408/pid5408-new-session-first-frame-transaction-1"
    else:
        raise ValueError("device is not allowlisted for persistence")
    return {
        "offline_only": True,
        "live_authorized": False,
        "device_id": device_id,
        "sequence_id": sequence,
        "duration_seconds": duration_seconds,
        "frame_count_hard_max": frames,
        "writes_hard_max": init_writes + frames * frame_writes,
        "bytes_hard_max": init_bytes + frames * frame_bytes,
        "expected_ack_count": frames if device_id == "0416:5408" else 0,
        "estimated_usb_bytes_per_second": round(frames * frame_bytes / duration_seconds, 3),
        "zero_retries": True,
        "policy": asdict(policy),
    }


def bounded_generated_plan(device_id: str, frame_writes: int, frame_bytes: int,
                           sequence_id: str, duration_seconds: float = 30.0) -> dict:
    """Hard budget for one prepared generated-frame persistence proof."""
    base=bounded_test_plan(device_id,duration_seconds)
    init_bytes=2048 if device_id=="0416:5408" else 512
    frames=base["frame_count_hard_max"]
    base.update({"sequence_id":sequence_id,"source_kind":"generated",
                 "frame_writes":frame_writes,"frame_bytes":frame_bytes,
                 "writes_hard_max":1+frames*frame_writes,
                 "bytes_hard_max":init_bytes+frames*frame_bytes,
                 "estimated_usb_bytes_per_second":round(frames*frame_bytes/duration_seconds,3),
                 "live_authorized":False,"offline_only":True})
    return base
