# Extreme low-CPU / low-overhead milestone

Date: 2026-08-27. Every profile used `OfflineSink`; USB/HID writes were zero.

## CPU ROOT CAUSE

The dominant cost was not JPEG encoding or Qt. Each FFmpeg helper decoded/exported every 59.94 FPS source frame through a raw BGR pipe although the two proven LCD paths consume far fewer updates. When the sequential pipe fell behind, scheduler catch-up also decoded frames that were immediately discarded. New frames additionally bypassed `DisplaySession` pacing while cached persistence sends still ran on their deadline, creating redundant work.

## HOTTEST THREAD/STAGE

The D3D11/FFmpeg decode, scale, hardware-to-system-memory transfer, and raw-pipe helpers remain hottest. JPEG encoding is 659–1,202 FPS and full preparation is 214–517 FPS in final tests, so neither is the limiting stage. Qt idle work is approximately 0.12% normalized CPU.

## OPTIMIZATIONS MADE

- D3D11 hardware decode is selected in Game Mode; the UI reports the active backend or the exact CPU fallback reason.
- FFmpeg selects useful timeline frames before scaling/copy-back and exports exact LCD-sized aspect-preserving frames, not 1920x1080/1280x720 intermediates.
- Sequential-source catch-up resets the monotonic deadline instead of decoding stale frames.
- Video source time remains correct: selecting 10/11.696 frames per second does not slow the 59.94 FPS media timeline.
- Hidden previews allocate no PIL/QImage frame. Visible preview is independent at 10 FPS in Game/low-resource modes, 15 FPS Normal, and 20 FPS High FPS.
- Metrics timers are 2 seconds in Game/Ultra Low Resource, 1.5 seconds Low Resource, 500 ms Normal, and 250 ms High FPS. Hidden card timers stop.
- Transform state stays cached under one per-card lock.
- `DisplaySession` now paces both new and repeated frames through one monotonic deadline and selects the latest pending frame; it no longer sends immediate new frames plus persistence repeats.
- Existing one-slot decoder and transport queues, independent workers, proven protocol framing, ACK behavior, and zero-retry rules are unchanged.

## HARDWARE DECODE STATUS

Both final media paths reported `Hardware (d3d11va)`. Initialization failures now produce an explicit `CPU fallback (OpenCV/FFmpeg; <reason>)` diagnostic rather than a silent fallback. CPU fallback remains available.

## CONTROLLED 60-SECOND RESULTS

CPU includes the application and all FFmpeg child processes. Normalized CPU is raw process-tree CPU divided by 16 logical CPUs.

| Scenario | Before normalized mean | After normalized mean | After p95 | After peak | Peak RSS | Peak threads |
|---|---:|---:|---:|---:|---:|---:|
| Idle visible | 0.103% | 0.116% | 0.200% | 0.388% | 66.0 MB | 7 |
| Idle tray | 0.122% | 0.118% | 0.200% | 0.381% | 66.0 MB | 7 |
| 1080p one display | 5.976% | 1.890% | 2.469% | 3.906% | 267.4 MB | 86 |
| 1080p two displays | 11.164% | 3.808% | 4.688% | 5.488% | 418.5 MB | 145 |
| 4K HEVC one display | 8.109% | 2.605% | 3.325% | 8.400% | 431.4 MB | 85 |
| 4K HEVC two displays | 15.708% | 6.253% | 7.669% | 13.656% | 745.3 MB | 145 |

The final 1080p one-display mean is 68.4% below baseline; dual 1080p is 65.9% lower. Final 4K one-display is 67.9% lower; dual 4K is 60.2% lower.

Final device metrics were approximately 10.0/11.7 selected decode FPS, 659–1,202 JPEG FPS, 214–517 prepared FPS, 5.6–5.7 PID 5408 offline session FPS, and 10.5–10.6 PID 5302 offline session FPS. These are offline sink measurements, not new physical USB claims.

## REALISTIC MINIMUM CPU FLOOR

Idle floor is about 0.12% normalized. One 1080p display reaches a 1.89% mean but not a strict sub-2% p95. One 4K HEVC display reaches 2.61% mean. Two independent hardware decoders raise the realistic floor to about 3.81% for dual 1080p and 6.25% for dual 4K. The remaining floor is primarily two independent GPU decode/filter/copy-back helpers; sharing a decoder would violate independent media semantics, while eliminating copy-back would require a GPU-native JPEG path not present in the reviewed environment.

Reports are `analysis/low-cpu-*.json` (baseline), `analysis/low-cpu-after-idle_*.json`, and `analysis/low-cpu-final-*.json`.
