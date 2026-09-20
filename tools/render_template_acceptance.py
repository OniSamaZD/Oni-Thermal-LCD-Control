from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from thermalright_lcd.hardware_monitor import MonitorRenderer, templates
from thermalright_lcd.sensors import (
    Aida64Provider, AfterburnerProvider, CachedSensorService, HwinfoProvider,
    NativeBasicProvider, RtssProvider, resolve_semantic_sensor,
)


ROLES = {
    "cpu.usage": "cpu_usage", "cpu.temperature": "cpu_temp",
    "cpu.clock": "cpu_clock", "cpu.power": "cpu_power",
    "gpu.usage": "gpu_usage", "gpu.temperature": "gpu_temp",
    "gpu.hotspot": "gpu_hotspot", "gpu.clock": "gpu_clock",
    "gpu.memory_clock": "gpu_memory_clock", "gpu.power": "gpu_power",
    "gpu.memory_used": "vram_usage", "memory.usage": "ram_usage",
    "storage.temperature": "ssd_temp", "network.download": "network_download",
    "network.upload": "network_upload", "game.fps": "fps",
    "game.frametime": "frametime", "fan.rpm": "fan_rpm", "pump.rpm": "pump_rpm",
}


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "analysis" / "template-visual-acceptance"
    out.mkdir(parents=True, exist_ok=True)
    service = CachedSensorService((HwinfoProvider(), AfterburnerProvider(), RtssProvider(), Aida64Provider(), NativeBasicProvider()))
    snapshot = service.poll(force=True)
    values = {value.definition.qualified_id: value.value for value in snapshot.values}
    mapping = {}
    for semantic, alias in ROLES.items():
        resolved = resolve_semantic_sensor(alias, snapshot.values)
        values[semantic] = resolved.value if resolved else None
        mapping[semantic] = resolved.definition.qualified_id if resolved else None
    cases = (
        ("0416:5408", "Gaming Dashboard"),
        ("0416:5302", "Gaming Dashboard"),
        ("0416:5408", "Clean Dark"),
        ("0416:5408", "Full System Overview"),
        ("0416:5302", "Benchmark Mode"),
    )
    rendered = []
    for target, name in cases:
        layout = templates(target)[name]
        path = out / f"{target.replace(':', '-')}-{name.lower().replace(' ', '-')}.png"
        image = MonitorRenderer(layout).render(values)
        image.save(path, optimize=True)
        rendered.append({"target": target, "template": name, "path": str(path), "size": image.size, "elements": len(layout.elements)})
        image.close()
    report = {"schema": 1, "live_sensor_count": len(snapshot.values), "providers": [asdict(x) for x in snapshot.provider_status], "semantic_mapping": mapping, "renders": rendered}
    (root / "analysis" / "template-visual-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
