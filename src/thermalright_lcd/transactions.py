from __future__ import annotations

import hashlib
import json
from base64 import b64encode
from dataclasses import asdict
from pathlib import Path

from .pcapng import packets
from .usbpcap import UsbTransfer, decode

MAGIC_5302 = bytes.fromhex("dadbdcdd")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _host_payloads(ts: list[UsbTransfer], device: int, endpoint: int) -> list[UsbTransfer]:
    return [t for t in ts if t.device == device and t.endpoint == endpoint and t.direction == "OUT" and t.payload]


def _blocks5408(chunks: list[UsbTransfer]):
    blocks = []
    for t in chunks:
        for sub in range(8):
            block = t.payload[sub*512:(sub+1)*512]
            if block[:2] != b"\x01\xff":
                continue
            h = block[:16]; length = int.from_bytes(h[6:8], "little")
            blocks.append((t, sub, h, block[16:16+length]))
    return blocks


def isolate(capture: Path) -> dict:
    ts = [decode(p) for p in packets(capture)]
    result = {"capture": str(capture.resolve()), "capture_sha256": _sha(capture.read_bytes()), "devices": {}}
    def context(device: int, start: float, end: float):
        return [{"packet": t.packet, "timestamp": t.timestamp, "endpoint": f"0x{t.endpoint:02x}",
                 "direction": t.direction, "transfer_type": t.transfer_name, "irp_id": f"0x{t.irp_id:016x}",
                 "urb_stage": "completion" if t.info else "submission", "status": t.status,
                 "declared_length": t.declared_length, "payload_size": len(t.payload)}
                for t in ts if t.device == device and start - 0.0005 <= t.timestamp <= end + 0.0005]

    out5408 = _host_payloads(ts, 5, 0x09)
    in5408 = [t for t in ts if t.device == 5 and t.endpoint == 0x81 and t.direction == "IN" and t.payload]
    starts = [i for i, t in enumerate(out5408) if len(t.payload) == 4096 and t.payload[:2] == b"\x01\xff" and int.from_bytes(t.payload[11:13], "little") == 0]
    tx5408 = []
    for frame_index, start in enumerate(starts):
        end = starts[frame_index + 1] if frame_index + 1 < len(starts) else len(out5408)
        chunks = out5408[start:end]
        blocks = _blocks5408(chunks)
        body = b"".join(x[3] for x in blocks)
        eoi = body.find(b"\xff\xd9")
        if not body.startswith(b"\xff\xd8") or eoi < 0:
            continue
        eoi += 2
        ack = next((x for x in in5408 if x.timestamp >= chunks[-1].timestamp and
                    (frame_index + 1 == len(starts) or x.timestamp < out5408[starts[frame_index + 1]].timestamp)), None)
        tx5408.append({
            "index": len(tx5408) + 1, "complete": True, "first_packet": chunks[0].packet,
            "last_out_packet": chunks[-1].packet, "start_timestamp": chunks[0].timestamp,
            "end_out_timestamp": chunks[-1].timestamp, "transfer_count": len(chunks),
            "usb_payload_bytes": sum(len(t.payload) for t in chunks), "protocol_chunk_count": len(blocks), "jpeg_bytes": eoi,
            "padding_bytes": sum(len(t.payload) for t in chunks) - sum(16 + len(x[3]) for x in blocks), "jpeg_sha256": _sha(body[:eoi]),
            "padding_nonzero_bytes": sum(x != 0 for x in body[eoi:]),
            "declared_jpeg_length": int.from_bytes(blocks[0][2][2:6], "little"),
            "declared_chunk_count": int.from_bytes(blocks[0][2][9:11], "little"),
            "chunk_indices": [int.from_bytes(x[2][11:13], "little") for x in blocks],
            "chunk_lengths": [int.from_bytes(x[2][6:8], "little") for x in blocks],
            "header_hex": chunks[0].payload[:16].hex(),
            "expected_response": None if ack is None else {"packet": ack.packet, "timestamp": ack.timestamp,
                "delay_after_last_out_ms": (ack.timestamp - chunks[-1].timestamp) * 1000,
                "payload_size": len(ack.payload), "payload_sha256": _sha(ack.payload), "payload_hex": ack.payload.hex()},
            "payload_packets": [{"packet": t.packet, "timestamp": t.timestamp, "sha256": _sha(t.payload),
                                  "payload_b64": b64encode(t.payload).decode()} for t in chunks],
            "context_packets": context(5, chunks[0].timestamp, ack.timestamp if ack else chunks[-1].timestamp)
        })

    out5302 = _host_payloads(ts, 6, 0x02)
    starts5302 = [i for i, t in enumerate(out5302) if t.payload.startswith(MAGIC_5302) and len(t.payload) == 512 and int.from_bytes(t.payload[4:8], "little") == 2]
    tx5302 = []
    for frame_index, start in enumerate(starts5302):
        first = out5302[start]
        h = first.payload[:20]
        jpeg_len = int.from_bytes(h[16:20], "little")
        boundary = starts5302[frame_index + 1] if frame_index + 1 < len(starts5302) else len(out5302)
        chunks = out5302[start:boundary]
        # EOF is also a valid transaction boundary.  Do not require a following
        # frame-start marker: the declared stream plus JPEG EOI can prove that
        # the final captured frame is complete on its own.
        stream = b"".join(t.payload for t in chunks)
        eoi = stream.find(b"\xff\xd9", 20)
        if not stream[20:22] == b"\xff\xd8" or eoi < 0:
            continue
        jpeg = stream[20:eoi + 2]
        tx5302.append({
            "index": len(tx5302) + 1, "complete": True, "first_packet": chunks[0].packet,
            "last_out_packet": chunks[-1].packet, "start_timestamp": chunks[0].timestamp,
            "end_out_timestamp": chunks[-1].timestamp, "transfer_count": len(chunks),
            "usb_payload_bytes": len(stream), "jpeg_bytes": len(jpeg), "padding_bytes": len(stream)-20-len(jpeg),
            "padding_nonzero_bytes": sum(x != 0 for x in stream[eoi + 2:]),
            "jpeg_sha256": _sha(jpeg), "header_hex": h.hex(),
            "header_fields": {"magic": h[:4].hex(), "command_le": int.from_bytes(h[4:8], "little"),
                              "width_le": int.from_bytes(h[8:10], "little"), "height_le": int.from_bytes(h[10:12], "little"),
                              "format_le": int.from_bytes(h[12:16], "little"), "jpeg_length_le": jpeg_len,
                              "jpeg_length_matches": jpeg_len == len(jpeg)},
            "expected_response": None,
            "payload_packets": [{"packet": t.packet, "timestamp": t.timestamp, "sha256": _sha(t.payload),
                                  "payload_b64": b64encode(t.payload).decode()} for t in chunks],
            "context_packets": context(6, chunks[0].timestamp, chunks[-1].timestamp)
        })

    correlated_ack_packets = {x["expected_response"]["packet"] for x in tx5408 if x["expected_response"]}
    frame_ack_responses = [x for x in in5408 if x.packet in correlated_ack_packets]
    non_frame_responses = [x for x in in5408 if x.packet not in correlated_ack_packets]
    result["devices"]["0416:5408"] = {"capture_device": 5, "interface": 0, "endpoint": "0x09",
        "transfer_type": "bulk", "transactions": tx5408,
        "response_summary": {"endpoint": "0x81", "count": len(in5408), "unique_payloads": len({_sha(x.payload) for x in in5408}),
                             "frame_ack_count": len(frame_ack_responses), "non_frame_response_count": len(non_frame_responses),
                             "unique_frame_ack_payloads": len({_sha(x.payload) for x in frame_ack_responses}),
                             "one_per_complete_frame": len(frame_ack_responses) == len(tx5408)}}
    result["devices"]["0416:5302"] = {"capture_device": 6, "interface": 1, "endpoint": "0x02",
        "transfer_type": "interrupt", "transactions": tx5302,
        "response_summary": {"endpoint": None, "count": 0, "one_per_complete_frame": False}}
    ack_delays = [x["expected_response"]["delay_after_last_out_ms"] for x in tx5408 if x["expected_response"]]
    result["analysis"] = {
        "0416:5408": {
            "complete_frames": len(tx5408),
            "chunk_index_rule_all": all(v == i for x in tx5408 for i, v in enumerate(x["chunk_indices"])),
            "declared_length_matches_all": all(x["declared_jpeg_length"] == x["jpeg_bytes"] for x in tx5408),
            "declared_chunk_count_matches_all": all(x["declared_chunk_count"] == x["protocol_chunk_count"] for x in tx5408),
            "full_chunk_lengths_496": all(all(v == 496 for v in x["chunk_lengths"][:-1]) for x in tx5408),
            "all_padding_zero": all(x["padding_nonzero_bytes"] == 0 for x in tx5408),
            "ack_payloads_unique": len({_sha(x.payload) for x in frame_ack_responses}),
            "non_frame_response_types": len({_sha(x.payload) for x in non_frame_responses}),
            "ack_delay_ms": {"min": min(ack_delays), "max": max(ack_delays), "mean": sum(ack_delays)/len(ack_delays)} if ack_delays else None,
            "header_correlation": "bytes 2-5 JPEG length; bytes 6-7 current payload length; byte 8 command 1; bytes 9-10 total chunk count uint16 LE; bytes 11-12 zero-based chunk index uint16 LE; bytes 13-15 zero"
        },
        "0416:5302": {
            "complete_frames": len(tx5302), "magic_all": all(x["header_fields"]["magic"] == MAGIC_5302.hex() for x in tx5302),
            "command_all_2": all(x["header_fields"]["command_le"] == 2 for x in tx5302),
            "dimensions_all_1280x480": all((x["header_fields"]["width_le"], x["header_fields"]["height_le"]) == (1280,480) for x in tx5302),
            "format_all_2": all(x["header_fields"]["format_le"] == 2 for x in tx5302),
            "jpeg_length_matches": sum(x["header_fields"]["jpeg_length_matches"] for x in tx5302),
            "jpeg_length_mismatches": sum(not x["header_fields"]["jpeg_length_matches"] for x in tx5302),
            "all_padding_zero": all(x["padding_nonzero_bytes"] == 0 for x in tx5302)
        }
    }
    return result


