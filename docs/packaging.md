# Windows packaging

## Status

The reproducible portable build is based on Python 3.12 and PyInstaller 6.22.
It creates a flat portable directory headed by
`dist/Oni Thermal LCD Control.exe`, embeds the application icon and
Windows version resource, and places third-party notices beside the executable.
It does not install, replace, or configure any USB driver. USBPcap, Wireshark,
TRCC, and a system Python are not runtime dependencies.

The executable carries the reviewed public device and lifecycle definitions in
the application source, plus the project license and ONI icon assets. Private
machine allowlists, captures, diagnostic reports, test media, logs, and
developer tools are not bundled.

An initial prototype failed before application startup with QtCore
`ERROR_PROC_NOT_FOUND`. Automated PE import/export comparison identified the
cause: the Codex desktop host's PATH exposed Poppler ICU 78 DLLs, PyInstaller
collected them at application root, and that unrelated `icuuc.dll` shadowed the
Windows ICU shim Qt6Core expects. The spec now excludes only those
Poppler-origin DLLs and selects the reviewed PySide wheel's matching VC runtime.
The rebuilt flat onedir artifact passes frozen startup/clean-exit smoke tests.
The flat format remains preferred because it is inspectable and better preserves
LGPL library replacement/relinking rights. The entire `dist` directory is the
portable app; the EXE must not be separated from `_internal` or its DLLs.

## Reproducible build

From a regular, non-elevated PowerShell prompt in the repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build-portable.ps1
```

The script requires the pinned build interpreter (`py -3.12`) and checks all
runtime/build imports before doing any work. It runs the complete regression
suite unless `-SkipTests` is explicitly supplied, regenerates the deterministic
multi-resolution icon, cleans only the repository-local PyInstaller work path
and previous executable, builds with UPX disabled, emits size and SHA-256, and
collects installed wheel license files into `dist/third-party-licenses`, and
requires one frozen smoke run to exit successfully before reporting success.

The PyInstaller specification is the authoritative manifest. Build results can
vary when Python or wheel versions differ. A release pipeline should create a
fresh virtual environment from a reviewed lock file and record `pip freeze`, the
Windows SDK/toolchain version, executable hash, and Authenticode signature.
The current development artifact is unsigned.

## Startup and package benchmark

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/benchmark-portable.ps1
```

The harness launches each existing candidate with the GUI's safe
750 ms smoke-test exit. It records artifact size, SHA-256, elapsed startup,
peak process-tree working set, handles, and threads in
`analysis/packaging-benchmark.json`. The GUI smoke path does not press Play and
does not issue USB endpoint writes.

The validated 2026-08-27 three-run artifact has SHA-256
`9e0ff7c780ba05082414a78738d8bb2748a623eee7bc96cd6d9f0c873684a7e0`.
Its 5.67 MB launcher heads a 293.0 MB / 303-file portable directory. Median safe-smoke elapsed
time was 2.137 seconds and median peak process-tree working set was 159.0 MB.
That short startup peak includes native Qt/OpenCV DLL loading and is distinct
from the settled source/offscreen dual-static measurement; visible packaged
steady-state profiling remains a release acceptance item.

PyInstaller was selected for the first artifact because version 6.22 was already
installed and has maintained PySide6 hooks. Nuitka was not installed, so inventing
Nuitka measurements would be misleading. The benchmark script automatically
adds `dist-nuitka/Oni Thermal LCD Control.exe` when a future reviewed Nuitka
build exists, allowing a same-host comparison. Selection for release should use
measured cold startup, steady working set, artifact size, compatibility, build
time, and license/relinking requirements—not compiler branding alone.

## Licensing and redistribution gate

Runtime dependency inventory at the time this pipeline was created:

| Component | Observed version | License reported by wheel metadata |
|---|---:|---|
| PySide6 / Essentials / Addons / shiboken6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| Pillow | 12.2.0 | MIT-CMU |
| psutil | 5.9.8 | BSD-3-Clause |
| opencv-python | 5.0.0.93 | Apache-2.0 |
| NumPy | 2.2.6 | BSD-3-Clause plus bundled-library notices |
| PyInstaller | 6.22.0 | GPL-2.0-or-later with its bootloader exception |

This is an engineering inventory, not legal advice. Before public redistribution:

1. Review the exact wheels in the release environment and preserve their notices.
2. Satisfy Qt/PySide LGPL requirements, including the applicable license text,
   source/relinking offer and replacement rights. A one-file extractor may be
   less convenient for LGPL relinking than an onedir distribution; legal review
   should decide the release format.
3. Review OpenCV's wheel contents and codec availability. No separate FFmpeg
   executable is bundled by this pipeline.
4. Ship `THIRD_PARTY_NOTICES.md` and `third-party-licenses` with the EXE.
5. Do not package Thermalright binaries, USBPcap, Wireshark, or any driver.

## Installer

The Inno Setup 6 installer packages the already-built `dist` directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build-installer.ps1
```

It defaults to Program Files, creates a Start Menu shortcut, offers an optional
desktop shortcut, and registers a standard uninstaller. It does not install or
replace display drivers, and uninstall deliberately preserves user settings and
profiles under `%LOCALAPPDATA%\OniThermalLcd`.

`packaging/smoke-installer.ps1` performs a temporary current-user acceptance
test covering install, both shortcuts, installed launch, uninstall, shortcut
cleanup, and settings preservation. The release uses public reviewed transport
definitions and discovers the current machine's instance/container/path
read-only at runtime. Machine-specific identifiers are not published or required.

## Safe validation

The build smoke test is intentionally short and interaction-free. It validates
that Qt plugins, image codecs, reviewed runtime definitions, settings/log paths,
and the frozen entry point initialize, then requests a clean application exit.
It is not a physical playback test and cannot prove USB behavior. A normal EXE
launch likewise does not open either LCD; device handles are opened only after
the user presses Play through the validated DisplaySession layer.
