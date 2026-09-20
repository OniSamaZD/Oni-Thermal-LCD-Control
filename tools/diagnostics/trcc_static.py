from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(r"C:\Program Files\TRCCCAP")
TERMS = re.compile(r"0416|5408|5302|1920|1280|462|480|jpeg|jfif|winusb|libusb|hid|endpoint|bulk|interrupt|usb", re.I)
ASCII = re.compile(rb"[\x20-\x7e]{4,}")
UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")


def strings(data: bytes):
    for m in ASCII.finditer(data):
        yield m.start(), m.group().decode("ascii", "replace")
    for m in UTF16.finditer(data):
        yield m.start(), m.group()[::2].decode("ascii", "replace")


def main() -> int:
    files, hits = [], []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append({"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        for offset, value in strings(data):
            if TERMS.search(value):
                hits.append({"file": str(path), "offset": offset, "string": value[:500]})
    candidates = []
    for base in filter(None, (os.getenv("APPDATA"), os.getenv("LOCALAPPDATA"), os.getenv("PROGRAMDATA"))):
        root = Path(base)
        for pattern in ("TRCC*", "Thermalright*", "*TRCCCAP*"):
            for p in root.glob(pattern):
                candidates.append(str(p))
    out = {"mode": "read-only", "install_root": str(ROOT), "files": files, "matching_strings": hits,
           "configuration_candidates": sorted(set(candidates))}
    target = Path("analysis/trcc-static.json")
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"files": len(files), "hits": len(hits), "configuration_candidates": out["configuration_candidates"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
