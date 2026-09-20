# Oni Thermal LCD Control

> ## Development Preview
>
> **Oni Thermal LCD Control is still under active development. Expect bugs and incomplete workflows.**
>
> There is currently **no public stable EXE or installer release**. The repository is public for source-based testing, development feedback, and community contributions.

Oni Thermal LCD Control is a Windows application for supported Thermalright USB LCD displays, with dual-display control, photo/video/GIF playback, customizable Sensor Themes, hardware-monitor layouts, profiles, diagnostics, performance controls, and an ONI-themed interface.

Developed and maintained by **OniSamaZD**, with assistance from **OpenAI ChatGPT and Codex** during development, testing, documentation, and iteration.

## Screenshots

### Home / dual-display workspace

![Oni Thermal LCD Control Home](docs/screenshots/home.png)

### Sensor Theme Studio

![Oni Sensor Theme Studio](docs/screenshots/sensor-themes.png)

### Hardware Monitor

![Oni Hardware Monitor](docs/screenshots/hardware-monitor.png)

> Screenshots are from development builds and may change while bugs and layout issues are fixed.

## What currently works

- ONI-themed Windows desktop UI
- Two-display workspace
- Photo, video, and animated GIF playback
- Fit / Fill / Center
- Position, zoom, and rotation controls
- Per-display brightness
- Data-driven Sensor Theme engine
- Visual Sensor Theme Studio/editor
- Text, sensor values, labels, images, icons, bars, gauges, graphs, clock, and date elements
- Built-in and user-created Sensor Themes
- `.oni-theme` import/export infrastructure
- Hardware Monitor / designer
- Profiles and per-display settings
- Diagnostics and performance controls
- Startup restore infrastructure
- Portable EXE and Inno Setup build pipeline for development

Some of these features are implemented but are **not yet fully reliable end-to-end**.

## Known issues

The project currently still has several important bugs and incomplete workflows:

- Sensor Theme deployment to the physical LCD still needs more hardening.
- **Sensor + Media** combined output needs to be restored and fully verified.
- A small floating/child preview window can appear in some Sensor Theme states.
- Editing/moving/resizing Sensor Theme elements can break or detach an active LCD deployment in some cases.
- Hardware Monitor customization does not yet expose every supported property consistently.
- Saved Hardware Monitor layouts still need the complete **Save -> Home -> Select -> Play/Apply -> LCD** workflow.
- Theme/layout rename, delete, refresh, restart restore, and dual-display deployment still need more validation.
- Public device onboarding is not finished, so LCD output may stay blocked on a new machine.
- There is no public stable EXE/installer release yet.

If you find a bug, **please report it**. Reproducible reports help a lot. I will review reports and fix what I can as time allows.

Useful bug-report information:

- display model
- USB PID if known
- Windows version
- exact steps to reproduce
- screenshot or video
- expected behavior
- actual behavior

## Currently implemented / tested device definitions

| USB ID | Display | Render / panel information |
| --- | --- | --- |
| `0416:5408` | Thermalright Trofeo Vision 9.16 LCD | Active render canvas `1920 × 462`; physical panel reports `1920 × 480` |
| `0416:5302` | Thermalright Trofeo Vision LCD 6.86 | `1280 × 480` |

For the 9.16-inch device, the app uses a `1920 × 462` active render region while the physical panel reports `1920 × 480`; the device protocol excludes 18 rows.

Hardware revisions can differ, and support is tied to the exact device/transport definitions in the source.

## How to run it right now

Because there is no public binary release yet, the current preview must be run from source.

### 1. Download the source

On GitHub:

1. Click **Code**
2. Click **Download ZIP**
3. Extract the ZIP
4. Open the extracted `Oni-Thermal-LCD-Control` folder

You can also clone the repository with Git.

### 2. Install Python 3.12

Install **Python 3.12 for Windows** with the Python Launcher.

Check it:

```bat
py -3.12 --version
```

### 3. Install dependencies

Open Command Prompt or PowerShell inside the project folder:

```bat
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -r requirements.txt
```

### 4. Start the app

The easiest way is:

```text
Double-click run-gui.bat
```

Or:

```bat
run-gui.bat
```

Manual launch:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m thermalright_lcd.gui
```

## Important hardware / authorization note

The public repository intentionally does **not** include machine-specific device authorization records.

The local file:

```text
config/device-allowlist.json
```

is excluded from GitHub. The repository only includes:

```text
config/device-allowlist.example.json
```

So a new user may be able to open and test the UI while physical LCD output remains blocked.

**Do not disable or bypass the safety checks.** A simpler public device-enrollment/configuration flow is still being developed.

## Sensor Themes

Sensor Themes are data-driven rather than hard-coded layouts.

The current format supports:

- custom position and size
- text and sensor values
- labels
- images and icons
- progress, horizontal, and vertical bars
- ring and arc gauges
- line graphs
- clock and date
- colors, fonts, borders, opacity, glow, and shadows
- sensor bindings
- thresholds and formatting
- `.oni-theme` import/export

See [docs/sensor-themes.md](docs/sensor-themes.md) for format details.

## Community contributions

I cannot personally buy and test every Thermalright LCD model or hardware revision.

Because the project is open source, contributions are welcome for:

- additional Thermalright LCD support
- bug fixes
- compatibility improvements
- performance optimizations
- new features
- Sensor Theme improvements

For a new LCD or hardware revision:

1. fork the repository
2. implement and test the change
3. document the device model, USB IDs, transport details, and test results
4. open a Pull Request
5. I will review it before deciding whether to merge it into the official repository

Please do not remove or bypass device-safety checks just to make a new model work.

## Official repository and forks

This is the **official Oni Thermal LCD Control repository maintained by OniSamaZD**.

Community members may fork, modify, optimize, extend, and redistribute the project under the MIT License.

Changes from forks do **not** automatically become part of the official project. Pull Requests are reviewed before merging.

Official releases from this repository are published by the project maintainer. Modified third-party forks/builds are not official Oni Thermal LCD Control releases unless explicitly identified as such here.

## Developer notes

Validated development environment: **Python 3.12 on Windows**.

Run tests:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m unittest discover -s tests -q
py -3.12 -m pytest -q
py -3.12 tools\ui_lock.py check
```

Do not update the UI-lock baseline just to hide an unexpected UI regression.

Advanced packaging details are in [docs/packaging.md](docs/packaging.md).

Development build commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-portable.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-installer.ps1
```

Generated binaries are local build artifacts and are intentionally not committed to the repository.

## License

Oni Thermal LCD Control is released under the [MIT License](LICENSE).

Third-party components retain their own licenses. See `THIRD_PARTY_NOTICES.md` for additional notices.
