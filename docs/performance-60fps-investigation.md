# Maximum safe performance / 60 FPS investigation

Date: 2026-08-27. All measurements below are offline and recorded **zero USB/HID writes**.

## Conclusions

- The transform/JPEG/protocol-preparation pipeline exceeds 60 FPS for both targets, separately and concurrently.
- Physical 60 FPS is **unproven** for PID 5408 and PID 5302. Existing protocol-safe persistence rates remain 6 FPS (5408, ACK-driven) and 11.696249 FPS (5302). They were not loosened from offline evidence.
- PID 5408's existing capture has roughly 156.125 ms frame cadence plus a required per-frame 512-byte ACK. PID 5302's existing capture has 85.497499 ms frame-start cadence and a long 512-byte HID-report sequence without a post-frame ACK.
- There is no application-global encoder, scheduler, send, or ACK lock. Each card owns its decoder, two-stage single-slot scheduler, encoder/pipeline, latest transport slot, session worker, connection lock, pacing, and metrics.

## Safe optimizations

- Video remains decoder-native BGR; the former full-resolution PIL RGB copy is gone.
- OpenCV encoding uses its bundled libjpeg-turbo path and is substantially faster than Pillow for video frames. Quality presets are Quality 95, Balanced 88, and Performance 80.
- 4K video is downscaled near decode to 1920x1080 or 1280x720 by a bounded FFmpeg helper when available. Optional D3D11 hardware acceleration is user-controlled and falls back to CPU/OpenCV.
- Decode, delivery/encode, and transport are independent stages. Both handoffs are one-slot latest-frame replacements, preventing accumulated latency.
- Manual 30/45/60 targets are available. Metrics display requested FPS, actual FPS, decode FPS, preparation time, an Auto sustainable estimate, and Performance Limited when actual delivery is below a manual request.
- Sync shares only a future playback epoch and coordinated Play/Pause/Stop. It does not share queues or force equal transport rates.
- Wheel zoom, drag pan, numeric X/Y/zoom, reset, and Fit/Fill/Center/Stretch do not enter the playback key, so they do not recreate the decoder.

## Final bounded benchmarks

Balanced profile:

| Source | Target | Decode FPS | Transform FPS | JPEG FPS | Full prepare FPS | JPEG bytes | Protocol bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1080p60 H.264 | 1920x462 | 160.40 | 287.75 | 884.18 | 216.44 | 84,240 | 90,112 |
| 1080p60 H.264 | 1280x480 | 160.40 | 232.75 | 1,276.27 | 181.72 | 63,007 | 67,072 |
| 4K59.94 HEVC (OpenCV CPU baseline) | 1920x462 | 30.17 | 100.14 | 890.18 | 205.89 | 81,633 | 86,016 |
| 4K59.94 HEVC (OpenCV CPU baseline) | 1280x480 | 30.17 | 96.10 | 1,281.40 | 124.35 | 62,709 | 67,072 |

Concurrent full-prepare throughput was 163.95/125.20 FPS from the 1080p source and 165.19/85.86 FPS from the already-decoded 4K source. CPU was approximately 197% raw (about two logical cores); RSS ended at 58.5 MB and 76.5 MB respectively. The 4K OpenCV CPU decode baseline is the bottleneck at 30.17 FPS; measured early-scaled FFmpeg CPU decode was approximately 59 FPS and optional D3D11 decode approximately 137 FPS on this machine.

The final 60-second two-display real-4K lifecycle soak peaked at 142.4 MB RSS, 195.3% raw CPU, and 26 OS threads. Dual playback averaged 47.1% raw CPU in its stable phase. Stop/Clear returned to 101.7 MB, 19 threads, no schedulers/decoders, and empty queues. See `analysis/pipeline-benchmark-1080p60-final.json`, `analysis/pipeline-benchmark-4k-hevc-final.json`, and `analysis/resource-soak-performance-final.json`.

## Remaining physical gate

A future authorized test should run each device independently at requested 30, then 45, then 60 FPS, stopping on error and retaining latest-frame semantics. Record transport FPS, 5408 ACK latency/validity, stale drops, failures, CPU/RSS, and then repeat concurrently with sync enabled to measure start/timeline skew. Offline throughput is not permission or proof to change proven USB pacing.

Brightness remains disabled: existing evidence contains no proven brightness command.
