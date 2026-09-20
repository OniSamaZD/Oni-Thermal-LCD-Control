from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


RUN_KEY=r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME="Oni Thermal LCD Control"


def startup_command(root:Path|None=None,start_minimized:bool=False,start_to_tray:bool=False)->str:
    """Return the per-user startup command for source or frozen builds."""
    suffix=[]
    if start_minimized:suffix.append("--start-minimized")
    if start_to_tray:suffix.append("--start-to-tray")
    if getattr(sys,"frozen",False):parts=[str(Path(sys.executable).resolve())]
    else:
        root=root or Path(__file__).resolve().parents[2]
        launcher=(root/"run-gui.bat").resolve();parts=[str(launcher)]
    return " ".join([f'"{parts[0]}"',*suffix])


class StartupManager:
    def __init__(self,registry=None):
        if registry is None:
            import winreg
            registry=winreg
        self.registry=registry
    def current_command(self)->str|None:
        r=self.registry
        try:
            with r.OpenKey(r.HKEY_CURRENT_USER,RUN_KEY,0,r.KEY_READ) as key:return r.QueryValueEx(key,VALUE_NAME)[0]
        except OSError:return None
    def enabled(self)->bool:return self.current_command() is not None
    def set_enabled(self,enabled:bool,command:str)->None:
        r=self.registry
        with r.CreateKeyEx(r.HKEY_CURRENT_USER,RUN_KEY,0,r.KEY_SET_VALUE) as key:
            if enabled:r.SetValueEx(key,VALUE_NAME,0,r.REG_SZ,command)
            else:
                try:r.DeleteValue(key,VALUE_NAME)
                except OSError:pass


def open_logs(path:Path)->None:
    path.mkdir(parents=True,exist_ok=True)
    if os.name=="nt":subprocess.Popen(["explorer.exe",str(path)])
