import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from thermalright_lcd.playback import FrameScheduler,SharedFrameScheduler,MediaFrame,OpenCvVideoSource,PillowAnimationSource
from thermalright_lcd.settings import AppSettings,DisplayProfile,SettingsStore
from thermalright_lcd.supervisor import ConnectionState,DeviceSupervisor


class EndlessSource:
    def __init__(self,color="red",fail=False):self.i=0;self.closed=False;self.color=color;self.fail=fail
    def next_frame(self):
        if self.fail:raise IOError("decode")
        x=MediaFrame(Image.new("RGB",(2,2),self.color),.01,self.i,self.i*.01);self.i+=1;return x
    def close(self):self.closed=True


class PlaybackTests(unittest.TestCase):
    def test_gif_duration_loop_and_one_frame_memory(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"a.gif";frames=[Image.new("RGB",(4,3),c) for c in ("red","blue")]
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=[40,80],loop=0)
            source=PillowAnimationSource(path);a=source.next_frame();b=source.next_frame();c=source.next_frame();source.close()
            self.assertEqual((a.index,b.index,c.index),(0,1,0));self.assertAlmostEqual(a.duration_seconds,.04,places=2);self.assertEqual(a.image.size,(4,3))
    def test_fps_limit_and_bounded_delivery(self):
        delivered=[];source=EndlessSource();scheduler=FrameScheduler(source,delivered.append,target_fps=20)
        scheduler.start();time.sleep(.18);scheduler.stop()
        self.assertLessEqual(len(delivered),5);self.assertTrue(source.closed);self.assertEqual(scheduler.metrics.delivered,len(delivered))
    def test_two_animation_schedulers_are_independent(self):
        left=[];right=[];a=FrameScheduler(EndlessSource("red"),left.append,30);b=FrameScheduler(EndlessSource("blue"),right.append,15)
        a.start();b.start();time.sleep(.12);a.stop();b.stop();self.assertTrue(left and right);self.assertGreaterEqual(len(left),len(right))
    def test_shared_decoder_fans_one_frame_to_independent_latest_slots(self):
        import numpy as np
        class SharedSource:
            def __init__(self):self.index=0;self.closed=False;self.buffer=np.zeros((8,16,3),dtype=np.uint8)
            def next_frame(self):
                frame=MediaFrame(None,.005,self.index,self.index*.005,self.buffer);self.index+=1;return frame
            def close(self):self.closed=True
        source=SharedSource();fast=[];slow=[]
        def slow_consumer(frame):slow.append(frame);time.sleep(.02)
        hub=SharedFrameScheduler(source,{"fast":fast.append,"slow":slow_consumer},target_fps=120);hub.start();time.sleep(.12);self.assertTrue(hub.stop())
        self.assertGreater(len(fast),len(slow));self.assertGreater(hub.dropped["slow"],0);self.assertTrue(source.closed)
        self.assertTrue(fast and slow);self.assertIs(fast[0].native_bgr,slow[0].native_bgr)
    def test_decoder_failure_isolated(self):
        good=[];bad=FrameScheduler(EndlessSource(fail=True),lambda _:None);ok=FrameScheduler(EndlessSource(),good.append,20)
        bad.start();ok.start();time.sleep(.08);bad.stop();ok.stop();self.assertIn("decode",bad.metrics.last_error);self.assertTrue(good)
    def test_ffmpeg_backed_video_source(self):
        try:import cv2
        except ImportError:self.skipTest("OpenCV unavailable")
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"x.avi";writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"MJPG"),10,(16,8))
            if not writer.isOpened():self.skipTest("MJPG writer unavailable")
            writer.write(np.zeros((8,16,3),dtype=np.uint8));writer.write(np.full((8,16,3),255,dtype=np.uint8));writer.release()
            source=OpenCvVideoSource(path,loop=False);a=source.next_frame();b=source.next_frame();source.close()
            self.assertEqual((a.native_bgr.shape[1::-1],b.native_bgr.shape[1::-1]),((16,8),(16,8)));self.assertIsNone(a.image);self.assertAlmostEqual(a.duration_seconds,.1,places=2);self.assertEqual(source.decoder_threads,1)


class SettingsTests(unittest.TestCase):
    def test_arbitrary_profile_names_and_complete_state_round_trip(self):
        from thermalright_lcd.settings import AppSettings,DisplayProfile,SettingsStore
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"settings.json";settings=AppSettings(window_geometry=[123,87,1180,720],display_layout="stacked",display_order=["0416:5302","0416:5408"],splitter_sizes=[333,777],display_sync=True,unified_sync_view=True,link_brightness=True,active_profile="My Anime Setup",designer_geometry=[20,30,1400,850],sensor_favorites=["HWiNFO:x"],monitor_layouts={"My Anime Setup":{"0416:5408":{"name":"custom"}}})
            for name in ("My Anime Setup","Benchmark LCD","Night","Asuka","Custom 1"):settings.profiles[name]={"0416:5408":DisplayProfile("a.mp4","Fill",90,"60",False,21,-105,1.5,"Extreme FPS",73),"0416:5302":DisplayProfile("b.png","Fit",180,"45",False,-4,8,2,"Balanced",55)}
            SettingsStore(path).save(settings);loaded=SettingsStore(path).load();self.assertEqual(set(settings.profiles),set(loaded.profiles));self.assertEqual(loaded.active_profile,"My Anime Setup");self.assertTrue(loaded.unified_sync_view);self.assertEqual(loaded.designer_geometry,[20,30,1400,850]);self.assertEqual(loaded.profiles["Asuka"]["0416:5408"].quality,"Extreme FPS")
    def test_profiles_round_trip_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            store=SettingsStore(Path(d)/"settings.json");value=AppSettings(active_profile="Gaming")
            value.profiles["Gaming"]={"0416:5408":DisplayProfile("a.gif","Fill",90,"30",True),"0416:5302":DisplayProfile("b.png","Fit",0,"Auto",False)}
            store.save(value);loaded=store.load();self.assertEqual(loaded.active_profile,"Gaming");self.assertEqual(loaded.profiles["Gaming"]["0416:5408"].rotation,90)
            self.assertFalse((Path(d)/"settings.json.tmp").exists())
    def test_extended_settings_and_library_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            store=SettingsStore(Path(d)/"settings.json");value=AppSettings(auto_reconnect=False,default_fps="24",media_library=["C:/media/a.mp4"])
            store.save(value);loaded=store.load();self.assertFalse(loaded.auto_reconnect);self.assertEqual(loaded.default_fps,"24");self.assertEqual(loaded.media_library,["C:/media/a.mp4"])


class SupervisorTests(unittest.TestCase):
    def test_disconnect_reconnect_lifecycle(self):
        present=[False,True,True,False,True];events=[]
        def discover():return present.pop(0) if present else True
        s=DeviceSupervisor(discover,lambda:events.append("connect"),lambda:events.append("disconnect"),.01);s.start();time.sleep(.12);s.stop()
        self.assertGreaterEqual(s.metrics.connects,2);self.assertGreaterEqual(s.metrics.disconnects,2);self.assertEqual(s.state,ConnectionState.DISCONNECTED)

if __name__=="__main__":unittest.main()
