# ONI Sensor Studio design

ONI Sensor Studio is an embedded, exact-pixel LCD compositor. It keeps authoring separate from output: the editor mutates a validated `SensorTheme` document, the Pillow renderer produces frames, and the existing per-display `DisplaySession` remains the only owner of the physical transport.

## Product research

The design keeps the useful parts of established tools while removing their common setup friction:

- Turing Smart Screen themes demonstrate exact-positioned text, images, graphs, radial gauges and custom data, but advanced layouts are primarily YAML/code driven. <https://github.com/mathoudebine/turing-smart-screen-python/wiki/System-monitor-%3A-themes>
- AIDA64 SensorPanel Manager establishes the familiar background-plus-layer workflow with drag, resize, ordering, fonts, colors and import/export. <https://www.aida64.com/user-manual/sensorpanel/sensorpanel-manager>
- InfoPanel demonstrates a separate designer/runtime model and reusable panel definitions. <https://github.com/habibrehmansg/infopanel>
- ESPHomeDesigner demonstrates exact-canvas editing, plugin-style widgets and JSON round trips in an open-source editor. <https://github.com/koosoli/ESPHomeDesigner>

ONI combines those patterns with immediate sensor binding, strict schema validation, safe package resources, two native Thermalright canvas presets, and deployment through the application's existing bounded output pipeline.

## Workspace

- Top toolbar: document actions, background import/placement, target canvas, preview data source and deployment.
- Layers: ordering, visibility, locking, duplication, alignment and distribution.
- Sensors: searchable logical bindings grouped by CPU, GPU, memory, storage, network, cooling and game telemetry.
- Widgets: reusable text, value, label/value, image, clock/date, bars, gauges, graphs, FPS and frametime elements.
- Layouts: built-in and user layouts with preview thumbnails, rename and delete.
- Canvas: exact LCD coordinates, zoom-to-fit, grid, snapping, guides, drag, eight resize handles, rotation, keyboard nudging and multi-selection.
- Inspector: exact geometry plus conditional typography, appearance, sensor, gauge/bar, graph, image and animation properties.

The background is a dedicated bottom plane rather than a normal selectable widget. It can be placed using cover, contain, stretch, center or native sizing and is locked by default.

## Runtime contract

The editor never imports device or session code. Apply hands an immutable validated snapshot to the main-window runtime. The runtime uses the shared sensor service, one bounded scheduler per active display state, bounded graph history, the existing frame preparation path, and the existing `DisplaySession`. Editor sample data is never sent to hardware.

Navigation is preflighted before changing the page stack. Save, Discard and Cancel therefore cannot trigger re-entrant `QStackedWidget` changes. Canvas edits invalidate only the canvas preview; layout-library thumbnails are refreshed only when the library itself changes.

## Performance rules

- One shared editor preview invalidation timer; no per-widget timers.
- Runtime FPS is capped to the supported presets.
- Static layouts are not regenerated until their content is due to change.
- Graph samples and decoded media queues remain bounded.
- Hidden or inactive layouts do not render.
- Thumbnail generation never runs in the canvas/property edit path.

