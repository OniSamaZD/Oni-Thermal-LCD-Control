# Custom sensor themes

Sensor themes are data-only layouts. A shareable theme uses the `.oni-theme`
extension and is a ZIP archive with this structure:

```text
theme.json
preview.png          # optional
assets/              # optional PNG, JPEG, WebP, or GIF files
fonts/               # optional TTF or OTF files
```

The current `theme.json` format is `oni-sensor-theme`, schema version `1`.
Executable files and code are not supported.

## Theme document

The root object contains `format`, `schema_version`, `id`, `name`, `canvas`,
`elements`, and optional `description`, `author`, `background_color`, and
`metadata`. A canvas has `width`, `height`, `preset`, and `scale_mode`.
Supported scale modes are `contain`, `cover`, and `stretch`. Presets are
available for USB displays `0416:5408` (1920x462) and `0416:5302` (1280x480);
`custom` accepts any validated canvas up to 8192x8192.

Every element has the common geometry/state fields `id`, `name`, `type`, `x`,
`y`, `width`, `height`, `rotation`, `opacity`, `visible`, `locked`, and
`z_index`. Elements can also use applicable background, border, corner,
shadow, and glow fields.

Supported element types are:

- `text`, `sensor_value`, `sensor_label`, `clock`, `date`
- `image`, `icon`
- `progress_bar`, `horizontal_bar`, `vertical_bar`
- `ring_gauge`, `arc_gauge`, `line_graph`

Text elements support family or packaged font, size, weight, italic,
horizontal/vertical alignment, letter spacing, and color. Sensor elements
support logical binding, unit, precision, prefix/suffix, min/max, warning and
critical thresholds, and unavailable text. Bars and gauges add track/value
colors, thickness, angles, and direction. Graphs add history duration, line
width, fill, smoothing, and automatic/manual scale. Images add asset path,
fit mode, crop rectangle, and the common opacity field.

Logical bindings are resolved through the application's existing sensor
subsystem. Missing or temporarily unavailable readings render the element's
`unavailable_text` rather than failing the frame.

## Storage and safety

Built-in themes are read from `assets/sensor-themes`. User themes are stored
separately under `%LOCALAPPDATA%\OniThermalLcd\sensor-themes`, so uninstalling
the application does not remove user-created layouts by default.

Imports validate schema versions, element properties, duplicate IDs, resource
references, archive traversal, duplicate/case-colliding members, expanded and
per-file size limits, compression ratios, allowed file types, and image pixel
dimensions. Archive members are copied as data; nothing in a theme is
executed.
