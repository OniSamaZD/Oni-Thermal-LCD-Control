import json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/"src"))
from thermalright_lcd.jpeg_compat import compatibility_report
from thermalright_lcd.persistence import bounded_test_plan

(ROOT/"analysis"/"persistence-30s-plans.json").write_text(json.dumps({
    "generated_offline_only":True,"usb_writes":0,
    "pid5302":bounded_test_plan("0416:5302",30),"pid5408":bounded_test_plan("0416:5408",30)},indent=2),encoding="utf-8")
(ROOT/"analysis"/"generated-jpeg-compatibility.json").write_text(json.dumps({
    "pid5408":compatibility_report(ROOT/"analysis/display_9_16/new-session-first-frame.jpg",ROOT/"captures/generated/test-media/generated_9_16.jpg"),
    "pid5302":compatibility_report(ROOT/"analysis/live-5302-hid-transmitted-frame.jpg",ROOT/"captures/generated/test-media/generated_6.jpg")},indent=2),encoding="utf-8")
