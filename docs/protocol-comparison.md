# Protocol comparison

## Persistence comparison

| Device | Evidence-backed cadence | Per-frame response | 30-second bounded proof |
|---|---:|---|---:|
| 0416:5408 | ~6 FPS | Exact 512-byte ACK required | CONFIRMED transport: 180 frames / 180 ACKs / 6.000872 FPS; physical continuity pending |
| 0416:5302 | measured vendor saturation 11.696 FPS; sparse 0.585 FPS also sustained visibility in one flawed test | No frame ACK | CONFIRMED transport: 344 frames / 11.468887 FPS; physical continuity pending |

The policies are intentionally independent. Both resend cached encoded frames for unchanged static content; neither relies on handle lifetime, heartbeat, or an invented commit command.

Generated output is now PHYSICALLY CONFIRMED on both devices simultaneously: PID 5408 used corrected command-1 chunk-count framing with an exact ACK after every frame; PID 5302 used command-2 framing with no post-frame ACK. This validates both independent encoders and persistence policies for arbitrary baseline JPEG content.

The first simultaneous bounded proof kept both independent sessions active for 29.992141 seconds with zero retries and clean close. USBPcap recovered only the approved capture-derived JPEG hashes, 344 complete PID 5302 frames, 180 complete PID 5408 frames, one PID 5408 readiness response, and exactly 180 identical PID 5408 frame ACKs. The user confirmed both images remained continuously visible and simultaneously active for the full test. Concurrent transport and simultaneous physical persistence are CONFIRMED.

| Property | Likely 9.16-inch / PID 5408 | Likely ~6-inch / PID 5302 |
|---|---|---|
| Physical mapping | HIGH CONFIDENCE | HIGH CONFIDENCE |
| Topology | Behind 1A40:0101 hub (CONFIRMED) | Direct root-hub child (CONFIRMED) |
| Interface | 0 vendor | 1 vendor; sibling HID interface 0 |
| Endpoint | 0x09 BULK OUT / 0x81 BULK IN | 0x02 INTERRUPT OUT |
| Host write | 4096 bytes | 512 bytes |
| Logical framing | Eight 512-byte subpackets per write | One 20-byte frame header, then raw continuation |
| Header | 16 bytes per subpacket | 20 bytes per frame |
| JPEG data/chunk | Up to 496 bytes | Up to 492 bytes first transfer, 512 thereafter |
| Resolution | 1920×462 | 1280×480 |
| Length | Repeated exact total JPEG length in every subheader | Frame header length; wrong/stale in 2/43 cases |
| Chunk index | 24-bit LE, zero-based | None observed |
| Final chunk | Short length field, zero padding/unused slots | EOI then zero padding |
| Response | Constant 512-byte 0x81 response per frame | None observed |
| Initialization | UNKNOWN; absent from capture | UNKNOWN; absent from capture |
| Separate terminator | Not observed | Not observed |

Protocols are materially different and must remain separate implementations.
# Session comparison

| Lifecycle element | PID 5408 | PID 5302 |
|---|---|---|
| Open | `0x09` BULK OUT, 2048-byte `02ff` command | `0x02` INTERRUPT OUT, 512-byte command 0 |
| Ready | `0x81` BULK IN, 512-byte nonzero `03ff` status | `0x83` INTERRUPT IN, 36-byte command `0x8001` identity/status |
| Frame OUT | `0x09`, 4096-byte writes with 8 subheaders | `0x02`, 512-byte writes, one 20-byte frame header |
| Frame ACK | One constant 512-byte `0x81` ACK per frame | None observed |
| Close | Handle release; no protocol payload | Handle release; no protocol payload |
| CONTROL/HID setup | None in lifecycle window | None in lifecycle window |

These protocols are independently modeled; similarities in request/response lifecycle do not imply identical framing.

PID 5302 now has two observed host access representations for the same H-protocol payload: vendor USB capture on MI_01 interrupt endpoints and Thermal Engine's standard HID MI_00 path with a leading zero report-ID byte. PID 5408 remains direct WinUSB BULK. They must remain separate transports.

PID 5408 header correction: byte 8 is command 1, bytes 9–10 are total chunks uint16 LE, and bytes 11–12 are chunk index uint16 LE. Values formerly labeled type/session (`61 01`, `67 02`) are simply 353- and 615-chunk counts.

Both protocols now use one state-machine engine with device-specific validators. PID 5408 enters `WAITING_FOR_FRAME_ACK`; PID 5302 transitions directly from frame transmission to `FRAME_ACCEPTED` only when no unexpected input is pending. Both close solely by handle release.

On the installed Windows stack, PID 5408 has a confirmed published WinUSB path. PID 5302 MI_01 is WINUSB-bound but has no published interface path, making the transport limitation device-specific rather than a protocol assumption.
