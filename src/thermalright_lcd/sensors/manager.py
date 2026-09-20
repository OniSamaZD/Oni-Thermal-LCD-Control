from __future__ import annotations

from dataclasses import dataclass
import time
import re
from collections import deque
from typing import Iterable

from .models import SensorValue
from .provider import ProviderStatus, SensorProvider


@dataclass(frozen=True, slots=True)
class SensorSnapshot:
    timestamp: float
    values: tuple[SensorValue, ...]
    provider_status: tuple[ProviderStatus, ...]

    def by_id(self) -> dict[str, SensorValue]:
        return {value.definition.qualified_id: value for value in self.values}


class SensorManager:
    """Poll providers independently and merge values by configured priority."""

    def __init__(
        self, providers: Iterable[SensorProvider], *,
        priority: Iterable[str] = ("HWiNFO", "MSI Afterburner", "RTSS", "AIDA64", "Windows Basic"),
        include_duplicates: bool = False,
    ) -> None:
        self.providers = tuple(providers)
        self.priority = tuple(priority)
        self.include_duplicates = include_duplicates
        self._selected: set[str] = set()

    def select(self, qualified_ids: Iterable[str]) -> None:
        self._selected = set(qualified_ids)

    def poll(self) -> SensorSnapshot:
        rank = {name: index for index, name in enumerate(self.priority)}
        collected: list[SensorValue] = []
        for provider in self.providers:
            collected.extend(provider.poll())
        collected.sort(key=lambda item: (rank.get(item.provider, len(rank)), item.definition.qualified_id))

        output: list[SensorValue] = []
        seen: set[str] = set()
        for value in collected:
            if not value.valid:
                continue
            qid = value.definition.qualified_id
            if self._selected and qid not in self._selected:
                continue
            key = value.definition.dedup_key
            if not self.include_duplicates and key in seen:
                continue
            seen.add(key)
            output.append(value)
        return SensorSnapshot(time.time(), tuple(output), tuple(p.status for p in self.providers))


class CachedSensorService:
    """Persistent provider owner with a bounded age-aware snapshot cache."""
    def __init__(self, providers: Iterable[SensorProvider], *, minimum_interval: float = 0.5,
                 include_duplicates: bool = True) -> None:
        self.manager = SensorManager(providers, include_duplicates=include_duplicates)
        self.minimum_interval = max(0.1, float(minimum_interval));self.snapshot = None
        self.last_poll_monotonic = float("-inf");self.poll_count = 0;self.poll_durations_ms=deque(maxlen=512);self.generation=0;self.last_success_timestamp=0.0
    def poll(self, *, force: bool = False) -> SensorSnapshot:
        now=time.perf_counter()
        if not force and self.snapshot is not None and now-self.last_poll_monotonic<self.minimum_interval:return self.snapshot
        started=time.perf_counter();self.snapshot=self.manager.poll();self.poll_durations_ms.append((time.perf_counter()-started)*1000);self.last_poll_monotonic=now;self.poll_count+=1;self.generation+=1
        if any(status.available for status in self.snapshot.provider_status):self.last_success_timestamp=self.snapshot.timestamp
        return self.snapshot
    def rescan(self)->SensorSnapshot:
        self.snapshot=None;self.last_poll_monotonic=float("-inf");return self.poll(force=True)
    def diagnostics(self)->dict:
        snapshot=self.snapshot;statuses=() if snapshot is None else snapshot.provider_status
        by_name={provider.name:provider for provider in self.manager.providers}
        return {"generation":self.generation,"poll_count":self.poll_count,"last_success_timestamp":self.last_success_timestamp,"last_poll_ms":self.poll_durations_ms[-1] if self.poll_durations_ms else 0.0,"mapped_sensor_count":len(snapshot.values) if snapshot else 0,"providers":[{"name":x.name,"available":x.available,"version":getattr(by_name.get(x.name),"version","unknown"),"mapped_sensors":getattr(by_name.get(x.name),"mapped_sensor_count",None),"mapped_readings":getattr(by_name.get(x.name),"mapped_reading_count",x.values_read),"values_read":x.values_read,"latency_ms":x.latency_ms,"last_error":x.last_error} for x in statuses]}


