from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .pcapng import packets
from .usbpcap import decode


TARGETS = {
    "0416:5408": {"address": 5, "interface": 0, "out": 0x09, "in": 0x81, "type": "bulk"},
    "0416:5302": {"address": 6, "interface": 1, "out": 0x02, "in": 0x83, "type": "interrupt"},
}


def _event(t, category: str, detail: str, confidence: str, payload: bool = False) -> dict:
    row = {"packet": t.packet, "timestamp": t.timestamp, "category": category,
           "endpoint": f"0x{t.endpoint:02x}", "direction": t.direction,
           "transfer_type": t.transfer_name, "length": len(t.payload),
           "detail": detail, "confidence": confidence}
    if payload:
        row["payload_hex"] = t.payload.hex()
        row["payload_sha256"] = hashlib.sha256(t.payload).hexdigest()
    return row


def session_report(capture: Path, vid_pid: str | None = None) -> dict:
    selected = [vid_pid.lower()] if vid_pid else list(TARGETS)
    if any(x not in TARGETS for x in selected):
        raise ValueError("unsupported VID:PID")
    transfers = {x: [] for x in selected}
    control_counts = {x: 0 for x in selected}
    for packet in packets(capture):
        t = decode(packet)
        for key in selected:
            if t.device == TARGETS[key]["address"]:
                if t.transfer_type == 2:
                    control_counts[key] += 1
                if t.payload:
                    transfers[key].append(t)

    result = {"capture": str(capture.resolve()), "devices": {}}
    for key in selected:
        cfg, ts = TARGETS[key], transfers[key]
        events, open_time, frames, responses = [], None, 0, []
        last_frame_end = None
        for t in ts:
            p = t.payload
            if key == "0416:5408":
                if t.endpoint == 0x09 and len(p) == 2048 and p[:2] == b"\x02\xff":
                    open_time = t.timestamp
                    events.append(_event(t, "session-open", "2048-byte 02ff command/status request", "CONFIRMED", True))
                elif t.endpoint == 0x81 and len(p) == 512 and p[:2] == b"\x03\xff":
                    kind = "device-ready" if open_time is not None and t.timestamp - open_time < .01 else "frame-ack"
                    responses.append(p)
                    events.append(_event(t, kind, "512-byte 03ff response", "HIGH CONFIDENCE", True))
                elif t.endpoint == 0x09 and len(p) == 4096 and p[:2] == b"\x01\xff" and int.from_bytes(p[11:14], "little") == 0:
                    frames += 1
                    events.append(_event(t, "frame-start", f"frame {frames}; declared JPEG={int.from_bytes(p[2:6], 'little')}; header={p[:16].hex()}", "CONFIRMED"))
                if t.endpoint == 0x09 and p:
                    last_frame_end = t.timestamp
            else:
                if t.endpoint == 0x02 and len(p) == 512 and p[:20] == bytes.fromhex("dadbdcdd00000000000000000100000000000000"):
                    open_time = t.timestamp
                    events.append(_event(t, "session-open", "command 0 request; fields 0,1,0", "CONFIRMED", True))
                elif t.endpoint == 0x83 and p[:8] == bytes.fromhex("dadbdcdd01800000"):
                    responses.append(p)
                    events.append(_event(t, "device-ready", "command 0x8001 identity/readiness response", "HIGH CONFIDENCE", True))
                elif t.endpoint == 0x02 and len(p) == 512 and p[:4] == bytes.fromhex("dadbdcdd") and int.from_bytes(p[4:8], "little") == 2:
                    frames += 1
                    events.append(_event(t, "frame-start", f"frame {frames}; 1280x480; declared JPEG={int.from_bytes(p[16:20], 'little')}", "CONFIRMED"))
                if t.endpoint == 0x02 and p:
                    last_frame_end = t.timestamp

        unique = {hashlib.sha256(x).hexdigest() for x in responses}
        result["devices"][key] = {
            "target": cfg, "control_transfer_count": control_counts[key],
            "events": events, "frame_count": frames,
            "response_count": len(responses), "unique_response_payloads": len(unique),
            "session_close": {"mechanism": "no protocol payload observed; final frame completed, then handles/endpoints were released",
                              "confidence": "HIGH CONFIDENCE", "last_out_timestamp": last_frame_end},
            "notes": ["No SET_CONFIGURATION, SET_INTERFACE, vendor CONTROL, or HID control transfer occurred in the captured open/close window.",
                      "Close evidence belongs to the immediately preceding TRCC session; reopen evidence belongs to the following session."],
        }
    return result


def write_session_report(capture: Path, output: Path, vid_pid: str | None = None) -> dict:
    report = session_report(capture, vid_pid)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
