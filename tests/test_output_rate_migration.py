import json
from pathlib import Path
from thermalright_lcd.output_rate import RATE_LABELS,resolve_output_rate
from thermalright_lcd.settings import SettingsStore

def test_retired_point_two_is_not_exposed_and_normalizes():
    assert "0.2" not in RATE_LABELS
    assert resolve_output_rate("0.2","0416:5302",animated=False).label == "0.1"

def test_old_settings_point_two_migrates(tmp_path:Path):
    path=tmp_path/"settings.json"
    path.write_text(json.dumps({"default_fps":"0.2","profiles":{"Default":{"0416:5408":{"fps":"0.2"},"0416:5302":{"fps":"0.2"}}}}),encoding="utf-8")
    settings=SettingsStore(path).load()
    assert settings.default_fps=="0.1"
    assert all(profile.fps=="0.1" for profile in settings.profiles["Default"].values())