SEMANTIC_ALIASES = {
    "fps": ("fps", "framerate", "framespersecond"), "fps_1low": ("1%low", "1percentlow", "fps1low"),
    "cpu_usage": ("cpuusage", "totalcpuusage"), "cpu_temp": ("cputctltdie", "cpudieaverage", "cpuccdtemperature", "cputemperature"),
    "gpu_usage": ("gpuusage", "gpuutilization"), "gpu_temp": ("gputemperature", "gputemp"),
    "gpu_power": ("gpupower", "totalboardpower", "boardpower"),
    "vram_used": ("vramused", "gpumemoryused"), "vram_total": ("vramtotal", "gpumemorytotal"),
    "network_download": ("networkdownload", "downloadrate", "receivedbytes"),
    "network_upload": ("networkupload", "uploadrate", "sentbytes"),
    "cpu_clock": ("averageeffectiveclock", "coreeffectiveclock", "cpuclock", "coreclock"), "cpu_power": ("cpupackagepower", "cputotalpower", "cpuppt"),
    "gpu_hotspot": ("gpuhotspottemperature", "gpuhotspot"), "gpu_clock": ("gpuclock", "gpucoreclock"),
    "gpu_memory_clock": ("gpumemoryclock", "videomemoryclock"), "vram_usage": ("gpumemoryusage", "vramusage"),
    "ram_usage": ("physicalmemoryload", "memoryusage", "ramusage"), "ssd_temp": ("drivetemperature", "ssdtemperature"),
    "frametime": ("frametime", "frametimeaverage"), "fan_rpm": ("fanrpm", "cpufan", "gpufan"),
    "pump_rpm": ("pumpspeed", "pumprpm", "pumpsys"),
}


def rank_semantic_sensors(alias: str, values: Iterable[SensorValue]) -> list[SensorValue]:
    """Rank live values for a curated alias while keeping every raw sensor available."""
    clean=lambda text:re.sub(r"[^a-z0-9%]+","",text.casefold());needles=tuple(clean(x) for x in SEMANTIC_ALIASES.get(alias,(alias,)))
    provider_rank={name:i for i,name in enumerate(("HWiNFO","MSI Afterburner","RTSS","AIDA64","Windows Basic"))}
    expected_units={"cpu_temp":"c","gpu_temp":"c","gpu_hotspot":"c","ssd_temp":"c","cpu_power":"w","gpu_power":"w","fan_rpm":"rpm","pump_rpm":"rpm","fps":"fps","frametime":"ms"}
    exclusions={"fps":("low","high"),"cpu_temp":("power","current"),"fan_rpm":("%",),"pump_rpm":("%",)}
    def score(value):
        canonical=clean(value.definition.canonical_key);hay=clean(" ".join((value.name,value.category,value.definition.canonical_key,value.id)))
        unit=clean(value.unit);bad=any(clean(x) in hay or clean(x)==unit for x in exclusions.get(alias,()))
        unit_bad=bool(alias in expected_units and expected_units[alias] not in unit)
        return (bad,unit_bad,0 if any(n==hay or n==canonical for n in needles) else 1,0 if any(n and n in hay for n in needles) else 1,provider_rank.get(value.provider,99),value.name.casefold())
    return sorted(values,key=score)


def resolve_semantic_sensor(alias: str, values: Iterable[SensorValue]) -> SensorValue | None:
    ranked=rank_semantic_sensors(alias,values)
    if not ranked:return None
    clean=lambda text:re.sub(r"[^a-z0-9%]+","",text.casefold());candidate=ranked[0]
    hay=clean(" ".join((candidate.name,candidate.category,candidate.definition.canonical_key,candidate.id)))
    return candidate if any(clean(term) in hay for term in SEMANTIC_ALIASES.get(alias,(alias,))) else None


class SemanticResolverCache:
    """Cache semantic ranking until the provider's sensor definitions change."""
    def __init__(self):self.definition_key=None;self.qualified_ids={};self.rebuilds=0
    def resolve(self,roles:dict[str,str],values:Iterable[SensorValue])->dict[str,SensorValue|None]:
        values=tuple(values);by_id={value.definition.qualified_id:value for value in values};key=tuple(sorted(by_id))
        if key!=self.definition_key:
            self.definition_key=key;self.qualified_ids={name:(match.definition.qualified_id if (match:=resolve_semantic_sensor(alias,values)) else None) for name,alias in roles.items()};self.rebuilds+=1
        return {name:by_id.get(qid) if qid else None for name,qid in self.qualified_ids.items()}
