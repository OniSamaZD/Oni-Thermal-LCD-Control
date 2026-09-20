from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Packet:
    number: int
    timestamp: float
    captured_length: int
    raw: bytes


def packets(path: Path) -> Iterator[Packet]:
    """Read Enhanced Packet Blocks from a little-endian PCAPNG file."""
    data = path.read_bytes()
    off = 0
    endian = "<"
    resolutions: dict[int, float] = {}
    number = 0
    while off + 12 <= len(data):
        block_type = struct.unpack_from(endian + "I", data, off)[0]
        block_len = struct.unpack_from(endian + "I", data, off + 4)[0]
        if block_len < 12 or off + block_len > len(data):
            raise ValueError(f"invalid PCAPNG block at offset {off}")
        if block_type == 0x0A0D0D0A:
            magic = data[off + 8:off + 12]
            if magic == b"\x4d\x3c\x2b\x1a":
                endian = "<"
            elif magic == b"\x1a\x2b\x3c\x4d":
                endian = ">"
            else:
                raise ValueError("invalid PCAPNG byte-order magic")
        elif block_type == 1:
            interface_id = len(resolutions)
            resolution = 1e-6
            opt = off + 16
            end = off + block_len - 4
            while opt + 4 <= end:
                code, length = struct.unpack_from(endian + "HH", data, opt)
                if code == 0:
                    break
                value = data[opt + 4:opt + 4 + length]
                if code == 9 and value:
                    n = value[0]
                    resolution = (2.0 ** -(n & 0x7f)) if n & 0x80 else (10.0 ** -n)
                opt += 4 + ((length + 3) & ~3)
            resolutions[interface_id] = resolution
        elif block_type == 6:
            interface_id, high, low, cap_len, _ = struct.unpack_from(endian + "IIIII", data, off + 8)
            start = off + 28
            number += 1
            yield Packet(number, ((high << 32) | low) * resolutions.get(interface_id, 1e-6), cap_len, data[start:start + cap_len])
        off += block_len
