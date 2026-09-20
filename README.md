# Oni Thermal LCD Control

Oni Thermal LCD Control is a Windows desktop application for configuring and driving supported Thermalright USB LCD displays. It provides dual-display control, photo/video/GIF playback, sensor themes, profiles, hardware monitoring, performance controls, and diagnostics in an ONI-themed interface.

> **Safety:** USB output is fail-closed. A display must match a locally reviewed authorization entry before the application can send generated media. The public source distribution does not include machine-specific authorization records.

## Screenshots

<!-- Add release screenshots here after final visual approval. -->

- Home / dual-display workspace: `docs/screenshots/home.png`
- Sensor theme gallery: `docs/screenshots/sensor-themes.png`
- Hardware monitor designer: `docs/screenshots/hardware-monitor.png`

## Supported displays

Current support targets these Thermalright USB product IDs:

| USB ID | Display |
| --- | --- |
| `0416:5408` | Trofeo Vision 9.16 LCD, 1920 × 480 |
| `0416:5302` | Trofeo Vision LCD / 6.86 LCD, 1280 × 480 |

Hardware revisions can differ. Confirm the detected device in Diagnostics and keep output disabled until the exact unit has been reviewed.

## Features

- Independent or synchronized control of two supported LCDs
- Photo, video, and animated GIF playback with fit, fill, position, zoom, and rotation controls
- Sensor-theme gallery and editable hardware-monitor layouts
- Reusable profiles and per-display settings
- Startup restore, tray operation, brightness, performance, and diagnostics controls
- Strict per-device authorization gates for USB writes
- Portable Windows build with no separate Python installation required

## Install on Windows

### Installer

1. Download `Oni-Thermal-LCD-Control-Setup.exe` from the release assets.
2. Run the installer and follow the prompts.
3. Choose whether to create the optional desktop shortcut.
4. Launch **Oni Thermal LCD Control** from the Start Menu.

The installer defaults to Program Files and registers a standard uninstaller. Uninstalling the application leaves user-created settings and profiles under `%LOCALAPPDATA%\OniThermalLcd` intact.

### Portable build

Download and extract the complete portable archive, then run `Oni Thermal LCD Control.exe`. Keep the `_internal` directory beside the executable. Portable means no Python installation is required; application settings still use `%LOCALAPPDATA%\OniThermalLcd`.

## Development setup

The validated development runtime is **Python 3.12 on Windows**.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[gui]"
```

Alternatively, install the minimum runtime list with `py -3.12 -m pip install -r requirements.txt`.

The local `config/device-allowlist.json` is intentionally not versioned because it contains machine-specific hardware identifiers. Start from `config/device-allowlist.example.json`; do not enable write authorization unless the device and transport have been independently validated.

## Run from source

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m thermalright_lcd.gui
```

You can also double-click `run-gui.bat`. The safe smoke mode is `run-gui.bat --smoke-test`.

## Tests

Run the complete validation from the repository root:

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m unittest discover -s tests -q
py -3.12 -m pytest -q
py -3.12 tools\ui_lock.py check
```

Never update the UI-lock baseline simply to silence an unexpected visual change.

## Build release artifacts

Install the development dependencies, PyInstaller, and Inno Setup 6, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-portable.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-installer.ps1
```

The portable application is written to `dist\`. The installer is written to `dist-installer\Oni-Thermal-LCD-Control-Setup.exe`. See `docs/packaging.md` for packaging details.

## Troubleshooting

- **Display is not listed:** reconnect it directly to the PC, avoid unpowered hubs, and check the Diagnostics page.
- **Output remains disabled:** this is expected until the exact device has a reviewed local authorization entry. Do not bypass the safety gate.
- **Media will not play:** install the `gui` dependency group for source runs and confirm the file is readable by FFmpeg/PyAV.
- **A second launch exits:** the first instance is restored because the application uses single-instance behavior.
- **Settings need inspection:** logs and settings are stored below `%LOCALAPPDATA%\OniThermalLcd`.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Device transport changes require reproducible evidence and must preserve all authorization and safety gates.

## License

Oni Thermal LCD Control is released under the [MIT License](LICENSE). Third-party components retain their own licenses; packaged builds include `THIRD_PARTY_NOTICES.md` and the corresponding license texts.
