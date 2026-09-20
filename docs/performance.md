# Performance profiling

Oni's profiler measures each workload in a fresh offscreen process. It never
opens a USB device: hardware senders are replaced before the GUI cards are
constructed, and every report records both `live_usb_permitted=false` and
`usb_writes=0`.

Run the short repeatable profile from the repository root:

```powershell
.\tools\profile-performance.ps1 -Duration 5
```

For a later soak test, use the same scenarios with a longer sampling window:

```powershell
.\tools\profile-performance.ps1 -Duration 1800 -Interval 5 -Output analysis/performance-soak-30m.json
```

## Scenarios and interpretation

The nine scenarios cover disconnected and simulated-connected GUI idle, dual
static content, static/GIF, dual GIF, static/video, dual video, monitor overlays,
and all integrations. Static content is encoded once and the immutable protocol
frame is reused. Animation uses the real one-frame scheduler, latest-frame queue,
resizer, JPEG encoder and protocol encoder. Synthetic video deliberately uses
that same pipeline without importing OpenCV, proving that idle/static/GIF paths
do not pay OpenCV's memory cost.

The JSON records working set, private bytes, committed virtual memory, CPU,
handles, threads, queue depth,
actual FPS and drops. `growth_mb_per_minute` is an ordinary least-squares trend
over the settled sample window. A short positive slope can be allocator warm-up;
it is evidence for investigation, not proof of a leak. Stable handle/thread
counts, bounded queue depth, and post-cleanup memory are equally important.

The connected and integration-provider states are simulations because this is an
offline test. Offscreen Qt also excludes some visible Windows compositor costs.
Use the prepared 30-minute command before release and a visible packaged-EXE run
for final acceptance. Standard `psutil` does not expose trustworthy per-process
GPU counters, so the report marks GPU metrics unavailable instead of fabricating
zero; packaged visible-run ETW/GPU evidence remains follow-up work. The `<100 MB`
dual-static working-set goal remains an
engineering target, not a claim; the measured report is authoritative.

## Current short-run evidence

The 2026-08-27 three-second-per-scenario Windows run used the complete offscreen
`MainWindow` (no fallback). Peak measurements were:

| Scenario | Working set | Private bytes | Mean CPU | Handles | Threads |
|---|---:|---:|---:|---:|---:|
| Idle disconnected | 53.4 MB | 29.7 MB | 1.0% | 251 | 5 |
| Idle connected (simulated) | 53.3 MB | 29.7 MB | 1.0% | 251 | 5 |
| Dual static | 54.5 MB | 29.9 MB | 1.0% | 267 | 7 |
| Static + GIF | 54.8 MB | 30.1 MB | 8.2% | 271 | 8 |
| Dual GIF | 55.0 MB | 31.0 MB | 13.4% | 275 | 9 |
| Static + video | 54.5 MB | 30.0 MB | 11.3% | 271 | 8 |
| Dual video | 55.4 MB | 32.1 MB | 19.6% | 275 | 9 |
| Monitor overlays | 54.5 MB | 30.4 MB | 1.0% | 259 | 6 |
| All integrations | 57.4 MB | 34.0 MB | 18.6% | 283 | 10 |

All queues remained at depth zero at sample time, drops were zero, and all nine
short leak screens reported no obvious growth; handles and threads remained
bounded during every scenario. OpenCV remained unloaded in all
nine scenarios. Dual-static peak working set was below the aggressive 100 MB
target in this offscreen source run. Animated CPU results model encoding load and
are not packaged-EXE or visible-desktop acceptance results.
