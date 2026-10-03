# Community Display Support Engine

## Subphase 1 safety boundary

`SafeScanner` consumes Windows PnP metadata, HID capability descriptors and
read-only WinUSB interface/pipe descriptors. It is invoked explicitly and has
no background poller. Its dependency surface intentionally excludes frame
encoders, output sessions, protocol initialization, brightness, HID output and
feature-set reports, `WinUsb_WritePipe`, serial writes, SCSI commands, reset,
driver changes and firmware operations.

Hardware identity and protocol compatibility are separate results. A shared
VID/PID remains `AMBIGUOUS` unless a safe discriminator is observed. Catalog
resolution or model data remains `CATALOG_REFERENCE`, never an observed fact.

## Declarative protocol migration path

A future versioned profile can describe these independent sections without
changing the verified drivers in this subphase:

1. `identity`: VID/PID/revision plus safe descriptor discriminators.
2. `transport`: HID, WinUSB, serial or SCSI interface and endpoint contract.
3. `initialization`: named transactions with direction and response predicates.
4. `display`: physical/render resolution and orientation evidence.
5. `encoding`: JPEG/RGB/RGB565 format and quality constraints.
6. `frame`: header fields, chunking, sequence and padding.
7. `completion`: ACK/status predicates, timeout and serialization policy.
8. `controls`: brightness and stop/shutdown capabilities.

Profiles must be data-only, schema validated and fail closed. Existing verified
5302/5408 Python drivers remain authoritative until profile parity is proven by
offline vectors and explicit physical validation.

## Future guided-capture boundary

The next evidence flow is deliberately separate:

`Safe Scan -> insufficient evidence -> Guided Vendor Capture -> Passive Capture
Analyzer -> Candidate Protocol Profile -> explicit physical validation`.

Imported support packages and captures are untrusted data. They never execute
commands or trigger active probing. The analyzer may compare passive vendor
traffic with known families, but must never brute-force commands against a
device.
