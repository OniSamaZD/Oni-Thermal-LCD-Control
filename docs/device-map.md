# Device map

## Stable Windows identities

| Likely display | VID:PID | Stable instance | ContainerId | Driver | Topology | Confidence |
|---|---|---|---|---|---|---|
| 9.16-inch | 0416:5408 | Local value (not published) | Local value (not published) | WINUSB | Local topology (not published) | HIGH CONFIDENCE |
| ~6-inch | 0416:5302 | Local value (not published) | Local value (not published) | WINUSB MI_01; HidUsb MI_00 | Local topology (not published) | HIGH CONFIDENCE |

Topology and stable IDs were confirmed locally but are deliberately omitted from the public repository. Physical size mapping is HIGH CONFIDENCE: PID 5408 sends 1920×462 images matching the 9.16-inch form factor; PID 5302 sends 1280×480. A safe known-good identify replay or one visual confirmation is still required for CONFIRMED status.

Capture bus/device addresses 3.5 and 3.6 are transient evidence correlations only and must not be persistent identities.
