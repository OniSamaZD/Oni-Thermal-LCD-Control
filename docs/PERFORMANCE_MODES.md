# Performance mode policy

Performance modes never alter USB/HID framing, endpoints, ACK validation, physical resolution, selected LCD output FPS, or media timeline speed.

| Mode | Foreground preview cap | Hidden/tray preview | Sensor interval | Diagnostics interval | Intent |
|---|---:|---|---:|---:|---|
| Normal | 20 FPS | Suspended | 500 ms | 500 ms | Balanced desktop responsiveness |
| High FPS | 20 FPS | Suspended | 250 ms | 250 ms | Faster UI and sensor feedback; physical transport remains independently selected |
| Gaming | 15 FPS | Suspended | 1000 ms | 2000 ms | Reduce GUI interference while preserving physical output |
| Low Resource | 15 FPS | Suspended | 1000 ms | 1500 ms | Reduce nonessential GUI refresh |
| Ultra Low Resource | 15 FPS | Suspended | 1000 ms | 2000 ms | Static-first UI behavior and minimum background wakeups |

All modes retain bounded latest-frame queues, one shared in-process PyAV decoder for synchronized same-media playback, and zero persistent decoder child processes.
