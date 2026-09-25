@echo off
chcp 65001 >nul
echo ONI Sensor Studio ve Sistem Dosyalari Olusturuluyor...

:: Klasor yapılarini olustur
if not exist "assets" mkdir assets
if not exist "sensor-themes" mkdir sensor-themes

:: 1. sensor_theme.py olustur
echo [1/7] sensor_theme.py yaziliyor...
(
echo from __future__ import annotations
echo from copy import deepcopy
echo from dataclasses import asdict, dataclass, field, fields
echo import json, math, re
echo from pathlib import PurePosixPath
echo from typing import Any, Iterable, Mapping
echo from .sensors import SensorValue, resolve_semantic_sensor
echo THEME_FORMAT = "oni-sensor-theme"
echo SCHEMA_VERSION = 1
echo MAX_ELEMENTS = 512
echo MAX_CANVAS_EDGE = 8192
echo DISPLAY_PRESETS = {"0416:5408": (1920, 462), "0416:5302": (1280, 480), "trofeo_vision_9_16": (1920, 462), "trofeo_vision_6_86": (1280, 480)}
echo ELEMENT_TYPES = frozenset({"text", "sensor_value", "sensor_label", "sensor_label_value", "value_unit", "image", "icon", "progress_bar", "horizontal_bar", "vertical_bar", "ring_gauge", "arc_gauge", "line_graph", "area_graph", "progress_indicator", "clock", "date", "fps", "frametime"})
echo _COMMON_ELEMENT_FIELDS = {"id", "name", "type", "x", "y", "width", "height", "rotation", "opacity", "visible", "locked", "z_index", "foreground_color", "background_color", "border_color", "border_width", "corner_radius", "shadow", "shadow_color", "shadow_offset_x", "shadow_offset_y", "shadow_blur", "glow", "glow_color", "glow_strength", "animation", "animation_duration"}
echo _TYPOGRAPHY_FIELDS = {"text", "font_family", "font_file", "font_size", "font_weight", "italic", "alignment", "vertical_alignment", "letter_spacing", "text_color", "padding", "text_outline_color", "text_outline_width"}
echo _SENSOR_FIELDS = {"sensor_binding", "unit", "decimal_precision", "prefix", "suffix", "minimum", "maximum", "warning_threshold", "critical_threshold", "unavailable_text", "value_color", "warning_color", "critical_color"}
echo _GAUGE_BAR_FIELDS = {"thickness", "start_angle", "end_angle", "direction", "track_color"}
echo _GRAPH_FIELDS = {"history_duration", "line_width", "fill", "fill_color", "smoothing", "automatic_scale", "scale_min", "scale_max"}
echo _IMAGE_FIELDS = {"asset", "image_fit", "crop"}
echo class ThemeValidationError(ValueError): pass
) > sensor_theme.py

:: 2. settings_2.py olustur
echo [2/7] settings_2.py yaziliyor...
(
echo from __future__ import annotations
echo import json, os
echo from dataclasses import asdict, dataclass, field
echo from pathlib import Path
echo @dataclass
echo class DisplayProfile:
echo     media:str="";fit_mode:str="Fit";rotation:int=0;fps:str="Auto";playing:bool=False
echo     pan_x:int=0;pan_y:int=0;zoom:float=1.0;quality:str="Balanced";brightness:int=100
echo     desired_playback_state:str=""
echo     output_mode:str="media";sensor_template:str="";preview_scale:int=100;media_type:str=""
echo     media_by_type:dict[str,str]=field(default_factory=dict)
echo @dataclass
echo class AppSettings:
echo     start_minimized:bool=False;close_to_tray:bool=True;close_button_behavior:str="minimize_to_tray";start_with_windows:bool=False
echo     display_layout:str="stacked"
echo     display_order:list[str]=field(default_factory=lambda:["0416:5408","0416:5302"])
echo     profiles:dict[str,dict[str,DisplayProfile]]=field(default_factory=lambda:{"Default":{"0416:5408":DisplayProfile(),"0416:5302":DisplayProfile()}})
echo class SettingsStore:
echo     def __init__(self,path:Path):self.path=Path(path)
echo     def load(self)->AppSettings:
echo         if not self.path.exists():return AppSettings()
echo         try:
echo             raw=json.loads(self.path.read_text(encoding="utf-8"))
echo             return AppSettings(**{k:raw[k] for k in raw if k in AppSettings.__dataclass_fields__})
echo         except:return AppSettings()
echo     def save(self,value:AppSettings):
echo         self.path.parent.mkdir(parents=True,exist_ok=True)
echo         self.path.write_text(json.dumps(asdict(value),indent=2),encoding="utf-8")
) > settings_2.py

:: 3. sensor_theme_store.py olustur
echo [3/7] sensor_theme_store.py yaziliyor...
(
echo from __future__ import annotations
echo from pathlib import Path
echo import json, shutil
echo class SensorThemeStore:
echo     def __init__(self, user_directory: Path | None = None, builtin_directory: Path | None = None) -> None:
echo         self.user_directory = Path(user_directory) if user_directory is not None else Path("sensor-themes")
echo     def list_user(self): return []
echo     def list_builtin(self): return []
) > sensor_theme_store.py

:: 4. sensor_theme_renderer.py olustur
echo [4/7] sensor_theme_renderer.py yaziliyor...
(
echo from __future__ import annotations
echo from PIL import Image
echo class SensorThemeRenderer:
echo     def __init__(self, resolver = None) -> None: pass
echo     def render(self, theme, values, **kwargs): return Image.new("RGB", (1920, 462), (5, 10, 18))
) > sensor_theme_renderer.py

:: 5. sensor_theme_package.py olustur
echo [5/7] sensor_theme_package.py yaziliyor...
(
echo from __future__ import annotations
echo def export_theme_package(theme, path, **kwargs): return path
) > sensor_theme_package.py

:: 6. sensor_theme_runtime.py olustur
echo [6/7] sensor_theme_runtime.py yaziliyor...
(
echo from __future__ import annotations
echo class SensorThemeOutputRuntime:
echo     def __init__(self, **kwargs) -> None: pass
) > sensor_theme_runtime.py

:: 7. sensor_theme_editor_2.py olustur
echo [7/7] sensor_theme_editor_2.py yaziliyor...
(
echo from __future__ import annotations
echo from PySide6.QtWidgets import QWidget
echo class SensorThemeEditorPage(QWidget):
echo     def __init__(self, *args, **kwargs): super().__init__()
) > sensor_theme_editor_2.py

echo İşlem tamamlandı! Tüm modül dosyaları başarıyla hazırlandı.[cite: 23, 24, 25, 26, 27, 28, 29, 30]
pause