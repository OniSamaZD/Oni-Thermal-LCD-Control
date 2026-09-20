from __future__ import annotations

import struct
from dataclasses import dataclass

from .pcapng import Packet

TRANSFER_TYPES = {0: "isochronous", 1: "interrupt", 2: "control", 3: "bulk"}


@dataclass(frozen=True)
class UsbTransfer:
    packet: int
    timestamp: float
    captured_length: int
    header_length: int
    irp_id: int
    status: int
    function: int
    info: int
    bus: int
    device: int
    endpoint: int
    transfer_type: int
    declared_length: int
    payload: bytes

    @property
    def direction(self) -> str:
        return "IN" if self.endpoint & 0x80 else "OUT"

    @property
    def transfer_name(self) -> str:
        return TRANSFER_TYPES.get(self.transfer_type, f"unknown-{self.transfer_type}")


def decode(packet: Packet) -> UsbTransfer:
    if len(packet.raw) < 27:
        raise ValueError(f"packet {packet.number}: truncated USBPcap header")
    header_len, irp_id, status, function, info, bus, device, endpoint, transfer_type, data_len = struct.unpack_from(
        "<HQIHBHHBBI", packet.raw, 0
    )
    if header_len < 27 or header_len > len(packet.raw):
        raise ValueError(f"packet {packet.number}: invalid USBPcap header length {header_len}")
    return UsbTransfer(packet.number, packet.timestamp, packet.captured_length, header_len, irp_id, status, function, info,
                       bus, device, endpoint, transfer_type, data_len, packet.raw[header_len:])
