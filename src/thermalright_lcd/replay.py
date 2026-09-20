from __future__ import annotations

import json
from base64 import b64decode
from pathlib import Path


class SafetyError(ValueError):
    pass


def load_allowlist(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != 1 or not isinstance(data.get("devices"), list):
        raise SafetyError("invalid allowlist schema")
    return data


def dry_run(transaction_file: Path, allowlist_file: Path, vid_pid: str, transaction_index: int) -> dict:
    report = json.loads(transaction_file.read_text(encoding="utf-8"))
    allow = load_allowlist(allowlist_file)
    target = next((x for x in allow["devices"] if x["vid_pid"].lower() == vid_pid.lower()), None)
    if not target:
        raise SafetyError("target VID:PID is not allowlisted")
    captured = report["devices"].get(vid_pid.lower()) or report["devices"].get(vid_pid.upper())
    if not captured:
        raise SafetyError("transaction does not match requested VID:PID")
    for key in ("interface", "endpoint", "transfer_type"):
        if str(target[key]).lower() != str(captured[key]).lower():
            raise SafetyError(f"allowlist mismatch: {key}")
    tx = next((x for x in captured["transactions"] if x["index"] == transaction_index), None)
    if not tx or not tx.get("complete"):
        raise SafetyError("complete captured transaction not found")
    payloads = [b64decode(x["payload_b64"]) for x in tx["payload_packets"]]
    sizes=[len(p) for p in payloads]
    valid_sizes=(all(n==target["host_payload_size"] for n in sizes) if vid_pid.lower()!="0416:5408" else
                 all(n==4096 for n in sizes[:-1]) and bool(sizes) and sizes[-1] in (2048,4096))
    if not valid_sizes:
        raise SafetyError("payload size violates allowlist")
    return {"mode": "DRY-RUN", "usb_opened": False, "usb_written": False, "target": target,
            "transaction_index": transaction_index, "initialization_sequence": "not present in capture",
            "frame_transfer_count": len(payloads), "frame_byte_count": sum(map(len, payloads)),
            "termination_sequence": "implicit final padded transfer; no separate command observed",
            "expected_response": tx.get("expected_response"), "payload_sha256": [x["sha256"] for x in tx["payload_packets"]]}


def dry_run_session(session_file: Path, transaction_file: Path, allowlist_file: Path,
                    vid_pid: str, transaction_index: int = 1) -> dict:
    session = json.loads(session_file.read_text(encoding="utf-8"))
    allow = load_allowlist(allowlist_file)
    target = next((x for x in allow["devices"] if x["vid_pid"].lower() == vid_pid.lower()), None)
    lifecycle = session.get("devices", {}).get(vid_pid.lower())
    if not target or not lifecycle:
        raise SafetyError("session target is not allowlisted or absent")
    cfg = lifecycle.get("target", {})
    if cfg.get("interface") != target["interface"] or f"0x{cfg.get('out', -1):02x}" != target["endpoint"]:
        raise SafetyError("wrong interface or endpoint")
    opens = [x for x in lifecycle.get("events", []) if x.get("category") == "session-open"]
    ready = [x for x in lifecycle.get("events", []) if x.get("category") == "device-ready"]
    if len(opens) != 1 or len(ready) != 1 or opens[0]["timestamp"] >= ready[0]["timestamp"]:
        raise SafetyError("malformed session open/ready ordering")
    if opens[0]["endpoint"].lower() != target["open_request"]["endpoint"] or ready[0]["endpoint"].lower() != target["open_response"]["endpoint"]:
        raise SafetyError("wrong open/response endpoint")
    frame = dry_run(transaction_file, allowlist_file, vid_pid, transaction_index)
    return {
        "mode": "SESSION DRY-RUN", "usb_opened": False, "usb_written": False,
        "target": target, "transfer_count": 1 + frame["frame_transfer_count"],
        "byte_count": opens[0]["length"] + frame["frame_byte_count"],
        "initialization_sequence": [opens[0]], "expected_responses": [ready[0], frame["expected_response"]],
        "frame_data_sequence": {"transaction_index": transaction_index,
                                "transfer_count": frame["frame_transfer_count"],
                                "byte_count": frame["frame_byte_count"],
                                "payload_sha256": frame["payload_sha256"]},
        "termination_sequence": {"transfers": [], "action": "release interface/device handle",
                                 "evidence": lifecycle["session_close"]},
    }
