from __future__ import annotations

import json
import struct
import time
from typing import Any, Callable, Iterable, Mapping
import xml.etree.ElementTree as ET

from .models import SensorDefinition, SensorValue
from .provider import SensorProvider
from .shared_memory import ReadOnlyNamedMemoryReader, SnapshotReader


Record = Mapping[str, Any]


class _MemoryProvider(SensorProvider):
    mapping_name = ""
    mapping_size = 1024 * 1024

    def __init__(
        self, reader: SnapshotReader | None = None,
        decoder: Callable[[Any], Iterable[Record]] | None = None,
    ) -> None:
        super().__init__()
        self.reader = reader or ReadOnlyNamedMemoryReader(self.mapping_name, self.mapping_size)
        self.decoder = decoder or self.decode_snapshot

    def _read_values(self) -> tuple[SensorValue, ...]:
        timestamp = time.time()
        records = self.decoder(self.reader.read())
        return tuple(_record_value(self.name, record, timestamp) for record in records)

    def decode_snapshot(self, snapshot: Any) -> Iterable[Record]:
        return _structured_records(snapshot)


class HwinfoProvider(_MemoryProvider):
    """HWiNFO Shared Memory Viewer v2 consumer (read-only)."""

    name = "HWiNFO"
    mapping_name = r"Global\HWiNFO_SENS_SM2"
    mapping_size = 4 * 1024 * 1024

    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.version="unknown";self.mapped_sensor_count=0;self.mapped_reading_count=0

    def decode_snapshot(self, snapshot: Any) -> Iterable[Record]:
        if not isinstance(snapshot, (bytes, bytearray, memoryview)):
            return _structured_records(snapshot)
        data = bytes(snapshot)
        if len(data) < 44 or data[:4] != b"HWiS":
            return _structured_records(data)
        version,revision=struct.unpack_from("<II",data,4);self.version=f"{version}.{revision}"
        # Public HWiNFO_SENSORS_SHARED_MEM2 header. Element sizes/offsets come
        # from the mapping itself so newer revisions can add tail fields safely.
        sensor_off, sensor_size, sensor_count = struct.unpack_from("<III", data, 20)
        reading_off, reading_size, reading_count = struct.unpack_from("<III", data, 32)
        self.mapped_sensor_count=sensor_count;self.mapped_reading_count=reading_count
        if sensor_size < 264 or reading_size < 300:
            raise ValueError("unsupported HWiNFO element layout")
        _bounds(data, sensor_off, sensor_size, sensor_count)
        _bounds(data, reading_off, reading_size, reading_count)
        sensors: dict[int, str] = {}
        for index in range(sensor_count):
            base = sensor_off + index * sensor_size
            original = _cstring(data[base + 8:base + 136])
            user = _cstring(data[base + 136:base + 264])
            sensors[index] = user or original
        records = []
        for index in range(reading_count):
            base = reading_off + index * reading_size
            reading_type, sensor_index, reading_id = struct.unpack_from("<III", data, base)
            original = _cstring(data[base + 12:base + 140])
            user = _cstring(data[base + 140:base + 268])
            unit = _cstring(data[base + 268:base + 284])
            value = struct.unpack_from("<d", data, base + 284)[0]
            sensor_name = sensors.get(sensor_index, "")
            name = user or original or f"Reading {reading_id}"
            records.append({
                "id": f"{sensor_index}:{reading_id}", "name": name,
                "category": sensor_name or _category(name, unit), "unit": unit,
                "value": value, "canonical_key": _canonical(name, unit),
                "type": reading_type,
            })
        return records


