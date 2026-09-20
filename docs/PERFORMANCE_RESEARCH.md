# Performance research and adoption record

Date: 2026-08-29. This is an architectural comparison, not copied source code.

## Primary references and licenses

- Qt `QWidget` documentation: `update()` schedules a paint and permits Qt to coalesce repeated requests; `repaint()` paints immediately. Hidden widgets are not painted. `WA_OpaquePaintEvent` can avoid background erasure for opaque, rapidly updated surfaces. Source: https://doc.qt.io/qt-6.8/qwidget.html (Qt documentation; Qt documentation licensing applies).
- libjpeg-turbo documentation: SIMD-accelerated JPEG API/codec reference and official binary information. Source: https://libjpeg-turbo.org/Documentation/Documentation (BSD-style project licensing; no code imported).
- LibreHardwareMonitor: dynamically enumerated hardware and sensor model, explicitly usable library, MPL-2.0 with separately noted third-party components. Source: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor.
- InfoPanel: HWiNFO shared-memory sensor visualization, separate LCD render loop, caching and multi-element dashboards. Source: https://github.com/habibrehmansg/infopanel (GPL-3.0; examined for concepts only, no code copied or linked).
- SensorPanel: modular device profiles, dynamic sensors, native themes, bounded renderer choices, regional updates where a device protocol supports them, and an editable fixed-pixel canvas. Source: https://github.com/oae/sensorpanel (MIT; concepts only, no code copied).

## Findings applied

1. One owner controls the final-frame publication slot for each display. Media and monitor rendering are modes, not concurrent publishers. A monotonically increasing ownership generation rejects work prepared before a transition.
2. Sensor acquisition remains a shared, interval-cached service. Standalone hardware-monitor mode renders only on sensor ticks and the existing DisplaySession persists the resulting encoded frame. It does not render at transport cadence.
3. Media-with-sensor-overlay remains one media producer. A transparent telemetry layer is regenerated only on sensor ticks and composited into the media branch immediately before one JPEG encode. There is no second transport queue.
4. Hidden/tray Qt preview work remains suspended; no QImage/QPixmap is constructed when presentation is not due. Static bezel/product assets remain cached.
5. Regional/dirty-rectangle transport was rejected because neither confirmed Thermalright protocol proves such a command. No protocol behavior was inferred from other projects.

## Deliberately not adopted

- GPL InfoPanel code or implementation details: incompatible copying risk and no need for it.
- Browser/Chrome dashboard rendering: disproportionate process and memory overhead for this application.
- Undocumented partial-frame writes, JPEG table reuse, hardware brightness, or commit commands: unsupported by the capture evidence.
- Busy polling and deep frame queues: conflict with bounded latest-frame semantics and background CPU goals.

## Benchmark gate

`tools/jpeg_benchmark.py` measures OpenCV and Pillow at 1920x462 and 1280x480 with qualities 45/75/88/95. `analysis/jpeg-benchmark.json` records time, equivalent encoder FPS, byte size, library versions, and whether Pillow reports libjpeg-turbo. Encoder choice must be made from measured total preparation cost and protocol compatibility, not branding alone.
