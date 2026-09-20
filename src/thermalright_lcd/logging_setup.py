from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(base: Path) -> Path:
    """Bounded application diagnostics; media and USB payloads are never logged."""
    base=Path(base);base.mkdir(parents=True,exist_ok=True);path=base/"oni-thermal-lcd.log"
    root=logging.getLogger("thermalright_lcd")
    if not root.handlers:
        handler=RotatingFileHandler(path,maxBytes=1_000_000,backupCount=3,encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler);root.setLevel(logging.INFO)
    return path
