# ~6-inch display protocol

## Persistence status

- **CONFIRMED:** a one-shot captured frame appears physically, then disappears despite a 15-second open handle with zero added writes.
- **CONFIRMED SOURCE EVIDENCE:** Thermal Engine continuously sends valid frames even for static scenes.
- **HIGH CONFIDENCE:** persistence requires repeated command-2 frame transactions; no heartbeat, commit, or post-frame ACK is supported by evidence.
- **CONFIRMED PHYSICAL EVIDENCE:** 25 capture-confirmed exact frames at 0.585 FPS were part of a session that kept the image continuously visible for about 95 seconds (±1–2 seconds). This proves sparse successful refresh can sustain output; it does not determine the minimum rate.
- Corrected offline proof: 30-second monotonic hard limit, maximum 350 known-good frames at 85.497 ms / 11.696 FPS, 117,251 logical writes / 60,032,512 bytes including init, zero retries, no expected frame ACK. The intended cadence remains **NOT YET VALIDATED**.

## Vendor discovery/open path (static evidence, 2026-08-25)

- CONFIRMED: `USBLCDNEW.dll` represents PID 5302 as decimal VID 1046 / PID 21250 and handles it in `ThreadSendDeviceDataH`.
- CONFIRMED: discovery enumerates `LibUsbDotNet.UsbDevice.AllDevices`, filters `0416:5302`, calls `UsbRegistry.Open` as an eligibility test, reads `UsbRegistry.DevicePath`, extracts the serial component between `#` delimiters, and later calls `OpenUsbDevice(new UsbDeviceFinder(0416,5302,serial))`.
- CONFIRMED: the vendor method does not supply or invent a `DeviceInterfaceGuid`. After open it uses configuration 1 and claim interface 0 in the selected per-interface WinUSB registry object. Those mutating session steps were not executed by our read-only test.
- Current read-only result: the installed LibUsbDotNet `AllDevices` list contains zero PID 5302 entries, so vendor-equivalent `OpenUsbDevice(0416:5302)` returns null. MI_01 remains present, healthy, WINUSB-bound, class `{88bae032-5a81-49f0-bc3d-a4ff138216d6}`, but publishes no symbolic device-interface path. No driver or registry setting was changed.
- Evidence: `analysis/trcc-usblcdnew-discovery-il.txt` and `analysis/trcc-usblcdnew-pid5302-il.txt`.

## Standard-user HID path confirmed

Thermal Engine uses the sibling HID MI_00 interface rather than the unpublished MI_01 WinUSB path. The present unrestricted HID interface has usage page `FF06`, usage `1`, version `0407`, a 513-byte output report, and a 37-byte input report. These sizes are exactly report ID zero plus the captured 512-byte protocol packet and 36-byte readiness payload. Read-only CreateFile, HID attributes, preparsed data and capabilities all succeeded, followed by clean close without transmitting a report.

Thermal Engine prepends report ID zero to each output. Its payload framing otherwise matches the independently captured MI_01 traffic: command-zero init, command-two image header, 1280x480, format 2, uint32 JPEG length, first 492 JPEG bytes, then 512-byte continuations. Whether the HID firmware path produces identical physical presentation remains NOT YET CONFIRMED and requires one later authorized captured-frame test.

Status: independently analyzed. Physical mapping HIGH CONFIDENCE. No live transmission authorized.

## HID transport implementation status (2026-08-26)

- **CONFIRMED offline/read-only:** the allowlist pins the exact MI_00 HID path, HIDUSB driver, report ID 0, 513-byte output capability, 37-byte input capability, stable parent identity, and ContainerId. Fresh preflight re-enumerates these before any output-capable handle would be opened.
- **CONFIRMED offline implementation:** `RealHidTransport` uses bounded overlapped HID I/O/cancellation, maps report ID zero to the captured 512/36-byte protocol payloads, enforces exact path/identity/sizes/endpoints and hard write budgets, detects short I/O and re-enumeration, and performs best-effort cleanup. Automatic retries are zero.
- **CONFIRMED same-session candidate:** original capture transaction 254 is the first frame after command-0 / command-`0x8001` readiness. `analysis/pid5302-same-session-first-frame.json` contains its 335 frame reports. Including initialization, the hard first-test budget is 336 writes / 172,032 logical bytes. No frame ACK is expected or invented.
- **Historical pre-test state:** HID output had not yet been sent at this point. This is superseded by the controlled transaction below; `allowLiveReplay=false` remains the default gate.

## First physically executed HID transaction (2026-08-26)

- **CONFIRMED protocol/transport:** the exact same-session captured transaction completed through MI_00 HID and the state machine reached `CLOSED`.
- Initialization and the 36-byte `AP4S122` readiness response matched byte-for-byte. The transaction used 336 logical writes / 172,032 bytes total: one 512-byte init and 335 frame reports / 171,520 bytes.
- USBPcap independently recovered all 335 ordered frame payloads byte-for-byte; transaction SHA-256 `47af55dab42d17a9a1ba0cce9494992dc9bf5f22ba56ef1ab1da36e62f072038`. No extra OUT or IN payload occurred and no frame ACK was invented.
- Live ready-to-frame delay was 2,390.944 ms versus vendor 2,404.650 ms; live frame duration was 83.857 ms versus vendor 85.129 ms.
- The handle remained open for 15 seconds after frame completion with exactly zero additional writes, then closed cleanly. Zero retries.
- Capture: `captures/originals/live_5302_hid_captured_20260826_113754.pcapng`, 37,682 packets / 35.179164 seconds / SHA-256 `42fd22130ae68a2b76f89ceafd9580333c78ee46924ef131287ef67a12bea96f`.
- Recorder reported one global packet drop on the busy USBPcap3 side, but PID 5302 was on USBPcap4 and its complete init, readiness, and every expected frame payload are present. Target transaction completeness is therefore CONFIRMED.
- **VISUAL RESULT UNKNOWN:** physical panel observation is still required. Live authorization was restored to false.

