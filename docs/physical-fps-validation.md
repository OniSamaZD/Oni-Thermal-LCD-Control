# Physical FPS validation — known transport only

Date: 2026-08-27. Authorization was limited to the already validated initialization, normal generated frame packets, PID 5408 exact ACK, and handle release. No unknown command, retry, driver change, firmware action, or brightness request occurred.

The moving 1080p60 fixture supplied distinct timeline frames. Each independent target ran for three seconds; the final synchronized dual run lasted five seconds. Queue depth was bounded to one and stale timeline slots were discarded.

## PID 5408

| Requested | Completed physical transport FPS | Stable | Median frame | p95 frame | Median ACK | p95 ACK | Stale drops |
|---:|---:|---|---:|---:|---:|---:|---:|
| 10 | 9.979 | yes | 18.058 ms | 21.518 ms | 0.145 ms | 0.174 ms | 0 |
| 20 | 19.872 | yes | 15.477 ms | 21.147 ms | 0.145 ms | 0.189 ms | 0 |
| 30 | 29.826 | yes | 18.034 ms | 22.008 ms | 0.149 ms | 0.183 ms | 0 |
| 45 | 42.440 | yes, latest-frame | 15.836 ms | 31.189 ms | 5.376 ms | 13.156 ms | 6 |
| 60 | 42.667 | no | 16.166 ms | 31.369 ms | 7.506 ms | 13.137 ms | 51 |

Minimum observed frame completion was 7.32 ms, but alternating/queued device completion behavior raises p95 to about 31 ms at saturation. The sustainable ceiling is approximately 42–43 distinct completed frames/s with this known ACK-driven protocol and representative ~89 KB frames. A 16.67 ms median alone is insufficient for 60 FPS because the tail/ACK-ready behavior cannot sustain every deadline.

## PID 5302

| Requested | Completed physical transport FPS | Stable | Median frame | p95 frame | Stale drops |
|---:|---:|---|---:|---:|---:|
| 10 | 9.926 | yes | 32.815 ms | 33.809 ms | 0 |
| 20 | 19.772 | yes | 32.405 ms | 33.634 ms | 0 |
| 30 | 29.509 | yes | 32.479 ms | 33.899 ms | 0 |
| 45 | 30.167 | no | 32.546 ms | 33.769 ms | 43 |
| 60 | 30.333 | no | 32.532 ms | 33.676 ms | 87 |

The representative Balanced frames averaged ~66 KB and 129 HID reports. HID report submission occupies approximately 32.5 ms/frame, giving a mathematical ceiling near 30.7 FPS. There is no frame ACK in the known protocol; successful completion means all exact reports completed without short I/O/error.

## Final synchronized dual run

- PID 5408 target 45: 42.400 completed FPS, 213/213 exact ACKs, 12 stale drops, 3.787 MB/s.
- PID 5302 target 30: 29.711 completed FPS, no errors, 0 stale drops, 1.978 MB/s.
- Shared data-phase start skew: 0.0 ms at recorded clock resolution.
- Normalized CPU mean/peak: 0.805% / 4.675% (pre-encoded transport-only harness).
- Peak RSS: 75.9 MB; peak process threads: 39.
- Neither transport waited for the other after the shared start barrier.

## Implementation

- Static persistence evidence remains 6 FPS/11.696 FPS.
- Video Auto targets are now 45 FPS for PID 5408 and 30 FPS for PID 5302.
- Manual 10/20/30/45/60 changes both timeline-frame selection and transport deadline. Requested FPS never changes media duration.
- `DisplaySession` gates new and repeated frames through one monotonic deadline. New media replaces pending stale media rather than bypassing pacing.
- Actual GUI FPS remains successful completed frame transactions, including exact ACK completion for PID 5408.

Evidence: `analysis/physical-fps-progression-20260827.json` and `analysis/physical-fps-dual-final-20260827.json`.

## Conclusion

**REAL PHYSICAL 60 FPS NOT POSSIBLE WITH CURRENT KNOWN TRANSPORT.** PID 5408 ceilings near 42–43 FPS under ACK saturation; PID 5302 ceilings near 30–31 FPS due to sequential HID report duration.
# Quality/transport ceiling follow-up (2026-08-27)

A requested-60 sweep changed only the already proven JPEG quality profile; protocol ordering, initialization, endpoints, ACK rules, and retry count were unchanged.

| Device | Quality | Mean protocol bytes/frame | Completed FPS | Limiting evidence |
|---|---:|---:|---:|---|
| PID 5408 | Quality | 132,993 | 42.454 | Exact ACK serialized after every frame |
| PID 5408 | Balanced | 89,024 | 42.333 | Size reduction did not improve cadence |
| PID 5408 | Performance | 70,537 | 42.454 | Size reduction did not improve cadence |
| PID 5302 | Quality | 98,312 | 20.333 | 192 HID reports/frame, ~2.03 MB/s |
| PID 5302 | Balanced | 66,087 | 30.504 | 129 HID reports/frame, ~2.04 MB/s |
| PID 5302 | Performance | 52,167 | 38.667 | 102 HID reports/frame, ~2.03 MB/s |

The ten-second simultaneous confirmation completed PID 5408 at 42.3 FPS with 424/424 exact ACKs and PID 5302 at 37.9 FPS with no stale drops. Shared start skew was 0 ms. No retries, unknown commands, stalls, short I/O, or disconnects occurred. Therefore **real physical 60 FPS is not achieved** with the known safe protocols. PID 5408 is ACK/cadence bound rather than JPEG-size bound; PID 5302 is HID report-throughput and encoded-frame-size bound. These are measured ceilings, not hard GUI caps: manual 60 remains selectable and reported separately from completed physical FPS.

## PID 5302 quality-75 Pareto validation

An offline 60-frame Fill comparison found quality 75 averaged 46.5 KB, 91.5 reports, and 39.17 dB PSNR versus quality 80 at 51.9 KB, 101.9 reports, and 40.21 dB. Because PID 5302 is report-throughput bound, this was a plausible known-protocol improvement and was physically retested once. The ten-second requested-60 run completed **43.2 FPS**, 433 frames, averaging 46,898 bytes and 91.60 reports per frame at 2.031 MB/s. There were zero errors, retries, unknown commands, or invented acknowledgements. This supersedes 38.67 FPS as the current PID 5302 measured transport baseline, but it still does not establish real 60 FPS.

An explicit `Extreme FPS` Pareto option was then tested at quality 50 (36.25 dB mean PSNR) and quality 45 (35.83 dB). Both completed exactly **53.4 FPS / 535 frames** in ten seconds. Quality 45 averaged 32,980 bytes and 64.41 reports with a 16.20 ms median write, but its p95 remained 24.08 ms and frame starts retained the Windows HID 16/31 ms scheduling pattern. The absence of improvement after crossing below the nominal 16.67 ms median establishes a host/HID scheduling ceiling around 53–54 FPS for this workload. Auto Extreme targets 54; manual 60 remains available. Real 60 is still not claimed.
