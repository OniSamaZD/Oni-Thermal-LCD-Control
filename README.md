# Oni Thermal LCD Control

> ## Development Preview — expect bugs
>
> **This is not a finished or stable release yet.** The project is under active development and there are still many known UI, Sensor Theme, Hardware Monitor, persistence, and LCD-deployment issues.
>
> There is currently **no public EXE or installer release** in GitHub Releases. The current public version is intended for source-based testing and development feedback.

Oni Thermal LCD Control is a Windows application for controlling supported Thermalright USB LCD displays. The project includes dual-display control, photo/video/GIF playback, customizable Sensor Themes, hardware-monitor layouts, profiles, diagnostics, performance controls, and an ONI-themed interface.

Oni Thermal LCD Control is developed and maintained by **OniSamaZD**, with assistance from **OpenAI ChatGPT and Codex** during development, testing, documentation, and iteration.

> **Important hardware note:** USB output is intentionally fail-closed. The public repository does not include machine-specific device authorization records. The application can be launched from source, but LCD writes may remain disabled until the connected device has a reviewed local authorization configuration. A simple public device-enrollment flow is not finished yet.

## Screenshots

> Screenshots show development builds and may differ from the current source while bugs and layout issues are being fixed.

### Home / dual-display workspace

![Oni Thermal LCD Control Home](docs/screenshots/home.png)

### Sensor Theme Studio

![Oni Sensor Theme Studio](docs/screenshots/sensor-themes.png)

### Hardware Monitor

![Oni Hardware Monitor](docs/screenshots/hardware-monitor.png)

## Current status

A large part of the application exists and can be tested, but **there are still many bugs and incomplete workflows**. Please do not expect a polished plug-and-play release yet.

### Known issues / unfinished work

- Sensor Theme deployment to the physical LCD is still being completed and hardened.
- **Sensor + Media** combined output needs to be restored and fully verified.
- A small floating/child preview window can appear in some Sensor Theme states.
- Moving/resizing/editing Sensor Theme elements can currently detach or break active LCD deployment in some cases.
- Hardware Monitor customization does not yet expose every supported property consistently.
- Saved Hardware Monitor layouts still need the complete **Save -> appear on Home -> select -> Play/Apply -> LCD** workflow.
- User theme/layout rename, delete, refresh, restart restore, and dual-display deployment still need additional validation.
- Some editor/runtime state transitions still need regression testing.
- Public device onboarding is not finished; the current fail-closed authorization model can prevent LCD writes on a new machine.
- There is no public stable EXE/installer release yet.

### Please report bugs

If you find a bug, please report it. Reproducible reports are especially helpful.

Useful information includes:

- display model
- USB PID if known
- Windows version
- exact steps to reproduce
- screenshot/video if useful
- expected behavior
- actual behavior

I will review reports and fix what I can as time allows. This is a community-facing open-source project, so fixes and improvements may take time.

## Supported Thermalright displays

Current device support targets:

| USB ID | Display | Current canvas / panel information |
| --- | --- | --- |
| `0416:5408` | Thermalright Trofeo Vision 9.16 LCD | Active render canvas `1920 × 462`; physical panel reports `1920 × 480` |
| `0416:5302` | Thermalright Trofeo Vision LCD 6.86 | `1280 × 480` |

Hardware revisions can differ. Support is currently tied to the exact device/transport definitions in the source.

## Community device support

I cannot personally buy and test every Thermalright LCD model or hardware revision.

Because the project is open source, the community is encouraged to contribute support for additional displays, improve compatibility, optimize performance, add features, and fix bugs.

If you add support for a new LCD or improve existing support:

1. fork the repository
2. implement and test the change
3. include the device model, USB IDs, transport details, and reproducible test information
4. open a Pull Request
5. I will review the change before deciding whether to merge it into the official repository

Please do not remove or bypass device-safety checks just to make a new model work.

## Official project vs forks

This repository is the **official Oni Thermal LCD Control repository maintained by OniSamaZD**.

Community members are welcome to:

- fork the project
- modify the source
- add features
- optimize code
- add support for additional LCDs
- fix bugs
- submit Pull Requests

Changes submitted by others do **not** automatically become part of the official project. They are reviewed before being merged.

Official releases from this repository are published by the project maintainer.

Because the project is licensed under MIT, other people may also maintain and redistribute their own modified forks under the terms of that license. Those forks or builds are **not official Oni Thermal LCD Control releases from this repository** unless explicitly identified as such here.

## What is implemented

The repository currently includes:

