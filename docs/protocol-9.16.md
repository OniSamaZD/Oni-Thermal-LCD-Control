# 9.16-inch display protocol

## Persistence status

- **HIGH CONFIDENCE:** captured vendor frames follow an approximately 6 FPS timer cadence, independently from PID 5302.
- **CONFIRMED:** every completed frame requires the exact 512-byte `0x81` ACK; no post-ACK commit or heartbeat was observed.
- Prepared offline proof: 30 seconds, 180 known-good captured frames, 8,101 OUT writes / 32,811,008 bytes including init, exactly 180 expected ACKs, zero retries. Physical repeated-frame persistence is still **UNKNOWN**.

Status: captured transport and physical output confirmed; generated and persistent output not yet confirmed. No live transmission authorized.

## Transport and transaction

- CONFIRMED: VID 0416 PID 5408, interface 0 vendor class, endpoint 0x09 BULK OUT, endpoint 0x81 BULK IN, descriptor max packet 512.
- CONFIRMED: one complete frame transaction is a sequence of 4,096-byte host writes. Each host write aggregates eight 512-byte protocol subpackets.
- CONFIRMED: each active subpacket contains a 16-byte header and 0–496 JPEG bytes.
- CONFIRMED: after the final OUT write, the host submits one 512-byte read on 0x81 and receives one constant 512-byte response 0.322–0.421 ms after the last OUT write.
- HIGH CONFIDENCE: the constant 0x81 response is a frame-accepted/completion acknowledgement or ready status. It is one-to-one with all 20 complete frames. Its exact bit semantics remain UNKNOWN.
- CONFIRMED: no device-specific initialization or separate termination command is present in this capture. Initial control traffic is descriptor enumeration/injection; initialization requirements remain UNKNOWN.

## 16-byte subpacket header

| Offset | Length | Example | Interpretation | Confidence |
|---:|---:|---|---|---|
| 0 | 2 | `01 FF` | Protocol magic | CONFIRMED |
| 2 | 4 | `29 A6 04 00` | Total JPEG length, uint32 LE; 304,681 in example | CONFIRMED |
| 6 | 2 | `F0 01` | JPEG bytes carried by this subpacket, uint16 LE; 496 normally, shorter on final subpacket | CONFIRMED |
| 8 | 1 | `01` | Frame-data command | CONFIRMED |
| 9 | 2 | `61 01` | Total protocol chunk count, uint16 LE; 353 in example | CONFIRMED |
| 11 | 2 | `00 00`, `01 00` | Zero-based chunk index, uint16 LE | CONFIRMED |
| 13 | 3 | `00 00 00` | Reserved/constant | CONFIRMED |
| 16 | 0–496 | JPEG data | Sequential frame content | CONFIRMED |

All 20 declared JPEG lengths match reconstructed SOI-through-EOI length. All non-final chunks carry 496 bytes. The final host write contains the short final subpacket followed by zero padding and possibly unused all-zero 512-byte slots. No separate frame terminator was observed.

## Endpoint 0x81 response

Every response is exactly:

- 512 bytes
- prefix `03 FF 00 00 00 00 00 00 01`
- remaining bytes zero
- SHA-256 `b7874d85200e7782dcdedf14a9c9b4ac7a0f14949b5b49c7e02c2ddb7650c406`

CONFIRMED correlation: 20 responses for 20 complete frames, always immediately after frame OUT completion. HIGH CONFIDENCE meaning: frame completion/accepted/ready acknowledgement. Status-field meanings and behavior on failure remain UNKNOWN.

## 1920×462 investigation

