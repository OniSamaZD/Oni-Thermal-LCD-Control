# Device support research

This document separates hardware ONI has physically tested from protocol-only research. A repository implementing a protocol is interoperability evidence, not proof that ONI safely supports every product sold under a similar name.

## Status definitions

- **Physically verified** — ONI output was tested on real hardware by this project.
- **Protocol verified / community test needed** — public specifications and offline protocol tests exist, but ONI has not tested the hardware.
- **Experimental** — useful upstream protocol evidence exists, but identification, transport, or safety validation is incomplete.
- **Unsupported** — evidence is insufficient for safe public writes.

## Findings

| Family | Upstream evidence | License | Transport / protocol | Known identity / resolution | ONI status |
|---|---|---|---|---|---|
| Thermalright Trofeo Vision 9.16 / 6.86 | ONI captures and reviewed public definitions | ONI original research | WinUSB bulk / Windows HID; JPEG transaction protocols | `0416:5408` 1920×462 active canvas; `0416:5302` 1280×480 | **Physically verified**, output enabled |
| BeadaPanel | [NXElec Panel-Link](https://github.com/NXElec/panelLink), official Panel-Link/Status-Link manuals, [beadapanel-python](https://github.com/unawakened1986/beadapanel-python), [InfoPanel](https://github.com/habibrehmansg/infopanel), [beada-drm](https://github.com/oskarirauta/beada-drm) | NXElec demo and InfoPanel GPL-3.0; beadapanel-python MIT; beada-drm GPL-2.0 | WinUSB interface 0; Status-Link `0x02/0x82`, Panel-Link `0x01`; RGB565/BGR565 selected from panel info | `4e58:1001` and reported `4e58:1002`; panel-info geometry includes 320×480 through 462×1920 families | **Protocol verified / community test needed**. ONI independently implements bounded tag and RGB565/BGR565 encoding plus exact read-only descriptor classification. Output transport remains disabled. |
| MacroSilicon MS9132 / Jonsbo DS339 / VMAX 4.6 | User-supplied maintained [InfoPanel fork](https://github.com/emaspa/infopanel-1), [MacroSilicon GPL MS91xx driver fork](https://github.com/bambinounos/ms91xx-linux-drm) | GPL interoperability evidence; clean-room Python integration | Composite HID feature-report control plus WinUSB bulk EP `0x04`; BGR888 frame envelope in 64 KiB transfers | `345f:9132`; valid EDID preferred timing selects DS339 376×960 or VMAX 320×960 before bulk output | **Experimental**, runtime output enabled; community hardware validation required |
| Turing Smart Screen / TURZX | [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python), user-supplied InfoPanel sources | GPL-3.0 interoperability evidence; clean-room Python integration | Unique `1cbe` USB revisions use DES-framed 512-byte commands on bulk EP `0x01/0x81`; JPEG command 101. Serial revisions remain a separate incompatible family. | Output enabled for `1cbe:0088`, `0080`, `0092`, `0046`, `0050`, `0016`, `0021` with fixed model geometry. Shared serial `1a86:5722` remains ambiguous. | **Experimental** for the seven exact USB revisions; shared serial revisions remain unsupported |
| XuanFang | turing-smart-screen-python | GPL-3.0; no source copied | Model-specific USB serial; some visually similar HID devices are explicitly incompatible | 3.5-inch 320×480 commonly documented; identity is not safely unique | **Experimental**, no ONI output |
| UsbPCMonitor | turing-smart-screen-python, [ch340disp](https://github.com/thomasteoh/ch340disp) | GPL-3.0 references; clean-room protocol integration | CH340 USB serial at 115200 with RTS/CTS; six-byte HELLO and full-frame RGB565 little-endian | Shared `1a86:5722` bridge ID; exact HELLO `01×6`, `02×6`, `03×6` selects 320×480, 480×800, 600×1024 respectively | **Experimental**, runtime output enabled only for the three exact HELLO responses; all other responses fail closed |
| Kipye / Qiye | turing-smart-screen-python | GPL-3.0; no source copied | USB serial revision D | 3.5-inch 320×480 reported upstream; exact public identity incomplete | **Experimental**, no ONI output |
| WeAct Display FS V1 | [WeActStudio.SystemMonitor](https://github.com/WeActStudio/WeActStudio.SystemMonitor), turing-smart-screen-python | GPL-3.0; reference implementation not copied | USB 2.0 FS CDC, distinct 0.96/3.5-inch protocols, RGB565 | 160×80 and 320×480 reported upstream; safe Windows identity/handshake still incomplete | **Experimental**, no ONI output |
| AX206 / AIDA64 / USB2LCD photo frames | turing-smart-screen-python issue research, lcd4linux/dpf-ax ecosystem, [win-ax206-display](https://github.com/mechcow/win-ax206-display) | GPL-derived protocol references; no implementation copied | USB Mass Storage Bulk-Only Transport carrying vendor CDBs; driver replacement may be required | `1908:0102` and bulk endpoints `0x01/0x81` are useful diagnostic evidence, but geometry varies | **Experimental diagnostics only**: exact read-only classification exists; output remains disabled |
| Waveshare / GUITION vendor USB monitors | turing-smart-screen-python compatibility research | GPL research index | Proprietary or firmware-dependent | Product naming is insufficient | **Unsupported** |
| Thermaltake 6-inch / ASRock 480×480 | InfoPanel | GPL-3.0; no source copied | InfoPanel reports support, but ONI has no independent protocol specification | Model-specific identity not established | **Experimental research only**, no ONI output |

## Licensing decision

No GPL implementation source from turing-smart-screen-python or InfoPanel was copied or adapted. Copying those implementations into ONI would require GPL compatibility and corresponding-source obligations for distribution. ONI therefore uses them only as factual interoperability evidence. The small BeadaPanel encoder was independently written from public protocol descriptions and official format facts; the MIT beadapanel-python project is credited as corroborating evidence.

## Safety boundary

Catalog entries never create connected displays. Runtime sessions are created only after physical enumeration and each enabled family's exact probe. MS9132 additionally requires one unambiguous HID/bulk pair and a checksum-valid EDID whose preferred timing matches a supported model. Serial bridge VID/PID values are never sufficient because unrelated products share them. Unknown, incomplete, ambiguous, and malformed descriptors remain blocked.

The community classification API can report exact BeadaPanel and AX206 descriptor evidence and can label shared `1a86:5722` CH340 identities as ambiguous. Every community classification returns `output_authorized=false`; it never opens a handle, performs a handshake, or sends a probe command.

## Community validation needed

BeadaPanel is the first candidate for a guarded transport integration because the vendor publishes protocol documentation. Required next evidence is a read-only descriptor/panel-info capture and physical confirmation of initialization, pixel order, orientation, brightness, bounded timeouts, disconnect/reconnect, and shutdown on each model. All other experimental families need equally specific identity and protocol evidence before an output adapter can be enabled.