def write_transactions(capture: Path, output: Path) -> dict:
    report = isolate(capture)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

def write_selected_transaction(report_file:Path,output:Path,vid_pid:str,index:int)->dict:
    """Create a compact capture-derived report containing one exact transaction."""
    report=json.loads(report_file.read_text(encoding="utf-8"));device=report["devices"][vid_pid]
    tx=dict(next(x for x in device["transactions"] if x["index"]==index));tx["index"]=1
    compact={"capture":report.get("capture"),"capture_sha256":report.get("capture_sha256"),
             "source_kind":report.get("source_kind","captured"),"selected_original_index":index,
             "devices":{vid_pid:{**{k:v for k,v in device.items() if k!="transactions"},"transactions":[tx]}}}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(compact,indent=2),encoding="utf-8")
    return compact


def extract_jpeg(report_file: Path, vid_pid: str, index: int, output: Path) -> dict:
    from base64 import b64decode
    report=json.loads(report_file.read_text(encoding="utf-8")); tx=next(x for x in report["devices"][vid_pid]["transactions"] if x["index"]==index)
    payloads=[b64decode(x["payload_b64"]) for x in tx["payload_packets"]]
    if vid_pid=="0416:5408": jpeg=b"".join(x[3] for x in _blocks5408([
        UsbTransfer(0,0,len(p),0,0,0,0,0,0,0,0x09,3,len(p),p) for p in payloads]))
    else:
        stream=b"".join(payloads); eoi=stream.find(b"\xff\xd9",20)+2; jpeg=stream[20:eoi]
    jpeg=jpeg[:tx["jpeg_bytes"]]; output.parent.mkdir(parents=True,exist_ok=True); output.write_bytes(jpeg)
    return {"output":str(output.resolve()),"bytes":len(jpeg),"sha256":_sha(jpeg)}
