import unittest
from pathlib import Path
from thermalright_lcd.modes import MODES,resource_mode
from thermalright_lcd.startup import StartupManager,startup_command,VALUE_NAME

class Key:
    def __init__(self,r):self.r=r
    def __enter__(self):return self
    def __exit__(self,*_):pass
class Registry:
    HKEY_CURRENT_USER=1;KEY_READ=2;KEY_SET_VALUE=4;REG_SZ=1
    def __init__(self):self.values={}
    def OpenKey(self,*_):
        if VALUE_NAME not in self.values:raise OSError()
        return Key(self)
    def CreateKeyEx(self,*_):return Key(self)
    def QueryValueEx(self,key,name):return self.values[name],self.REG_SZ
    def SetValueEx(self,key,name,zero,kind,value):self.values[name]=value
    def DeleteValue(self,key,name):
        if name not in self.values:raise OSError()
        del self.values[name]

class StartupModeTests(unittest.TestCase):
    def test_per_user_startup_is_idempotent_and_removable(self):
        r=Registry();m=StartupManager(r);cmd=startup_command(Path("C:/App"),True,True);self.assertFalse(m.enabled());m.set_enabled(True,cmd);m.set_enabled(True,cmd);self.assertEqual(m.current_command(),cmd);m.set_enabled(False,cmd);self.assertFalse(m.enabled())
    def test_modes_are_bounded_and_game_mode_is_conservative(self):
        self.assertIn("Game Mode",MODES);g=resource_mode("Game Mode");self.assertFalse(g.preview_when_hidden);self.assertGreaterEqual(g.sensor_interval_ms,1000);self.assertEqual(g.log_level,"WARNING")
