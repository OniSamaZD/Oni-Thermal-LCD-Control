# Thermal Engine 0.8.2-pre reference

## License and reuse decision

The local reference at `D:\Thermal-Engine-0.8.2-pre` is MIT licensed. Its `LICENSE` says Copyright (c) 2024 and requires the copyright and permission notice in copies or substantial portions. MIT imposes no source-disclosure requirement and permits use, modification, redistribution, sublicensing, and commercial distribution. Direct reuse is compatible if the notice is retained.

This project used Thermal Engine primarily as a behavioral reference. The new HID discovery and runtime modules were independently implemented for this repository; no function body was copied. Protocol constants and the HID report-ID convention were compared against both Thermal Engine and our independent USB captures. The required notice is retained in `THIRD_PARTY_NOTICES.md`.

## Architecture observed

- Python 3.10+, PySide6 UI, Pillow images, hidapi device access, OpenCV video, psutil diagnostics.
- `DeviceManager` supports multiple simultaneous devices in a dictionary keyed by VID/PID, while editor sessions carry independent frame buffers.
- The UI uses periodic timers and an optional render worker; stale rendered content is replaced instead of accumulated. Frames are sent repeatedly at the selected target FPS while the device handle stays open.
- GIF frames are decoded into a bounded in-memory representation with source durations. Video is decoded with OpenCV, resized before storage, and capped by a maximum buffered-frame count.

## PID 5302 findings

Persistence call-chain evidence is direct: connection invokes `start_continuous_send`; default `target_fps` is 30; a `QTimer` invokes `send_frame_with_sensors`; every tick renders every session, including static elements, and calls `session.device.send_frame(img)`. There is no static one-shot branch, heartbeat, or post-frame commit. Blocking ~85 ms HID writes explain the captured ~11.696 FPS saturation.

- Registry entry maps `0416:5302` to `TrofeoVisionDevice`.
- Access is HID, not MI_01 WinUSB: enumerate VID/PID, open the HID symbolic path, prepend report ID zero to every 512-byte output report.
- Init is 512 bytes: `DA DB DC DD`, command zero, byte 12 equals one. It reads a response for up to two seconds.
- The response byte 5 selects resolution; value 128 means 1280x480. Board identity occupies bytes 20–35.
- Frame command is 2; width/height are little-endian at 8/10, format 2 at offset 12, JPEG length uint32 LE at 16, first 492 JPEG bytes at offset 20, then padded 512-byte reports.
- JPEG encoding uses Pillow baseline output, quality 80, `optimize=False`, subsampling 2.
- The source does not validate AP4S122 exactly and tries all HID interfaces. Our implementation remains stricter: exact MI_00, VID/PID, ContainerId and exact captured AP4S122 response are mandatory.

Read-only local validation found exactly one unrestricted HID interface, usage page FF06 / usage 1. It opened read-only and reported input length 37 and output length 513: one report-ID byte plus the independently captured 36-byte response / 512-byte protocol packet. No report was transmitted.

## PID 5408 findings

Automated JPEG marker comparison shows the attempted image was strict baseline 4:2:0 with standard Huffman tables and correct 1920x462 SOF/EOI. Its quality-92 quantization and unitless JFIF density differ from captured quality-95/96-DPI output, but there is no evidence those differences caused rejection. New application encoding matches the captured quality/JFIF profile.

Thermal Engine's PID 5408 class is explicitly a stub, so it is not evidence of a working JPEG encoder. Its comments point back to TRCC decompilation. Direct IL inspection of the installed TRCC helper resolved our failure:

- byte 8 is command 1;
- bytes 9–10 are uint16 LE total chunk count;
- bytes 11–12 are uint16 LE chunk index;
- bytes 13–15 are zero;
- chunk count is `jpeg_length // 496 + 1`;
- the subpacket array is padded to a multiple of four;
- host writes are 4096 bytes except a final 2048-byte write when applicable.

The earlier generated attempt advertised the captured frame's 353 chunks although it contained 296. The device waited for 57 missing chunks and did not ACK. After correction, our encoder reproduces all 45 writes of the physically proven captured transaction byte-for-byte.

## Reuse inventory

- Reused implementation text: none.
- Independently reimplemented concepts: exact HID discovery/open eligibility, bounded latest-frame queue, independent display workers, Pillow-compatible static pipeline, two-card PySide6 shell.
- Constants cross-checked: PID 5302 magic/header/report sizes, quality/subsampling, HID report ID; PID 5408 details were confirmed from TRCC IL and USB captures rather than relying on Thermal Engine's stub.
