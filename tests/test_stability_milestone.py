import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
try:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication,QWidget,QHBoxLayout
    from thermalright_lcd.gui import DisplayCard,PreviewBridge
    HAS_QT=True
except ImportError:HAS_QT=False

from thermalright_lcd.playback import FrameScheduler,MediaFrame
from thermalright_lcd.runtime import DisplaySession,LatestFrameQueue
from thermalright_lcd.media import MediaPipeline
from thermalright_lcd.subprocess_utils import hidden_subprocess_kwargs


class Sender:
    enabled=True
    def __init__(self):self.frames=[];self.closed=0
    def __call__(self,frame):self.frames.append(frame);return getattr(frame,"total_bytes",len(frame) if hasattr(frame,"__len__") else 1)
    def close(self):self.closed+=1


class TrackingSource:
    def __init__(self,color="red",duration=.01):self.color=color;self.duration=duration;self.index=0;self.closed=False
    def next_frame(self):
        frame=MediaFrame(Image.new("RGB",(8,8),self.color),self.duration,self.index,self.index*self.duration);self.index+=1;return frame
    def close(self):self.closed=True
    def skip(self,count):self.index+=count;return count


@unittest.skipUnless(HAS_QT,"PySide6 unavailable")
class GuiStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def animated_card(self,path,source):
        sender=Sender();card=DisplayCard("test",(1280,480),"0416:5302",hardware_sender=sender)
        card._deliver_frame=lambda frame:None
        patcher=patch("thermalright_lcd.gui.open_frame_source",return_value=source);patcher.start();self.addCleanup(patcher.stop);card.load(path);card.play();return card,sender
    def test_twenty_play_calls_reuse_timer_scheduler_decoder_and_session(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"a.gif";path.write_bytes(b"fixture");source=TrackingSource();card,sender=self.animated_card(path,source);scheduler=card.scheduler;timer=card.timer
            for _ in range(20):card.play()
            time.sleep(.04);self.assertIs(card.scheduler,scheduler);self.assertIs(card.timer,timer);self.assertEqual(card.scheduler_creations,1);self.assertEqual(scheduler.worker_starts,2);self.assertEqual(card.session.worker_starts,1);card.stop();self.assertTrue(source.closed)
    def test_loading_or_restoring_video_does_not_decode_before_play(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"idle.mov";path.write_bytes(b"fixture");card=DisplayCard("test",(1280,480),"0416:5302",hardware_sender=Sender())
            with patch("thermalright_lcd.gui.open_frame_source") as decoder:
                self.assertTrue(card.load(path));self.assertFalse(card.playing);self.assertFalse(card.hardware_started);self.assertIsNone(card.scheduler);decoder.assert_not_called()
            card.stop()
    def test_preview_signal_handoff_is_single_slot_latest_only(self):
        bridge=PreviewBridge()
        for value in range(100):
            image=QImage(4,4,QImage.Format_RGB32);image.fill(value);bridge.submit(image)
        self.assertEqual(bridge.pending,1);self.assertEqual(bridge.dropped,99);latest=bridge.take();self.assertEqual(latest.pixel(0,0)&0xffffff,99);self.assertEqual(bridge.pending,0)
    def test_thousand_high_resolution_previews_retain_one_downscaled_frame(self):
        bridge=PreviewBridge()
        for value in range(1000):
            image=QImage(1920,1080,QImage.Format_RGB32);image.fill(value);bridge.submit(image)
        self.assertEqual(bridge.pending,1);self.assertEqual(bridge.dropped,999);latest=bridge.take();self.assertLessEqual(latest.width(),720);self.assertLessEqual(latest.height(),240);self.assertEqual(bridge.pending,0)
    def test_pause_play_resumes_same_decoder_and_workers(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"a.gif";path.write_bytes(b"fixture");source=TrackingSource();card,_=self.animated_card(path,source);card.play();scheduler=card.scheduler;card.pause();self.assertTrue(scheduler.is_active);self.assertFalse(source.closed);card.play();self.assertIs(card.scheduler,scheduler);self.assertEqual(card.scheduler_creations,1);card.stop();self.assertTrue(source.closed)
    def test_geometry_stable_for_repeated_play_and_extreme_frames(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"a.png";Image.new("RGB",(16,16),"red").save(path);card=DisplayCard("test",(1280,480),"0416:5302",hardware_sender=Sender());host=QWidget();layout=QHBoxLayout(host);layout.addWidget(card);host.resize(700,500);host.show();self.app.processEvents();card.load(path);before=(card.sizeHint(),card.preview.sizeHint(),host.size())
            for _ in range(20):card.play();self.app.processEvents()
            for width,height in ((1,1),(7680,4320),(32,8000),(8000,32)):
                image=QImage(width,height,QImage.Format_RGB32);image.fill(0xff336699);card._show_image(image);self.app.processEvents();self.assertEqual(card.preview.sizeHint(),QSize(500,190));self.assertAlmostEqual(card.preview.width()/card.preview.height(),1280/480,delta=.03)
            after=(card.sizeHint(),card.preview.sizeHint(),host.size());self.assertEqual(after[1:],before[1:]);self.assertLess(abs(after[0].height()-before[0].height()),32);self.assertLess(abs(after[0].width()-before[0].width()),32);card.stop();host.close()
    def test_stop_and_clear_release_workers_decoder_frames_and_preview(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"a.gif";path.write_bytes(b"fixture");source=TrackingSource();card,_=self.animated_card(path,source);card.play();card.bridge.submit(QImage(20,20,QImage.Format_RGB32));card.stop();self.assertFalse(card.scheduler);self.assertTrue(source.closed);self.assertEqual(card.bridge.pending,0);self.assertIsNone(card.session._thread);self.assertIsNone(card.session._last);self.assertEqual(len(card.session.queue),0)
            card.clear();self.assertIsNone(card.path);self.assertEqual(card.pipeline.cache_entries,0);self.assertTrue(card.preview.pixmap().isNull())
    def test_media_replacement_releases_old_decoder(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.gif";b=Path(d)/"b.gif";a.write_bytes(b"a");b.write_bytes(b"b");sources=[TrackingSource("red"),TrackingSource("blue")];sender=Sender();card=DisplayCard("test",(1280,480),"0416:5302",hardware_sender=sender);card._deliver_frame=lambda frame:None
            with patch("thermalright_lcd.gui.open_frame_source",side_effect=sources):card.load(a);card.play();first=card.scheduler;card.load(b);self.assertTrue(sources[0].closed);card.play();self.assertIsNot(card.scheduler,first);self.assertEqual(card.scheduler_creations,2);card.stop();self.assertTrue(sources[1].closed)
    def test_two_displays_keep_independent_workers(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.gif";b=Path(d)/"b.gif";a.write_bytes(b"a");b.write_bytes(b"b");sa,sb=TrackingSource(),TrackingSource("blue");left=DisplayCard("left",(1920,462),"0416:5408",hardware_sender=Sender());right=DisplayCard("right",(1280,480),"0416:5302",hardware_sender=Sender());left._deliver_frame=lambda *args:None;right._deliver_frame=lambda *args:None
            with patch("thermalright_lcd.gui.open_frame_source",side_effect=[sa,sb]):left.load(a);right.load(b);left.play();right.play();left.stop();self.assertFalse(left.scheduler);self.assertTrue(right.scheduler.is_active);self.assertFalse(sb.closed);right.stop()


class RuntimeStabilityTests(unittest.TestCase):
    def test_static_cache_keeps_protocol_and_small_preview_not_full_canvas(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"large.png";Image.new("RGB",(4000,3000),"navy").save(path);pipeline=MediaPipeline(1);prepared,encoded=pipeline.prepare_static(path,"0416:5302");self.assertLessEqual(prepared.canvas.width,720);self.assertLessEqual(prepared.canvas.height,240);self.assertEqual(prepared.jpeg,b"");self.assertGreater(encoded.total_bytes,0);pipeline.clear();self.assertEqual(pipeline.cache_entries,0)
    def test_latest_frame_queue_clear_and_replacement(self):
        queue=LatestFrameQueue()
        for value in range(1000):queue.put(value)
        self.assertEqual(len(queue),1);self.assertEqual(queue.take(),999);self.assertEqual(queue.dropped,999);queue.put(object());queue.clear();self.assertEqual(len(queue),0)
    def test_scheduler_single_slot_under_slow_delivery(self):
        release=threading.Event();entered=threading.Event()
        def deliver(_):entered.set();release.wait(.5)
        source=TrackingSource(duration=.001);scheduler=FrameScheduler(source,deliver,target_fps=240);scheduler.start();self.assertTrue(entered.wait(.2));time.sleep(.04);self.assertLessEqual(scheduler.pending_frames,1);self.assertGreater(scheduler.metrics.dropped,0);release.set();self.assertTrue(scheduler.stop());self.assertTrue(source.closed);self.assertEqual(scheduler.active_workers,0);self.assertEqual(scheduler.pending_frames,0)
    def test_display_session_play_is_idempotent_and_stop_clears_retained_data(self):
        sender=Sender();session=DisplaySession("offline",sender,refresh_interval=.02);session.set_media(b"frame")
        for _ in range(20):session.play()
        time.sleep(.04);self.assertEqual(session.worker_starts,1);session.stop();self.assertIsNone(session._thread);self.assertIsNone(session._last);self.assertEqual(len(session.queue),0)
    def test_hidden_subprocess_flags_are_scoped(self):
        self.assertEqual(hidden_subprocess_kwargs("posix"),{})
        flags=hidden_subprocess_kwargs("nt");self.assertIn("creationflags",flags);self.assertIn("startupinfo",flags);self.assertNotEqual(flags["creationflags"],0)


if __name__=="__main__":unittest.main()
