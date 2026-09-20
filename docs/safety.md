# Safety policy

Status: captured-sequence CLI replay remains disabled behind fail-closed authorization gates. Generated media in the daily-use GUI is enabled only for the two exact physically confirmed devices and only through the validated per-display `DisplaySession`; application launch, preview, settings, and media selection issue no endpoint writes.

Live USB writes require strict stable identity, ContainerId, device path, interface, endpoint and response validation plus explicit per-attempt authorization. Stop on disconnect, reset, stall, timeout, re-enumeration, or unexpected response. No driver replacement, firmware operation, fuzzing, guessed command, silent process termination, or automatic retry is permitted.

The repeated-frame command defaults to dry-run. Its live branch is hard-locked to the 30-second capture-derived plan and requires every standard gate plus a fresh persistence-specific phrase. Offline plans are hard-bounded, use exact capture-derived frames, zero retries, stable identity revalidation, and exact PID 5408 ACK validation. Both `allowLiveReplay` values remain false. GUI startup, previews, profiles, and media decoding issue no endpoint writes.

## Fail-closed replay state machine

`live_state.py` separates protocol sequencing from `UsbTransport`. `DryRunUsbTransport` and scripted faults exercise the complete state machine; `RealUsbTransport` is intentionally non-operational and raises before discovery/open. The CLI therefore has no path capable of a hardware write.

Normal transitions are `DISCONNECTED → DISCOVERED → VALIDATED → OPENING → WAITING_FOR_READY → READY → SENDING_FRAME → [WAITING_FOR_FRAME_ACK] → FRAME_ACCEPTED → CLOSING → CLOSED`. PID 5302 omits the bracketed ACK state because captures prove no frame response. Any identity, mapping, response, timeout, stall, short I/O, disconnect, re-enumeration, OS error, duplicate input, or sequence failure transitions to `ERROR` or `ABORTED`, releases the handle best-effort, and performs no retry.

Default conservative timeouts are centralized in `TimeoutPolicy`: open 2000 ms, readiness 1000 ms, each transfer 1000 ms, PID 5408 ACK 1000 ms, close 2000 ms, zero retries. `config/device-allowlist.json` records the same policy and remains `offline-only` with `live_send_authorized: false`.

`validate-live-session` is read-only and never opens endpoints. `simulate-live-replay` uses only capture-derived responses and never touches USB hardware. Event logs omit frame payloads and record deterministic timestamps, state transitions, stable identity, endpoint, length, expected/actual response class, and abort reason.

The Windows transport has a fail-closed WinUSB implementation for PID 5408 and a separate fail-closed Windows HID implementation for PID 5302. The latter follows Thermal Engine's proven MI_00 HID route, pins the exact HID path/ContainerId/report capabilities, maps report ID zero to captured 512/36-byte logical payloads, and never guesses the unpublished MI_01 WinUSB path. Both perform zero automatic retries and remain disabled by per-device `allowLiveReplay=false` gates.

The CLI requires `--send`, exact stable ID, exact known-good sequence ID, `--i-understand-live-usb`, `allowLiveReplay: true`, a fully passing fresh preflight, and the exact interactive phrase `SEND EXACT CAPTURED FRAME`.

PID 5408 alone is now explicitly authorized in the allowlist for preparation of one first controlled replay. PID 5302 remains false. The selected PID 5408 sequence has a transport-enforced immutable budget of 78 OUT writes and 317,440 bytes (one 2,048-byte initialization plus 77 captured 4,096-byte frame writes). Any attempted 79th write or excess byte aborts before the API call. Generated encoder output is never accepted as the selected first-live sequence.

The first authorized attempt aborted before WinUSB initialization and before all writes because a 64-bit `CreateFileW` HANDLE was truncated at the ctypes boundary. Explicit Windows function signatures were added offline. No retry was performed, and PID 5408 authorization was reset to false pending a new explicit confirmation.

The separately authorized corrected attempt passed fresh preflight but `CreateFileW` returned `ACCESS_DENIED`. TRCC, USBLCD, and USBLCDNEW were still running and likely held exclusive access. It aborted with no handle and no writes. Both authorization flags were reset to false; vendor processes were not terminated automatically.

After vendor processes were closed, the next separately authorized attempt opened the device but WinUSB initialization failed because `FILE_FLAG_OVERLAPPED` was absent. It aborted before every write. The mandatory flag was restored offline, both authorizations were reset to false, and no automatic retry occurred.

The subsequently authorized PID 5408 attempt succeeded end-to-end: exact initialization, exact readiness response, 77 exact captured frame writes, exact ACK, and clean handle release. The hard budget was 78 OUT writes / 317,440 bytes and was not exceeded. No retry, second frame, generated media, or PID 5302 access occurred. Authorization was reset to false immediately afterward.
