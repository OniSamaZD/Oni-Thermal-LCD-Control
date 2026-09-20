from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

from .pcapng import packets
from .usbpcap import UsbTransfer, decode

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(SOI):
        return None
    i = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while i + 3 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if i + 2 > len(data):
            return None
        length = int.from_bytes(data[i:i + 2], "big")
        if marker in sof and i + 7 <= len(data):
            return int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 3:i + 5], "big")
        if length < 2:
            return None
        i += length
    return None


def find_jpegs(stream: bytes) -> list[tuple[int, int]]:
    found, cursor = [], 0
    while True:
        start = stream.find(SOI, cursor)
        if start < 0:
            break
        end = stream.find(EOI, start + 2)
        if end < 0:
            break
        found.append((start, end + 2))
        cursor = end + 2
    return found


def analyze(capture: Path, out_dir: Path, target_device: int | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "extracted_frames"
    frames_dir.mkdir(exist_ok=True)
    all_transfers = [decode(p) for p in packets(capture)]
    transfers = [t for t in all_transfers if target_device is None or t.device == target_device]
    groups: dict[tuple[int, int, int], list[UsbTransfer]] = defaultdict(list)
    for t in transfers:
        groups[(t.bus, t.device, t.endpoint)].append(t)

    devices = {}
    for t in transfers:
        if t.endpoint == 0x80 and len(t.payload) >= 18 and t.payload[:2] == b"\x12\x01":
            devices[f"{t.bus}.{t.device}"] = {
                "bus": t.bus, "device": t.device,
                "vid": f"{int.from_bytes(t.payload[8:10], 'little'):04x}",
                "pid": f"{int.from_bytes(t.payload[10:12], 'little'):04x}",
                "bcd_device": f"{int.from_bytes(t.payload[12:14], 'little'):04x}",
            }

    endpoints = []
    for key, items in sorted(groups.items()):
        sizes = Counter(len(x.payload) for x in items)
        endpoints.append({"bus": key[0], "device": key[1], "endpoint": f"0x{key[2]:02x}",
                          "direction": items[0].direction, "transfer_type": items[0].transfer_name,
                          "packets": len(items), "payload_bytes": sum(map(lambda x: len(x.payload), items)),
                          "payload_sizes": dict(sorted(sizes.items()))})

    with (out_dir / "endpoints.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bus", "device", "endpoint", "direction", "transfer_type", "packets", "payload_bytes", "payload_sizes"])
        w.writeheader(); w.writerows({**x, "payload_sizes": json.dumps(x["payload_sizes"])} for x in endpoints)
    with (out_dir / "packet-sizes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["packet", "captured_size", "payload_size", "bus", "device", "endpoint", "direction", "transfer_type"])
        w.writerows([t.packet, t.captured_length, len(t.payload), t.bus, t.device, f"0x{t.endpoint:02x}", t.direction, t.transfer_name] for t in transfers)
    with (out_dir / "timeline.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["packet", "timestamp", "bus", "device", "endpoint", "direction", "transfer_type", "status", "declared_size", "payload_size"])
        w.writerows([t.packet, f"{t.timestamp:.6f}", t.bus, t.device, f"0x{t.endpoint:02x}", t.direction, t.transfer_name, t.status, t.declared_length, len(t.payload)] for t in transfers)

    frames = []
    for key, items in sorted(groups.items()):
        stream = b"".join(t.payload for t in items)
        stream_name = f"bus{key[0]}_device{key[1]}_endpoint{key[2]:02x}_{items[0].direction.lower()}"
        (out_dir / f"{stream_name}.bin").write_bytes(stream)
        (out_dir / f"{stream_name}.json").write_text(json.dumps({
            "bus": key[0], "device": key[1], "endpoint": f"0x{key[2]:02x}",
            "direction": items[0].direction, "transfer_type": items[0].transfer_name,
            "packets": [{"packet": t.packet, "timestamp": t.timestamp, "captured_size": t.captured_length,
                         "declared_size": t.declared_length, "payload_size": len(t.payload), "status": t.status}
                        for t in items]
        }, indent=2), encoding="utf-8")
        if items[0].direction != "OUT" or items[0].transfer_name not in ("bulk", "interrupt"):
            continue
        payload_items = [t for t in items if t.payload]
        framed512 = bool(payload_items and all(len(t.payload) == 4096 and t.payload[:2] == b"\x01\xff" for t in payload_items))
        header_size = 16 if framed512 else 0
        body_by_transfer = []
        if framed512:
            with (out_dir / f"{stream_name}_headers.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["packet", "subpacket", "header_hex", "jpeg_length_le", "chunk_payload_length_le", "type", "chunk_index_le24"])
                for t in payload_items:
                    body = bytearray()
                    for sub in range(8):
                        block = t.payload[sub*512:(sub+1)*512]
                        if block[:2] != b"\x01\xff":
                            continue
                        h = block[:16]; length = int.from_bytes(h[6:8], "little")
                        body += block[16:16+length]
                        w.writerow([t.packet, sub, h.hex(), int.from_bytes(h[2:6], "little"), length, h[10], int.from_bytes(h[11:14], "little")])
                    body_by_transfer.append(bytes(body))
            items = payload_items
            stream = b"".join(body_by_transfer)
            (out_dir / f"{stream_name}_body.bin").write_bytes(stream)
        offsets, pos = [], 0
        for n, t in enumerate(items):
            body_len = len(body_by_transfer[n]) if framed512 else len(t.payload)
            offsets.append((pos, pos + body_len, t)); pos += body_len
        for start, end in find_jpegs(stream):
            image = stream[start:end]
            dims = jpeg_dimensions(image)
            touched = [t for a, b, t in offsets if b > start and a < end]
            idx = len(frames) + 1
            name = f"frame_{idx:04d}.jpg"
            (frames_dir / name).write_bytes(image)
            first_off = max(a for a, b, t in offsets if a <= start < b)
            last_off = max(a for a, b, t in offsets if a < end <= b) if any(a < end <= b for a,b,t in offsets) else 0
            prefix = (touched[0].payload[:header_size] if framed512 else b"") + stream[first_off:start]
            suffix_end = next((b for a,b,t in offsets if a < end <= b), end)
            suffix = stream[end:suffix_end]
            meta = {"file": name, "bus": key[0], "device": key[1], "endpoint": f"0x{key[2]:02x}",
                    "stream_start": start, "stream_end_exclusive": end, "jpeg_size": len(image),
                    "width": dims[0] if dims else None, "height": dims[1] if dims else None,
                    "sha256": sha256(image), "first_packet": touched[0].packet, "last_packet": touched[-1].packet,
                    "start_timestamp": touched[0].timestamp, "end_timestamp": touched[-1].timestamp,
                    "transfer_count": len(touched), "per_transfer_header_size": header_size,
                    "prefix_hex": prefix.hex(), "suffix_hex": suffix.hex()}
            frames.append(meta)
            (frames_dir / f"frame_{idx:04d}_prefix.bin").write_bytes(prefix)
            (frames_dir / f"frame_{idx:04d}_suffix.bin").write_bytes(suffix)
    (out_dir / "frames.json").write_text(json.dumps(frames, indent=2), encoding="utf-8")
    with (out_dir / "frames.csv").open("w", newline="", encoding="utf-8") as f:
        fields = list(frames[0]) if frames else ["file"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(frames)
    validation = {"decoder": "JPEG marker parser", "valid": 0, "recoverable_truncated": 0, "failed": 0}
    try:
        from PIL import Image, ImageOps, ImageDraw, ImageFile
        thumbs = []
        for frame in frames:
            path = frames_dir / frame["file"]
            try:
                ImageFile.LOAD_TRUNCATED_IMAGES = False
                with Image.open(path) as im:
                    im.load()
                validation["valid"] += 1
                truncated = False
            except OSError:
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                try:
                    with Image.open(path) as im: im.load()
                    validation["recoverable_truncated"] += 1
                    truncated = True
                except OSError:
                    validation["failed"] += 1
                    continue
            with Image.open(path) as im:
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                thumb = ImageOps.contain(im.convert("RGB"), (320, 100))
                tile = Image.new("RGB", (340, 130), "#181818")
                tile.paste(thumb, ((340-thumb.width)//2, 5))
                label = frame["file"] + (" (recoverable/truncated)" if truncated else "")
                ImageDraw.Draw(tile).text((8, 110), label, fill="white")
                thumbs.append(tile)
        if thumbs:
            cols = 2; rows = (len(thumbs) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * 340, rows * 130), "#101010")
            for i, thumb in enumerate(thumbs): sheet.paste(thumb, ((i % cols)*340, (i // cols)*130))
            sheet.save(out_dir / "contact-sheet.jpg", quality=90)
        validation["decoder"] = f"Pillow {__import__('PIL').__version__}"
    except ImportError:
        pass
    summary = {"capture": str(capture.resolve()), "capture_sha256": sha256(capture.read_bytes()), "target_device": target_device,
               "packet_count": len(transfers), "duration_seconds": transfers[-1].timestamp - transfers[0].timestamp,
               "devices": devices, "endpoints": endpoints, "jpeg_count": len(frames), "image_validation": validation, "frames": frames}
    (out_dir / "capture-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Capture summary", "", f"- Capture SHA-256: `{summary['capture_sha256']}`", f"- Packets: {len(transfers)}",
             f"- Duration: {summary['duration_seconds']:.6f} s", f"- Reconstructed JPEGs: {len(frames)}", "", "## Endpoints", ""]
    lines += [f"- {x['bus']}.{x['device']}.{x['endpoint']} {x['direction']} {x['transfer_type']}: {x['packets']} packets, {x['payload_bytes']} payload bytes" for x in endpoints]
    lines += ["", "## Frames", ""] + [f"- {x['file']}: {x['width']}×{x['height']}, {x['jpeg_size']} bytes, packets {x['first_packet']}–{x['last_packet']}" for x in frames]
    (out_dir / "capture-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
