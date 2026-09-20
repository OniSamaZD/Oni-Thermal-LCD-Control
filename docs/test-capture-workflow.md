# Controlled Test A/Test B capture workflow

Status: PREPARED, NOT EXECUTED.

Test media exists under `captures/generated/test-media/` for both proven resolutions. The UI Automation inspector verifies the process/window belongs to TRCC before enumerating semantic controls and does not launch or click anything.

Required capture sequence for each display independently:

1. Start capture on confirmed `USBPcap3` with descriptor injection before TRCC opens the device.
2. Record timestamps for TRCC launch, device selection, Test A apply, Test B apply, optional Test A return, device deselection/close, and TRCC exit.
3. Use only semantic UI Automation controls whose process ID belongs to TRCC. Never use blind coordinates.
4. Stop capture after device close so initialization and termination are both present.
5. Preserve PCAPNG unchanged, hash it, and run `analyze` plus `transactions` independently for each capture device.

This capture is necessary because the existing evidence begins during active PID 5302 frame transmission and contains only injected/enumeration control descriptors, not proven device-open initialization or shutdown traffic.