class AfterburnerProvider(_MemoryProvider):
    """MSI Afterburner Hardware Monitoring shared-memory consumer.

    Binary layouts are versioned by Afterburner. A decoder can be injected for
    a newly documented revision; decoded records and fixture maps require no
    Afterburner dependency.
    """

    name = "MSI Afterburner"
    mapping_name = "MAHMSharedMemory"
    mapping_size = 1024 * 1024

    def decode_snapshot(self, snapshot: Any) -> Iterable[Record]:
        if not isinstance(snapshot, (bytes, bytearray, memoryview)):
            return _structured_records(snapshot)
        data = bytes(snapshot)
        if data[:4] != b"MAHM" or len(data) < 32:
            return _structured_records(data)
        _signature, version, header_size, count, entry_size = struct.unpack_from("<IIIII", data, 0)
        if not (32 <= header_size <= len(data)) or entry_size < 100:
            raise ValueError(f"unsupported MAHM layout version {version:#x}")
        _bounds(data, header_size, entry_size, count)
        records = []
        for index in range(count):
            entry = data[header_size + index * entry_size:header_size + (index + 1) * entry_size]
            # Stable leading fields in the public MAHM entry ABI.
            name = _cstring(entry[0:32])
            unit = _cstring(entry[32:48])
            if not name:
                continue
            # Public v2 entries keep current/min/max float values after the
            # localized strings and recommended-format field (offset 112).
            value_offset = 112
            if entry_size < value_offset + 4:
                raise ValueError("truncated MAHM entry")
            value = struct.unpack_from("<f", entry, value_offset)[0]
            records.append({"id": name, "name": name, "unit": unit, "value": value,
                            "category": _category(name, unit), "canonical_key": _canonical(name, unit)})
        return records


class RtssProvider(_MemoryProvider):
    """RTSS shared-memory statistics provider.

    RTSS changes application-entry layouts across ABI revisions; the versioned
    mapping is validated and an injectable decoder is supported. Structured
    snapshots expose FPS/frametime/1% low without process hooks or injection.
    """

    name = "RTSS"
    mapping_name = "RTSSSharedMemoryV2"
    mapping_size = 2 * 1024 * 1024

    def decode_snapshot(self, snapshot: Any) -> Iterable[Record]:
        if not isinstance(snapshot, (bytes, bytearray, memoryview)):
            return _structured_records(snapshot)
        data = bytes(snapshot)
        if data[:4] != b"RTSS":
            return _structured_records(data)
        if len(data) < 20:
            raise ValueError("truncated RTSS header")
        version, entry_size, app_offset, app_count = struct.unpack_from("<IIII", data, 4)
        # These leading header/entry fields are stable in the public RTSS v2
        # shared-memory ABI. Unknown shorter revisions fail closed.
        if entry_size < 284:
            raise ValueError(f"unsupported RTSS ABI version {version:#x}")
        _bounds(data, app_offset, entry_size, app_count)
        records = []
        for index in range(app_count):
            base = app_offset + index * entry_size
            process_id = struct.unpack_from("<I", data, base)[0]
            if not process_id:
                continue
            app_name = _cstring(data[base + 4:base + 264]) or f"PID {process_id}"
            time0, time1, frames, frame_time_us = struct.unpack_from("<IIII", data, base + 268)
            prefix = f"{process_id}"
            if time1 > time0 and frames:
                fps = frames * 1000.0 / (time1 - time0)
                records.append({"id": f"{prefix}.fps", "name": f"{app_name} FPS", "category": "Framerate",
                                "unit": "FPS", "value": fps, "canonical_key": "game.fps"})
            if frame_time_us:
                records.append({"id": f"{prefix}.frametime", "name": f"{app_name} Frametime",
                                "category": "Framerate", "unit": "ms", "value": frame_time_us / 1000.0,
                                "canonical_key": "game.frametime"})
        return records


class Aida64Provider(_MemoryProvider):
    """AIDA64 External Applications shared-memory XML consumer."""

    name = "AIDA64"
    mapping_name = "AIDA64_SensorValues"
    mapping_size = 1024 * 1024

    def decode_snapshot(self, snapshot: Any) -> Iterable[Record]:
        if not isinstance(snapshot, (bytes, bytearray, memoryview, str)):
            return _structured_records(snapshot)
        if isinstance(snapshot, str):
            text = snapshot
        else:
            text = bytes(snapshot).split(b"\0", 1)[0].decode("utf-8", "replace")
        text = text.strip()
        if text.startswith("{") or text.startswith("["):
            return _structured_records(text)
        if not text:
            return ()
        root = ET.fromstring(text)
        records = []
        for index, node in enumerate(root.iter()):
            if node is root or list(node):
                continue
            attributes = {key.lower(): value for key, value in node.attrib.items()}
            sensor_id = attributes.get("id") or attributes.get("key") or f"{node.tag}:{index}"
            name = attributes.get("label") or attributes.get("name") or attributes.get("description") or sensor_id
            unit = attributes.get("unit", "")
            raw = attributes.get("value", (node.text or "").strip())
            value = _number_or_text(raw)
            records.append({"id": sensor_id, "name": name, "category": _category(name, unit),
                            "unit": unit, "value": value, "canonical_key": _canonical(name, unit)})
        return records


