from __future__ import annotations

import argparse,json,os,tempfile,time
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import MainWindow
from thermalright_lcd.settings import AppSettings,DisplayProfile,SettingsStore


def main():
    p=argparse.ArgumentParser();p.add_argument("--video",type=Path,required=True);p.add_argument("--seconds",type=float,default=20);p.add_argument("--output",type=Path,required=True);args=p.parse_args();root=Path(tempfile.mkdtemp(prefix="oni-autorestore-"));os.environ["LOCALAPPDATA"]=str(root);os.environ["ONI_LCD_INSTANCE_NAME"]=f"OniPhysicalRestore-{os.getpid()}";still=root/"restore-static.png";Image.new("RGB",(1920,480),(50,5,80)).save(still)
    settings=AppSettings();settings.output_modes={"0416:5408":"media","0416:5302":"media"};settings.profiles["Default"]={"0416:5408":DisplayProfile(str(still),"Fill",0,"0.1",True,0,0,1,"Balanced",80,"Playing"),"0416:5302":DisplayProfile(str(args.video),"Fill",0,"60",True,0,0,1,"Extreme FPS",70,"Playing")};SettingsStore(root/"OniThermalLcd"/"settings.json").save(settings)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False);started=time.monotonic();window=MainWindow();first_frame={};deadline=started+15
    while time.monotonic()<deadline and any(card.session.metrics.sent<1 and not card.session.metrics.last_error for card in (window.left,window.right)):
        app.processEvents();now=time.monotonic()
        for card in (window.left,window.right):
            if card.session.metrics.sent and card.device_id not in first_frame:first_frame[card.device_id]=now-started
        time.sleep(.01)
    measured=time.monotonic();baseline={card.device_id:card.session.metrics.sent for card in (window.left,window.right)}
    while time.monotonic()-measured<args.seconds:app.processEvents();time.sleep(.01)
    report={"scenario":"physical-cold-start-autorestore","startup_seconds_to_first_frame":first_frame,"results":{card.device_id:{"path":str(card.path) if card.path else None,"desired_state":card.desired_playback_state,"playing":card.playing,"hardware_started":card.hardware_started,"completed_after_startup":card.session.metrics.sent-baseline[card.device_id],"physical_fps":card.actual_fps(),"error":card.session.metrics.last_error,"brightness":card.brightness_slider.value(),"rate":card.fps.currentText()} for card in (window.left,window.right)}}
    window.shutdown();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
