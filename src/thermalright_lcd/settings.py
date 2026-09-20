from __future__ import annotations

import json
import os
from dataclasses import asdict,dataclass,field
from pathlib import Path


@dataclass
class DisplayProfile:
    media:str="";fit_mode:str="Fit";rotation:int=0;fps:str="Auto";playing:bool=False
    pan_x:int=0;pan_y:int=0;zoom:float=1.0;quality:str="Balanced";brightness:int=100
    desired_playback_state:str=""
    output_mode:str="media";sensor_template:str="";preview_scale:int=100;media_type:str=""
    media_by_type:dict[str,str]=field(default_factory=dict)

@dataclass
class AppSettings:
    start_minimized:bool=False;close_to_tray:bool=True;close_button_behavior:str="minimize_to_tray";start_with_windows:bool=False
    minimize_to_tray:bool=False;restore_previous_media:bool=True;auto_reconnect:bool=True
    remember_window_position:bool=True;default_fps:str="Auto";default_display_mode:str="Fit";stale_frame_dropping:bool=True;resume_playback:bool=True
    hardware_decode:bool=False
    performance_mode:str="Normal";sensor_interval_ms:int=500
    last_media_directory:str=""
    media_library:list[str]=field(default_factory=list)
    sensor_favorites:list[str]=field(default_factory=list)
    recent_sensors:list[str]=field(default_factory=list)
    monitor_layouts:dict[str,dict[str,dict]]=field(default_factory=dict)
    monitor_layout_library:dict[str,dict[str,dict]]=field(default_factory=dict)
    designer_geometry:list[int]=field(default_factory=list)
    window_geometry:list[int]=field(default_factory=list)
    window_maximized:bool=False
    sidebar_expanded:bool=True
    display_layout:str="stacked"
    display_order:list[str]=field(default_factory=lambda:["0416:5408","0416:5302"])
    splitter_sizes:list[int]=field(default_factory=list)
    preview_scales:dict[str,int]=field(default_factory=lambda:{"0416:5408":100,"0416:5302":100})
    advanced_expanded:dict[str,bool]=field(default_factory=dict)
    active_profile:str="Default"
    display_sync:bool=False
    unified_sync_view:bool=False
    link_brightness:bool=False
    output_modes:dict[str,str]=field(default_factory=lambda:{"0416:5408":"stopped","0416:5302":"stopped"})
    monitor_templates:dict[str,str]=field(default_factory=dict)
    sensor_theme_ids:dict[str,str]=field(default_factory=dict)
    sensor_theme_fps:dict[str,int]=field(default_factory=lambda:{"0416:5408":2,"0416:5302":2})
    profiles:dict[str,dict[str,DisplayProfile]]=field(default_factory=lambda:{"Default":{"0416:5408":DisplayProfile(),"0416:5302":DisplayProfile()}})

class SettingsStore:
    def __init__(self,path:Path):self.path=Path(path)
    def load(self)->AppSettings:
        try:return self._load()
        except (OSError,UnicodeError,json.JSONDecodeError,TypeError,ValueError,AttributeError):return AppSettings()
    def _load(self)->AppSettings:
        if not self.path.exists():return AppSettings()
        raw=json.loads(self.path.read_text(encoding="utf-8"));profiles={}
        for name,devices in raw.get("profiles",{}).items():
            profiles[name]={}
            for pid,value in devices.items():
                value=dict(value)
                if str(value.get("fps","")).strip()=="0.2":value["fps"]="0.1"
                profiles[name][pid]=DisplayProfile(**value)
        known={k:raw.get(k,getattr(AppSettings(),k)) for k in (
            "start_minimized","close_to_tray","close_button_behavior","start_with_windows","minimize_to_tray",
            "restore_previous_media","auto_reconnect","remember_window_position","default_fps","default_display_mode","stale_frame_dropping",
            "resume_playback","hardware_decode","performance_mode","sensor_interval_ms","last_media_directory","media_library","sensor_favorites","recent_sensors","monitor_layouts","monitor_layout_library","designer_geometry","window_geometry","window_maximized","sidebar_expanded","display_layout","display_order","splitter_sizes","preview_scales","advanced_expanded","active_profile","display_sync","unified_sync_view","link_brightness","output_modes","monitor_templates","sensor_theme_ids","sensor_theme_fps")}
        if known["display_layout"] not in {"side_by_side","stacked"}:known["display_layout"]="stacked"
        if sorted(known["display_order"])!=["0416:5302","0416:5408"]:known["display_order"]=["0416:5408","0416:5302"]
        # Old builds persisted the former false-by-default checkbox even when
        # the user never selected an exit policy. The new explicit preference
        # therefore defaults safely to tray unless the new key is present.
        behavior=raw.get("close_button_behavior","minimize_to_tray")
        if behavior not in {"minimize_to_tray","exit_application"}:behavior="minimize_to_tray"
        known["close_button_behavior"]=behavior;known["close_to_tray"]=behavior=="minimize_to_tray"
        if str(known["default_fps"]).strip()=="0.2":known["default_fps"]="0.1"
        known["profiles"]=profiles or AppSettings().profiles
        return AppSettings(**known)
    def save(self,value:AppSettings):
        self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix(self.path.suffix+".tmp")
        tmp.write_text(json.dumps(asdict(value),indent=2),encoding="utf-8");os.replace(tmp,self.path)
