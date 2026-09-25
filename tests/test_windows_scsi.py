from thermalright_lcd.windows_scsi import ScsiPanelConnection,enumerate_scsi_candidates
from thermalright_lcd.devices.thermalright_reference import MODELS
from thermalright_lcd.encoder import encode_reference

def test_scsi_enumeration_requires_real_path_vid_pid_and_usblcd_model():
    class Result:returncode=0;stdout='[{"path":"\\\\.\\\\PhysicalDrive3","pnp":"USB\\\\VID_0402&PID_3922\\\\A","model":"USBLCD Panel","status":"OK"},{"path":"\\\\.\\\\PhysicalDrive4","pnp":"USB\\\\VID_0402&PID_3922\\\\B","model":"Disk","status":"OK"}]'
    assert enumerate_scsi_candidates(lambda *a,**k:Result())==(("\\.\\PhysicalDrive3","0402:3922"),)

def test_scsi_connection_poll_init_frame_and_cleanup():
    class Api:
        def __init__(self):self.calls=[];self.closed=0
        def open(self,path):return 7
        def command(self,h,cdb,data,direction):
            self.calls.append((int.from_bytes(cdb[:4],"little"),len(data),direction));response=bytearray(len(data));response[0]=0x64;return bytes(response)
        def close(self,h):self.closed+=1
    api=Api();c=ScsiPanelConnection("\\.\\PhysicalDrive3","0402:3922",api);assert c.open().key=="elite-vision-scsi"
    model=MODELS["elite-vision-scsi"];raw=bytes(320*320*2);frame=encode_reference(model,rgb565=raw);assert c(frame)==len(raw);c.close();assert api.closed==1
