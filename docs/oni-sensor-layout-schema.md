# ONI Sensor Layout JSON v1

The canonical ONI layout document is UTF-8 JSON with `format: "oni-sensor-theme"` and `schema_version: 1`. The existing name is retained for compatibility with published themes; Sensor Studio treats it as the ONI Sensor Layout v1 schema.

Coordinates and dimensions are native LCD pixels. A valid document can therefore place a widget exactly on either reviewed canvas without Python changes.

```json
{
  "format": "oni-sensor-theme",
  "schema_version": 1,
  "id": "ai-layout-example",
  "name": "AI Layout Example",
  "canvas": {
    "width": 1280,
    "height": 480,
    "preset": "0416:5302",
    "scale_mode": "contain"
  },
  "background_color": "#050A12",
  "background_asset": "assets/background.png",
  "background_fit": "cover",
  "background_opacity": 1.0,
  "background_locked": true,
  "elements": [
    {
      "id": "gpu-temperature",
      "name": "GPU Temperature",
      "type": "sensor_label_value",
      "x": 105,
      "y": 82,
      "width": 321,
      "height": 77,
      "sensor_binding": "gpu.temperature",
      "font_family": "Segoe UI",
      "font_size": 32,
      "text_color": "#6FE7FF",
      "unit": "°C",
      "decimal_precision": 0,
      "animation": "none",
      "animation_duration": 1.0
    }
  ]
}
```

Omitted element fields use validated defaults. Supported canvas presets are `0416:5408` (1920×462), `0416:5302` (1280×480), and `custom`. Resources must be relative members under `assets/` or `fonts/`; absolute paths and traversal are rejected. Imported JSON is limited to 2 MiB, element counts and canvas edges are bounded, unknown fields/types are rejected, and no code or expressions are executed.

Use `.oni-theme` for a portable package containing the JSON and resources. Plain JSON export copies referenced assets/fonts beside the JSON so `assets/...` and `fonts/...` remain resolvable.