## Transport and transaction

- CONFIRMED: VID 0416 PID 5302, composite device; HID interface 0 and vendor interface 1.
- CONFIRMED: display frames use interface 1 endpoint 0x02 INTERRUPT OUT with 512-byte host payloads.
- CONFIRMED: every recoverable frame begins on a 512-byte transfer boundary with a 20-byte header, followed immediately by JPEG.
- CONFIRMED: JPEG continues across sequential 512-byte writes. EOI is followed by zero padding to the boundary; the next transaction starts with a new header.
- CONFIRMED: 43 complete 1280×480 frame transactions are isolated.
- CONFIRMED: no corresponding non-control IN response is present.
- UNKNOWN: device-specific initialization. Capture begins mid-frame and initial control traffic is descriptor enumeration/injection.
- HIGH CONFIDENCE: transaction termination is implicit through declared/observed JPEG completion and zero padding; no separate command is observed.

## 20-byte frame header

| Offset | Length | Example | Interpretation | Confidence |
|---:|---:|---|---|---|
| 0 | 4 | `DA DB DC DD` | Frame magic | CONFIRMED |
| 4 | 4 | `02 00 00 00` | Command/type 2 | CONFIRMED value / TENTATIVE role |
| 8 | 2 | `00 05` | Width, uint16 LE = 1280 | CONFIRMED |
| 10 | 2 | `E0 01` | Height, uint16 LE = 480 | CONFIRMED |
| 12 | 4 | `02 00 00 00` | Codec/format discriminator 2 | CONFIRMED value / HIGH CONFIDENCE JPEG role |
| 16 | 4 | varies | JPEG length, uint32 LE | HIGH CONFIDENCE |

The length equals actual JPEG size for 41/43 frames. Two frames have stale/incorrect larger declared lengths, but the next frame magic occurs earlier after a valid JPEG EOI and zero padding. This proves transaction isolation must use both header boundaries and JPEG validation, not blindly trust the length field.

No chunk header or chunk index exists on continuation transfers in the observed protocol.
# Captured session lifecycle (TRCC 2.1.6, 2026-08-25)

- **CONFIRMED — open request:** interface 1, INTERRUPT OUT `0x02`, 512 bytes. First 20 bytes: `da db dc dd 00 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00`; remainder zero. This is command 0 with fields 0, 1, 0. Packet 194204 at 1787665069.535235.
- **HIGH CONFIDENCE — ready/identity response:** 0.750 ms later, INTERRUPT IN `0x83`, 36 bytes: `dadbdcdd018000000000000001000000100000004150345331323212004dd04807323e78`. Command is `0x8001`; payload contains ASCII identity `AP4S122` plus binary state/identity bytes. Packet 194206.
- **CONFIRMED — frame:** 2.405 s later, normal command-2 frame begins on interface 1, INTERRUPT OUT `0x02`; header remains magic, command 2, 1280×480, format 2, JPEG length.
- **HIGH CONFIDENCE — acknowledgement semantics:** no per-frame INTERRUPT IN or CONTROL response was observed. Endpoint `0x83` was used once for the open identity/readiness response, not as a per-frame ACK.
- **HIGH CONFIDENCE — close:** current frame completed and all traffic ceased; no close command or response payload was observed. Termination is interface/device handle release.
- **CONFIRMED — controls:** zero CONTROL transfers in the captured open/close window. No HID feature/output report over endpoint 0, SET_CONFIGURATION, SET_INTERFACE, or vendor control request established the session; the mandatory observed handshake is the endpoint `0x02` command-0 / endpoint `0x83` command-`0x8001` pair.

Full chronological payload evidence is in `analysis/session-report.json`. Because no setup packet occurred, bmRequestType/bRequest/wValue/wIndex/wLength are not applicable.

The fail-closed validator accepts only the exact 36-byte readiness payload with SHA-256 `a8f22dfb338d94889aa583a8ad5a3e81bdb3b90da67f272e7690d3c52bf53fc1`, command `0x8001`, and ASCII `AP4S122`. It expects no post-frame response; any such input aborts the session.

Historical MI_01 status: it is WINUSB-bound but publishes no openable path. The selected access route is now the legitimate sibling MI_00 HID collection proven by Thermal Engine and read-only validation; interface-1 endpoint labels remain logical protocol/capture metadata.

Expanded read-only discovery found the legitimate MI_00 HID interface used by Thermal Engine. Although it is not the captured MI_01 WinUSB endpoint owner, its report ID zero plus 512/36-byte HID reports map exactly to the captured command framing and readiness payload. This is the selected user-mode route; physical output through it remains NOT YET CONFIRMED and live authorization remains disabled.

Its independent offline encoder emits the 20-byte command-2/1280×480/format-2 header, exact JPEG length, 512-byte writes, EOI-aware reconstruction, and zero final padding. Capture-derived frame 1 round-trips with 171,717 JPEG bytes in 336 writes.
