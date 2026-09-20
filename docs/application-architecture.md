# Oni Thermal LCD Control application architecture

## Current runtime flow

Each `DisplayCard` owns an independent `DisplaySession`, media source, bounded scheduler, profile, and metrics. GUI actions call `set_media`, `play`, `pause`, and `stop`; they contain no USB framing logic. Static media is composited and protocol-encoded once in the bounded `MediaPipeline` cache. Device persistence reuses that cached transaction. Animated/video sources lazily decode and publish only the latest frame, so falling behind causes drops rather than latency growth.

`PersistencePolicy5302` uses the measured vendor cadence of 85.497 ms / 11.696 FPS. Thermal Engine requests 30 FPS, but its blocking ~85 ms HID transaction determines the real rate. `PersistencePolicy5408` is separate at ~6 FPS and requires one exact ACK per frame. `PersistentReplayMachine` supplies the bounded, zero-retry proof path with monotonic deadlines and identity validation outside the hot frame loop. The daily-use `DisplaySession` waits directly for its next deadline instead of polling every 5 ms; if blocking I/O exceeds the interval it immediately sends only the newest frame, resets deadline debt, and never creates a catch-up burst.

The GUI has two independent cards, software previews (not readback), media-library references, per-display profile application, navigation, hardware-monitor templates, settings/diagnostics, TRCC conflict reporting, tray controls, and bounded rotating logs. Normal startup performs no endpoint writes; an exact device is opened only when Play is pressed on its card.

## Implemented offline layers

- `MediaPipeline`: renders Fit, Fill, Stretch, Crop, or Center at the device's exact transmitted resolution, encodes baseline 4:2:0 JPEG once for unchanged static media, converts it to the independently validated PID-specific protocol, and retains a bounded LRU cache.
- `PillowAnimationSource`: lazily decodes GIF and animated WebP, respects per-frame durations, loops without accumulating decoded frames, and holds only the current frame.
- `OpenCvVideoSource`: uses OpenCV's FFmpeg backend for MP4, WebM, MKV, MOV, AVI, and M4V, retains one decoded frame, and exposes source timestamps/FPS. Audio is intentionally ignored.
- `FrameScheduler`: applies source timing and optional FPS caps, drops stale frames rather than growing latency, and records decoded, delivered, dropped, and actual-FPS metrics.
- `DisplaySession` / `DisplayManager`: independent bounded workers for both displays. One worker's failure cannot stop or corrupt the other.
- `GeneratedFrameConnection`: capture-derived initialization/readiness plus real long-lived device transport. It validates every generated frame before writing, checks the exact PID 5408 ACK after every frame, rejects any PID 5302 post-frame response, performs no automatic retries, and closes/revalidates independently.
- `DeviceSupervisor`: independent discovery, disconnect, and reconnect lifecycle coordination. Its connect callback remains externally authorization-gated.
- `SettingsStore`: atomic JSON persistence for per-display media, fit mode, rotation, FPS, playing state, named profiles, and startup/tray preferences.

## GUI state

The existing dark two-card layout remains intact. Each card independently supports drag/drop and file selection, exact software preview, static images, GIF/animated WebP/video preview, Play/Pause, fit/rotation/FPS selection, actual preview FPS, dropped-frame count, and persisted per-display state. The preview is explicitly software-rendered and is not presented as hardware readback.

GUI Play routes the selected static or decoded animation/video frame through `MediaPipeline`, device-specific protocol encoding, and that card's real long-lived `GeneratedFrameConnection`. Pause/Stop/Clear act independently and close the corresponding session. The GUI accepts only the two reviewed public definitions, binds each to one unambiguous local instance using read-only discovery, and then validates identity, transport capabilities, readiness, and encoded frames before writing. Optional legacy exact-machine allowlists remain compatible. CLI captured-sequence replay remains disabled. Startup and media selection still open no device; Play performs fresh identity/conflict validation and fails closed.

## Evidence status

- **CONFIRMED offline:** independent queues, bounded static cache, bounded animation/video decode, frame dropping, GIF timing, FFmpeg-backed video decode, settings round-trip, reconnect lifecycle, and failure isolation.
- **CONFIRMED physical:** one capture-derived PID 5408 frame displayed successfully in the earlier controlled test.
- **PHYSICALLY CONFIRMED:** one bounded concurrent run sustained independent captured-frame streams for 29.992 seconds: PID 5302 accepted 344 frames at 11.469 FPS and PID 5408 accepted 180 frames at 6.001 FPS with 180/180 exact ACKs. Both handles closed cleanly, USBPcap recovered only the two approved captured JPEG hashes, and the user observed both panels continuously visible and simultaneously active for the full test.
- **GENERATED OUTPUT PHYSICALLY CONFIRMED:** the first bounded simultaneous generated-static run delivered 350 exact PID 5302 frames at 11.694 FPS and 180 exact PID 5408 frames at 6.001 FPS with 180/180 ACKs. USBPcap verified both new JPEG hashes byte-for-byte, both sessions closed cleanly with no retries or errors, and the user observed both generated images continuously and simultaneously for the full run.
- **NOT YET PHYSICALLY CONFIRMED:** GUI-driven arbitrary static media, GIF/animated-WebP output, video output, and stable maximum hardware FPS limits.

## Desktop product layers

The application shell exposes Home, Media Library, Profiles, Hardware Monitor, Performance, Settings, and Diagnostics without exposing protocol jargon in its normal workflow. Per-user startup uses the current user's Windows Run key and supports minimized/tray startup. Resource profiles change preview, sensor, diagnostics, and logging overhead; they never alter the two evidence-backed device persistence protocols. When hidden, preview-only animation is stopped and released, while a stream that is actively feeding a physical LCD continues without UI rendering.

The sensor engine is optional and read-only. HWiNFO, MSI Afterburner, RTSS, and AIDA64 mappings are opened with `FILE_MAP_READ`; provider absence or parser failure is contained and cannot stop media or the other display. The hardware-monitor renderer caches its static layer and supports text, sensor values, labels, images, bars, and graphs at either exact transmitted resolution.
