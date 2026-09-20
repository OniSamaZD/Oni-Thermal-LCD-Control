"""Frozen GUI entry point for Oni Thermal LCD Control."""

from multiprocessing import freeze_support
import os
from pathlib import Path

from thermalright_lcd.gui import main


if __name__ == "__main__":
    freeze_support()
    media_smoke=os.environ.get("ONI_LCD_PYAV_SMOKE_MEDIA")
    if media_smoke:
        from thermalright_lcd.playback import PyAvVideoSource
        source=PyAvVideoSource(Path(media_smoke),(320,180),loop=False,hardware_acceleration=None)
        try:
            frame=source.next_frame()
            if frame is None or frame.native_bgr is None:raise RuntimeError("frozen PyAV produced no frame")
        finally:source.close()
        raise SystemExit(0)
    raise SystemExit(main())
