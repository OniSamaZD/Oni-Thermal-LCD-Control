import unittest
from thermalright_lcd.live_state import DeviceIdentity,DeviceReenumerated,SafetyError,TransportError
from thermalright_lcd.windows_hid import HidInterface,RealHidTransport,discover_5302

class Api:
    def enumerate_paths(self):return [r"\\?\hid#vid_0416&pid_5302&mi_00#x"]
    def inspect_path(self,p):return HidInterface(p,0x0416,0x5302,0x407,513,513)

class HidDiscoveryTests(unittest.TestCase):
    def test_exact_hid_path(self):
        x=discover_5302(Api());self.assertEqual((x.vid,x.pid),(0x0416,0x5302));self.assertEqual(x.output_report_bytes,513)
    def test_wrong_identity_rejected(self):
        class Bad(Api):
            def inspect_path(self,p):return HidInterface(p,0x0416,0x5408,0,0,0)
        with self.assertRaises(RuntimeError):discover_5302(Bad())

class IoApi:
    def __init__(self):self.writes=[];self.reads=[b"\x00"+bytes(36)];self.cancelled=False;self.closed=False;self.short=False
    def open(self,path):return 99
    def write_report(self,h,data,timeout):self.writes.append(data);return len(data)-int(self.short)
    def read_report(self,h,length,timeout):
        data=self.reads.pop(0);return data[:-1] if self.short else data
    def cancel(self,h):self.cancelled=True
    def close(self,h):self.closed=True

class HidTransportTests(unittest.TestCase):
    def setUp(self):
        self.target={"endpoint":"0x02","response_endpoint":"0x83"}
        self.identity=DeviceIdentity("0416:5302",r"USB\VID_0416&PID_5302\USBDISPLAY","{C}",1,"0x02","0x83","interrupt","HIDUSB","g",r"\\?\HID#VID_0416&PID_5302&MI_00#x",512)
        self.api=IoApi();self.current=[self.identity]
        self.tr=RealHidTransport(self.target,lambda:self.current[0],self.api,2,1024)
    def open(self):self.tr.discover();self.tr.open(100)
    def test_report_id_mapping_and_cleanup(self):
        self.open();self.assertEqual(self.tr.write("0x02",bytes(512),100),512)
        self.assertEqual(len(self.api.writes[0]),513);self.assertEqual(self.api.writes[0][0],0)
        self.assertEqual(len(self.tr.read("0x83",36,100)),36);self.tr.close(100)
        self.assertTrue(self.api.cancelled and self.api.closed)
    def test_wrong_path_endpoint_and_sizes_fail_closed(self):
        bad=DeviceIdentity(**{**self.identity.__dict__,"device_path":r"\\?\hid#wrong"})
        with self.assertRaises(SafetyError):RealHidTransport(self.target,lambda:bad,self.api,1,512).discover()
        self.open()
        for endpoint,payload in (("0x03",bytes(512)),("0x02",bytes(511))):
            with self.assertRaises(SafetyError):self.tr.write(endpoint,payload,100)
        self.api.short=True
        with self.assertRaises(TransportError):self.tr.write("0x02",bytes(512),100)
        with self.assertRaises(TransportError):self.tr.read("0x83",36,100)
    def test_budget_and_reenumeration(self):
        self.open();self.tr.write("0x02",bytes(512),100);self.tr.write("0x02",bytes(512),100)
        with self.assertRaises(SafetyError):self.tr.write("0x02",bytes(512),100)
        self.current[0]=DeviceIdentity(**{**self.identity.__dict__,"generation":"new"})
        with self.assertRaises(DeviceReenumerated):self.tr.revalidate(self.identity)
