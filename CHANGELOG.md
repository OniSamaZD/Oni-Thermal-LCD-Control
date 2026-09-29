# Changelog

All notable changes to Oni Thermal LCD Control are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning.

## [Unreleased]

### Added

- MIT open-source release documentation and reproducible Windows installer pipeline.
- ONI-themed startup splash screen using the existing application brand assets.

## [0.1.1] - 2026-09-28

### Changed

- Made startup device discovery asynchronous so the application shell appears immediately.
- Replaced normal GUI PowerShell/CIM discovery with much faster native Windows metadata and SCSI enumeration.
- Improved discovery, rescan, physical-identity, and per-display session reliability.
- Corrected Side-by-Side sizing on smaller windows while preserving preview aspect ratios.
- Improved playback scheduling and bounded static-content caching stability.
- Completed extended native-discovery, lifecycle, dual-display output, responsive-layout, and regression validation.

### Notes

- Physical output remains verified on `0416:5302` and `0416:5408`; other community-device paths remain Experimental until validated on their hardware.

## [0.1.0] - 2026-09-19

### Added

- Dual Thermalright LCD workspace for USB IDs `0416:5408` and `0416:5302`.
- Photo, video, GIF, sensor-theme, profile, hardware-monitor, performance, settings, and diagnostics workflows.
- Fail-closed per-device authorization and captured-frame transport validation.
- ONI dark navy and electric-blue application theme.
- PyInstaller portable Windows build.
