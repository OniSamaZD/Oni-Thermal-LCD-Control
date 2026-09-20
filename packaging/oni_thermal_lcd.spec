# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import PySide6


ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "assets" / "oni-thermal-lcd.ico"), "assets"),
    (str(ROOT / "assets" / "oni-thermal-lcd-icon.png"), "assets"),
    (str(ROOT / "assets" / "products"), "assets/products"),
]

a = Analysis(
    [str(ROOT / "packaging" / "oni_gui_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
    optimize=1,
)
# The Codex desktop host prepends its document/PDF Poppler runtime to PATH.
# PyInstaller otherwise collects Poppler's ICU 78 DLLs at application root,
# where `icuuc.dll` shadows the Windows ICU shim expected by Qt6Core and causes
# ERROR_PROC_NOT_FOUND before Python starts. They are not application
# dependencies. Also use the VC runtime shipped with the reviewed PySide wheel
# instead of the older copy beside this development interpreter.
qt_dir = Path(PySide6.__file__).resolve().parent
filtered = []
for dest, source, kind in a.binaries:
    upper_dest = dest.upper()
    source_text = str(source).lower().replace("\\", "/")
    if upper_dest in {"ICUUC.DLL", "ICUDT78.DLL"} and "/poppler/" in source_text:
        continue
    if upper_dest in {"VCRUNTIME140.DLL", "VCRUNTIME140_1.DLL"}:
        source = str(qt_dir / Path(dest).name)
    filtered.append((dest, source, kind))
a.binaries = filtered
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Oni Thermal LCD Control",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    exclude_binaries=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "oni-thermal-lcd.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=".",
)