class NativeBasicProvider(SensorProvider):
    """Safe basic Windows/process fallback, lazily importing psutil."""

    name = "Windows Basic"

    def __init__(self, psutil_module: Any | None = None) -> None:
        super().__init__()
        self._psutil = psutil_module

    def _read_values(self) -> tuple[SensorValue, ...]:
        psutil = self._psutil
        if psutil is None:
            try:
                import psutil as psutil_module
            except ImportError as exc:
                raise FileNotFoundError("psutil is not installed") from exc
            psutil = psutil_module
        now = time.time()
        cpu = SensorDefinition("cpu.total", self.name, "CPU Usage", "CPU", "%", "cpu.usage")
        memory = SensorDefinition("memory.used", self.name, "Memory Usage", "Memory", "%", "memory.usage")
        return (
            SensorValue(cpu, float(psutil.cpu_percent(interval=None)), now),
            SensorValue(memory, float(psutil.virtual_memory().percent), now),
        )


# Friendly spellings retained as aliases so UI/config code need not encode the
# internal Python capitalization choice.
HWiNFOProvider = HwinfoProvider
MsiAfterburnerProvider = AfterburnerProvider


def _record_value(provider: str, record: Record, timestamp: float) -> SensorValue:
    sensor_id = str(record.get("id") or record.get("name") or "").strip()
    name = str(record.get("name") or sensor_id).strip()
    if not sensor_id or not name:
        raise ValueError("sensor record lacks id/name")
    unit = str(record.get("unit", ""))
    definition = SensorDefinition(
        sensor_id, provider, name, str(record.get("category") or _category(name, unit)), unit,
        str(record.get("canonical_key", "")), str(record.get("description", "")),
    )
    return SensorValue(definition, record.get("value"), float(record.get("timestamp", timestamp)),
                       bool(record.get("valid", True)), str(record.get("error", "")))


def _structured_records(snapshot: Any) -> Iterable[Record]:
    if isinstance(snapshot, (bytes, bytearray, memoryview)):
        text = bytes(snapshot).split(b"\0", 1)[0].decode("utf-8", "strict").strip()
        snapshot = json.loads(text)
    elif isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    if isinstance(snapshot, Mapping):
        snapshot = snapshot.get("sensors", snapshot.get("values", [snapshot]))
    if not isinstance(snapshot, (list, tuple)):
        raise ValueError("snapshot is not a sensor-record sequence")
    if not all(isinstance(record, Mapping) for record in snapshot):
        raise ValueError("snapshot contains a non-record entry")
    return snapshot


def _bounds(data: bytes, offset: int, size: int, count: int) -> None:
    if offset < 0 or size <= 0 or count < 0 or offset + size * count > len(data):
        raise ValueError("shared-memory table exceeds snapshot bounds")


def _cstring(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _number_or_text(value: str) -> float | str:
    cleaned = value.strip().replace(",", ".")
    try: return float(cleaned)
    except ValueError: return value.strip()


def _category(name: str, unit: str) -> str:
    lowered = name.lower()
    if "gpu" in lowered: return "GPU"
    if "cpu" in lowered or "core" in lowered: return "CPU"
    if "memory" in lowered or "ram" in lowered: return "Memory"
    if "fan" in lowered or unit.lower() == "rpm": return "Fan"
    if "network" in lowered or "download" in lowered or "upload" in lowered: return "Network"
    if "drive" in lowered or "ssd" in lowered or "hdd" in lowered: return "Storage"
    if "fps" in lowered or "frame" in lowered: return "Framerate"
    return "Other"


def _canonical(name: str, unit: str) -> str:
    lowered = "".join(char.lower() for char in name if char.isalnum())
    aliases = (
        (("cpuusage", "totalcpuusage"), "cpu.usage"),
        (("gpuusage", "gpu1usage"), "gpu.usage"),
        (("gputemperature", "gputemp"), "gpu.temperature"),
        (("cpupackagetemperature", "cputemperature", "cputemp"), "cpu.temperature"),
        (("framerate", "fps"), "game.fps"),
        (("frametime",), "game.frametime"),
        (("memoryusage", "ramusage"), "memory.usage"),
    )
    for names, canonical in aliases:
        if lowered in names: return canonical
    return f"{lowered}.{''.join(c.lower() for c in unit if c.isalnum())}"