- Windows ONI-themed desktop UI
- Two-display workspace
- Photo playback
- Video playback
- Animated GIF playback
- Fit / Fill / Center controls
- Position, zoom, and rotation controls
- Per-display brightness controls
- Sensor Theme engine
- Data-driven `.oni-theme` format
- Visual Sensor Theme Studio/editor
- Sensor values, labels, text, images, icons, bars, gauges, graphs, clock, and date elements
- Built-in Sensor Theme templates
- User Sensor Theme save/import/export infrastructure
- Hardware Monitor / designer
- Sensor discovery/integration work
- Profiles and per-display settings
- Startup restore infrastructure
- Diagnostics
- Performance controls
- UI-lock regression protection
- Portable EXE and Inno Setup build scripts for development/release preparation

Some items above are **implemented but not yet fully reliable end-to-end**, especially Sensor Theme and Hardware Monitor deployment.

## How to run it right now

Because there is no public EXE release yet, the current preview must be run from the source code.

### 1. Download the source

On this GitHub page:

1. Click **Code**
2. Click **Download ZIP**
3. Extract the ZIP somewhere convenient, for example your Desktop or Downloads folder
4. Open the extracted `Oni-Thermal-LCD-Control` folder

You can also clone the repository with Git if you prefer.

### 2. Install Python 3.12

Install **Python 3.12 for Windows** and make sure the Python Launcher (`py`) is available.

Check it in Command Prompt:

```bat
py -3.12 --version
```

### 3. Install the required Python packages

Open Command Prompt or PowerShell inside the extracted project folder and run:

```bat
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -r requirements.txt
```

Current runtime dependencies include PySide6, Pillow, OpenCV, psutil, PyAV, and NumPy.

### 4. Start the application

The easiest way:

```text
Double-click run-gui.bat
```

Or from Command Prompt / PowerShell:

```bat
run-gui.bat
```

You can also launch it manually:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m thermalright_lcd.gui
```

### 5. Important: LCD output may still be blocked

The application deliberately does **not** ship with another person's device authorization data.

The local file:

```text
config/device-allowlist.json
```

is intentionally excluded from GitHub. The repository only contains:

```text
config/device-allowlist.example.json
```

Because of this, a new user may be able to open and test the UI but still be unable to send content to the physical LCD. **Do not disable or bypass the safety checks.** Public-friendly device enrollment/configuration is still being worked on.

## Sensor Themes

Sensor Themes are data-driven instead of being hard-coded layouts.

The current theme format can describe:

- custom position and size
- text and sensor values
- labels
- images and icons
- progress / horizontal / vertical bars
- ring and arc gauges
- line graphs
- clock and date
- colors
- fonts
- borders
- opacity
- glow/shadow styling
- sensor bindings
- thresholds and formatting
- import/export through `.oni-theme`

Built-in themes and user themes are stored separately. See [docs/sensor-themes.md](docs/sensor-themes.md) for the current format.

## For developers

The validated development environment is **Python 3.12 on Windows**.

Create a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[gui]"
```

Run the application:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m thermalright_lcd.gui
```

## Tests

From the repository root:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m unittest discover -s tests -q
py -3.12 -m pytest -q
py -3.12 tools\ui_lock.py check
```

Do not update the UI-lock baseline simply to hide an unexpected UI regression.

## Building your own EXE / installer

The repository already contains development packaging scripts, but the project does **not** currently provide a public stable binary release.

If you are developing the project yourself, see [docs/packaging.md](docs/packaging.md). The build pipeline uses PyInstaller for the portable application and Inno Setup for the Windows installer.

Typical development build commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-portable.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-installer.ps1
```

Generated output is local and is intentionally not committed to the repository.

## Troubleshooting

- **`py -3.12` is not recognized:** install Python 3.12 for Windows with the Python Launcher.
- **`run-gui.bat` says dependencies are missing:** run `py -3.12 -m pip install -r requirements.txt`.
- **The UI opens but the LCD does not accept output:** the local device authorization configuration may be missing. This is expected for the current public preview.
- **Display is not detected:** reconnect it directly to the PC, avoid problematic/unpowered hubs, and check Diagnostics.
- **Video/GIF does not play:** confirm the dependencies installed successfully and the media file can be read by PyAV/OpenCV.
- **A second app launch exits:** the application uses single-instance behavior and should restore the existing instance.
- **Sensor Theme behaves incorrectly after editing:** this is a known development issue; please report reproducible steps.

## License

Oni Thermal LCD Control is released under the [MIT License](LICENSE).

Third-party components keep their own licenses. See `THIRD_PARTY_NOTICES.md` for additional notices.
