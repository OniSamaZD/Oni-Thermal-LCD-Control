# Playback architecture and resource evidence — 2026-08-28

## Selected architecture

When Display Sync is enabled and both LCDs use the same animated/video source, Oni uses one in-process PyAV/libavcodec decoder. One immutable latest decoded ndarray reference is fanned into two independent single-slot workers. Each worker retains its own transform, crop, pan, zoom, brightness, quality, JPEG, protocol framing, physical cadence, and stale-frame count. Replacing a slow consumer slot drops only that consumer's old reference; it cannot block the other LCD.

PyAV uses early geometry-aware scaling. Fit/Center retains only a contained source surface (approximately 853×480 for a 16:9 source shared by these LCDs). Fill/Crop or active pan/zoom retains cover resolution so transform semantics are not falsified. HEVC or greater-than-1080p sources request in-process D3D11VA with explicit software fallback; 1080p H.264 uses the lower-CPU software path measured on this host.

Different media remain independent. External early-scaled FFmpeg remains the measured lower-CPU backend for two unrelated sources; it is counted honestly as part of Oni's process tree. It is never renamed, hidden from metrics, or described as free.

## Same-media before/after

| Workload | Architecture | CPU mean | Peak RSS | Helper processes |
|---|---|---:|---:|---:|
| Dual 1080p60 baseline | 2 external scaled FFmpeg decoders | 8.647% | 411.02 MB | 2 |
| Dual 1080p60 shared | 1 in-process PyAV decoder, early Fit scale | 8.407% | 184.89 MB | 0 |
| Dual 4K60 HEVC independent | 2 external D3D11VA helpers | 10.507% | 636.75 MB | 2 |
| Dual 4K60 HEVC shared | 1 in-process PyAV D3D11VA decoder | 7.796% | 297.46 MB | 0 |

The shared 1080 path reduces memory by 55%, removes both helpers, and slightly reduces CPU. The shared 4K HEVC path reduces memory by 53% and CPU by 26% while removing both helpers.

## Other matrix results

| Scenario | CPU mean | Peak RSS | Notes |
|---|---:|---:|---|
| Visible stopped | 0.124% | 65.73 MB | zero USB writes |
| Tray stopped | 0.118% | 65.91 MB | zero USB writes |
| One 1080p60 | 5.851% | 264.29 MB | one external early-scaled helper |
| Different/independent dual 1080p60 | 8.957% | 414.75 MB | two independent sources |
| One 4K60 HEVC | 6.490% | 380.61 MB | one external D3D11VA helper |
| Different/independent dual 4K60 HEVC | 10.507% | 636.75 MB | two independent sources |
| Shared 1080p60 in tray | 9.645% | 173.35 MB | preview target 0.1 FPS; zero helpers |

All measurements include the complete process tree. Offline acceptance used a USB-impossible sink.

## Ten-minute soak

The shared in-process 1080p60 soak completed 18,473 9.16-inch branch frames and 12,758 6.86-inch branch frames with no helper process. Quarterly RSS means were 178.05, 179.15, 179.94, and 180.10 MB; peak RSS was 189.91 MB. The small allocator warm-up plateaued rather than forming an unbounded queue or frame history.

## Copy audit

- External baseline: decoder helper → raw BGR pipe → NumPy copy → output-sized OpenCV transform → JPEG buffer; QImage is created only when preview is due.
- Shared PyAV: decoded AVFrame → early-scaled BGR ndarray once → immutable reference fan-out → independent output-sized OpenCV transforms/JPEG. No full source-frame copy is made for the second LCD.
- Pillow is not used in the hot video path.
- Preview QImage/PIL canvas generation is skipped entirely when preview is not due. Hidden/tray preview target is 0.1 FPS while physical/session cadence remains independent.
- Protocol queues, decoded consumer slots, and preview bridge are all latest-frame bounded.

## Thread experiment

Restricting OpenCV from its optimized native pool to two threads reduced total threads from 71 to 53 but increased normalized CPU from 8.41% to 9.74%; four threads measured 9.91%. The lower-total-CPU native configuration was retained. Codec threads remain explicitly bounded to two in PyAV.

