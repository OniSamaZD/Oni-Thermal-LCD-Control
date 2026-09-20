#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "src" / "thermalright_lcd" / "gui.py"
BASELINE = ROOT / "ui_lock_baseline.json"

PROTECTED = [
    ("PreviewLabel", "__init__"),
    ("PreviewLabel", "sizeHint"),
    ("PreviewLabel", "minimumSizeHint"),
    ("MediaLibraryDialog", "__init__"),
    ("SettingsDialog", "__init__"),
    ("HardwareMonitorDialog", "__init__"),
    ("ProfileManagerDialog", "__init__"),
    ("DisplayCard", "__init__"),
    ("DisplayCard", "_fit_side_by_side_preview"),
    ("DisplayCard", "sizeHint"),
    ("DisplayCard", "set_layout_mode"),
    ("DisplayCard", "resizeEvent"),
    ("MainWindow", "__init__"),
    ("MainWindow", "set_display_layout"),
    ("MainWindow", "swap_display_order"),
    ("MainWindow", "toggle_sidebar"),
    ("MainWindow", "set_sidebar_expanded"),
    ("MainWindow", "select_page"),
    ("MainWindow", "_action_page"),
    ("MainWindow", "_hardware_monitor_page"),
    ("MainWindow", "_performance_page"),
    ("MainWindow", "_settings_page"),
    ("MainWindow", "_diagnostics_page"),
]

def normalize_block(s: str) -> str:
    lines = [line.rstrip() for line in s.replace("\r\n","\n").replace("\r","\n").split("\n")]
    return "\n".join(lines).rstrip() + "\n"

def extract_class_method(text: str, cls: str, method: str) -> str:
    lines = text.splitlines(True)
    class_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^class\s+{re.escape(cls)}\b", line):
            class_idx = i
            break
    if class_idx is None:
        raise RuntimeError(f"class not found: {cls}")

    class_end = len(lines)
    for i in range(class_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip(" ")) == 0:
            class_end = i
            break

    method_idx = None
    pat = re.compile(rf"^    (?:async\s+)?def\s+{re.escape(method)}\s*\(")
    for i in range(class_idx + 1, class_end):
        if pat.match(lines[i]):
            method_idx = i
            break
    if method_idx is None:
        raise RuntimeError(f"method not found: {cls}.{method}")

    method_end = class_end
    for i in range(method_idx + 1, class_end):
        line = lines[i]
        if not line.strip():
            continue
        if re.match(r"^    (?:async\s+def|def|class)\s+", line) or re.match(r"^    @", line):
            method_end = i
            break

    return normalize_block("".join(lines[method_idx:method_end]))

def extract_style(text: str) -> str:
    m = re.search(r'(?m)^STYLE\s*=\s*"""', text)
    if not m:
        raise RuntimeError("STYLE start not found")
    start = m.start()
    qstart = text.find('"""', m.start())
    qend = text.find('"""', qstart + 3)
    if qend < 0:
        raise RuntimeError("STYLE closing quote not found")
    return normalize_block(text[start:qend+3])

def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def current_contract():
    text = GUI.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n")
    protected = {}
    for cls, method in PROTECTED:
        protected[f"{cls}.{method}"] = sha(extract_class_method(text, cls, method))
    protected["STYLE"] = sha(extract_style(text))
    return {
        "schema": 2,
        "algorithm": "source-block-sha256-v1",
        "approved_gui_sha256": hashlib.sha256(GUI.read_bytes()).hexdigest(),
        "protected": protected,
    }

def check():
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = current_contract()
    changed = [name for name, wanted in expected["protected"].items()
               if current["protected"].get(name) != wanted]
    if changed:
        print("UI LOCK: FAIL")
        print("Protected UI changed without updating the approved baseline:")
        for name in changed:
            print(f"  - {name}")
        print()
        print("Do NOT update the baseline unless the user explicitly approved a UI change.")
        return 1
    print("UI LOCK: PASS - approved interface contract unchanged.")
    return 0

def record():
    data = current_contract()
    BASELINE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("UI LOCK baseline updated.")
    print("New gui.py SHA256:", data["approved_gui_sha256"])
    return 0

if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "check"
    if cmd == "check":
        raise SystemExit(check())
    if cmd == "record":
        raise SystemExit(record())
    print("Usage: python tools/ui_lock.py [check|record]")
    raise SystemExit(2)