- CONFIRMED: all JPEG SOF markers declare 1920×462.
- CONFIRMED: TRCC embeds explicit profiles `1920X462`, `is1920x462`, `GifDirectoryWeb1920462`, and `USBLCD\Web\zt1920462\`.
- CONFIRMED: 4:2:0 MCU geometry pads 462 to 464 internally—two codec padding rows, not 18 missing rows to 480.
- CONFIRMED: removing every 512-byte subheader eliminates all protocol magic from JPEG data. Eighteen frames then decode strictly.
- HIGH CONFIDENCE: two variable-size frames remain malformed due to vendor JPEG encoder/bitstream output, not boundary reconstruction or protocol contamination.

Evidence: `analysis/display_9_16/jpeg-diagnostics.json`, `analysis/transactions.json`.
# Captured session lifecycle (TRCC 2.1.6, 2026-08-25)

- **CONFIRMED — open request:** interface 0, BULK OUT `0x09`, 2,048 bytes. Bytes 0–15 are `02 ff 00 00 00 00 00 00 01 00 00 00 00 00 00 00`; all remaining bytes are zero. Packet 208891 at 1787665073.781624.
- **HIGH CONFIDENCE — ready response:** 0.260 ms later, BULK IN `0x81`, 512 bytes beginning `03 ff`. Packet 208896. Its nonzero offsets are 16–20, 22, 24–25, 28–29, 32, 44, and 76–77. Little-endian values at offsets 24 and 28 are 1920 and 480; byte 44 is 18. This is the only response payload differing from the frame ACK.
- **CONFIRMED — frame:** interface 0, BULK OUT `0x09`. Header `01ff18aa0200f0010161010000000000` declares 353 chunks through bytes 9–10 (`61 01`); the earlier `67 02` declares 615 chunks. This variation is content-length-derived, not a session mode. Chunk index is bytes 11–12.
- **HIGH CONFIDENCE — frame ACK/ready:** exactly one BULK IN `0x81` 512-byte response for every complete frame. The ACK begins `03ff0000000000000100` and all remaining bytes are zero. Across the lifecycle slice: 312 frames, 313 responses, exactly two response hashes: 312 identical frame ACKs plus one distinct open/readiness response. No idle polling, shutdown response, or error response was observed.
- **HIGH CONFIDENCE — close:** TRCC completed its current frame and traffic ceased. No close payload was sent. Interface/device handle release is the observed termination mechanism.
- **CONFIRMED — controls:** zero CONTROL transfers in the open/close window; no SET_CONFIGURATION, SET_INTERFACE, vendor control, or HID control request was issued by TRCC.

The ready response supplies automated evidence for the 1920×462 question: it reports 1920 and 480 while a separate byte equals 18, and transmitted JPEG SOF remains 1920×462. **HIGH CONFIDENCE:** the device/profile intentionally represents an 18-row vertical exclusion/crop within a 1920×480 physical mode; it is not caused by protocol contamination or a misplaced JPEG boundary. Correct header stripping leaves no `01ff` protocol magic in JPEG entropy data, and 18/20 earlier frames decode strictly.

Chronology and full payloads are in `analysis/session-report.json`; the capture contains no USB setup packet, so bmRequestType/bRequest/wValue/wIndex/wLength are not applicable.

The fail-closed validator accepts exactly readiness SHA-256 `129d0ceaf69fd52875982965afe2e85de5275b2ff707013de963d1992339d1bd`, then independently checks 1920, 480, and 18 at their confirmed offsets. Frame ACK must exactly match SHA-256 `b7874d85200e7782dcdedf14a9c9b4ac7a0f14949b5b49c7e02c2ddb7650c406`. Missing, late, malformed, unknown, or duplicate responses abort without retry.

Windows transport status: interface 0 uses the installed Microsoft WINUSB service and publishes `{3876E417-E089-4BCC-BBF8-47ABA55E46FB}` with a stable path matching the allowlist. Read-only live preflight passes every technical prerequisite; `allowLiveReplay=false` remains the deliberate final gate.

First controlled replay selection: `0416:5408/capture-transaction-1`, strict JPEG 1920×462, 304,681 JPEG bytes, SHA-256 `72293648c85af8298d6dfaa78759a1e5819fae022d3c1b07cc54bae37bf528a3`; 77 captured frame writes plus one initialization write. Fresh preflight passed after explicit PID-5408-only authorization. No transmission has occurred.

The offline encoder constructs type `02` subheaders, 496-byte JPEG pieces, zero-based 24-bit chunk indices, eight 512-byte subpackets per 4,096-byte write, short final content, and zero padding. Capture-derived frame 1 round-trips to 615 chunks, 77 writes, and the original JPEG hash.

An ACK proves receipt/completion but not necessarily panel presentation. Earlier `01 67 02` versus `01 61 01` interpretation as different modes was incorrect: byte 8 is command 1 and bytes 9–10 encode total chunk counts 615 and 353. No additional commit command was observed after ACK, including at captured shutdown.

## Same-session type-01 live comparison (2026-08-25)

- CONFIRMED: exactly one authorized replay used init `02ff`, its exact readiness response, a 7.63-second wait, then the exact captured `01 61 / type 01` transaction. The session contained 46 writes and 184,320 bytes, with zero retries.
- CONFIRMED: USBPcap shows every init/frame/ACK protocol payload byte-for-byte equal to the TRCC reference. All 45 frame-write boundaries and ordering match; JPEG SHA-256 is `5c0a7af2202949ceee3162ea697fe3163b263ef326681985b1e49893cb7c1277`.
- CONFIRMED timing equivalence within normal host scheduling jitter: ready-to-frame was 7,632.855 ms live versus 7,630.770 ms reference; frame duration 13.303 ms versus 13.275 ms; mean inter-write interval 0.302342 ms versus 0.301702 ms; ACK arrived 0.301838 ms after final OUT versus 0.247002 ms.
- CONFIRMED: no OUT transfer followed the ACK and no commit/display command was omitted from this replay. One additional IN read was used only to reject a duplicate ACK; it returned no payload and was cancelled during cleanup. Pipe-abort records reflect endpoint/handle release, not protocol commands.
- HIGH CONFIDENCE: transport and protocol reproduction succeeded. Visual presentation remains UNKNOWN because ACK is not treated as evidence that the panel changed.
- Live authorization is disabled again. Evidence is preserved in `analysis/live-5408-same-session-comparison.json` and `captures/originals/live_5408_same_session_20260825_1.pcap`.

Physical observation subsequently CONFIRMED that the red-eyed-character captured frame appeared on the LCD. This upgrades captured-frame visual output to CONFIRMED; ACK alone was not used for that conclusion.

TRCC persistence evidence shows a second valid type-01 frame 170.758 ms after first-frame start (157.236 ms after ACK) and continuous transmission thereafter. The controlled replay instead closed about 5 ms after ACK. No distinct keepalive, commit, or display command was observed. HIGH CONFIDENCE: persistence depends on keeping the session open and/or continuing valid frame refreshes. The two possibilities remain separately UNKNOWN until a controlled persistence test holds the session open without adding an undocumented command.

The generated candidate uses a strict 1920x462 JPEG (146,366 bytes; SHA-256 `c37c595f79ae81f0a91d35e531063f455b86212d80ec32eecd446a0b09ef47b7`). Correct framing declares 296 chunks as bytes 9–10 `28 01`, with final payload length 46, contiguous indices, 37 4,096-byte writes, and zero padding.

Generated-frame attempt 1 incorrectly retained the captured frame's declared count `61 01` (353) while sending only 296 chunks. The firmware therefore waited for 57 missing chunks and withheld ACK. TRCC IL independently confirms bytes 9–10 are the total count. The corrected encoder is byte-for-byte identical to all 45 writes of the physically proven captured transaction. No corrected generated frame has been transmitted.
