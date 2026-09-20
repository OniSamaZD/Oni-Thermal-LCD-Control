import os,tempfile,time,unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
try:
    from PySide6.QtCore import QMimeData,QUrl,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QStyle,QStyleOptionSpinBox
    from thermalright_lcd.gui import DisplayCard,MainWindow,STYLE
    from thermalright_lcd.device_connection import DisabledHardwareSender
    HAS_QT=True
except ImportError:HAS_QT=False

class RecordingSender:
    enabled=True
    def __init__(self):self.frames=[];self.closed=False
    def __call__(self,frame):self.frames.append(frame);return frame.total_bytes
    def close(self):self.closed=True

@unittest.skipUnless(HAS_QT,"PySide6 unavailable")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_independent_cards_and_preview(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.png";b=Path(d)/"b.png";Image.new("RGB",(40,20),"red").save(a);Image.new("RGB",(20,40),"blue").save(b)
            left=DisplayCard("left",(1920,462),"0416:5408");right=DisplayCard("right",(1280,480),"0416:5302")
            left.load(a);right.load(b);time.sleep(.05);self.app.processEvents()
            self.assertEqual((left.path,right.path),(a,b));self.assertFalse(left.preview.pixmap().isNull());self.assertFalse(right.preview.pixmap().isNull())
            left.play();right.play();left.pause();self.assertTrue(right.playing);left.stop();right.stop()
    def test_fractional_rate_preview_resize_and_brightness_controls_do_not_recreate_session(self):
        card=DisplayCard("x",(1280,480),"0416:5302",hardware_sender=RecordingSender());session=card.session
        self.assertNotIn("0.1",[card.fps.itemText(i) for i in range(card.fps.count())]);self.assertEqual(card.output_rate(animated=False).interval_seconds,10.0)
        card.auto_preview.setChecked(False);card.preview_scale_slider.setValue(150);self.assertEqual(card.preview_scale,150);self.assertAlmostEqual(card.preview.width()/card.preview.height(),1280/480,delta=.03);self.assertIs(card.session,session)
        card.brightness_slider.setValue(75);self.assertEqual(card.brightness_value.text(),"75%");card.shutdown()
    def test_spinbox_arrow_subcontrols_have_independent_click_targets(self):
        QApplication.instance().setStyleSheet(STYLE);card=DisplayCard("x",(1280,480),"0416:5302",hardware_sender=RecordingSender());card.show();self.app.processEvents();box=card.pan_x_box;box.setValue(0);option=QStyleOptionSpinBox();box.initStyleOption(option)
        up=box.style().subControlRect(QStyle.CC_SpinBox,option,QStyle.SC_SpinBoxUp,box);down=box.style().subControlRect(QStyle.CC_SpinBox,option,QStyle.SC_SpinBoxDown,box)
        self.assertGreaterEqual(up.width(),20);self.assertGreaterEqual(down.width(),20);QTest.mouseClick(box,Qt.LeftButton,pos=up.center());self.assertEqual(box.value(),1);QTest.mouseClick(box,Qt.LeftButton,pos=down.center());self.assertEqual(box.value(),0);self.assertEqual(card.pan_y_box.value(),0);card.shutdown()
    def test_drop_routing_accepts_local_url(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.png";Image.new("RGB",(4,4),"green").save(p);card=DisplayCard("x",(1280,480),"0416:5302")
            class Event:
                def __init__(self):self.m=QMimeData();self.m.setUrls([QUrl.fromLocalFile(str(p))]);self.accepted=False
                def mimeData(self):return self.m
                def acceptProposedAction(self):self.accepted=True
            event=Event();card.dropEvent(event);self.assertEqual(card.path,p);self.assertTrue(event.accepted);card.stop()
    def test_unsupported_media_is_rejected_without_replacing_state(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.txt";p.write_text("no");card=DisplayCard("x",(1280,480),"0416:5302")
            self.assertFalse(card.load(p));self.assertIsNone(card.path);self.assertIn("Unsupported",card.status.text());card.stop()
    def test_gui_startup_has_independent_sessions_and_controls(self):
        window=MainWindow();self.assertIsNot(window.left.session,window.right.session);self.assertEqual(window.windowTitle(),"Oni Thermal LCD Control")
        self.assertEqual((window.left.device_id,window.right.device_id),("0416:5408","0416:5302"));window._force_exit=True;window.close()
    def test_tray_icon_actions_and_compact_controls(self):
        window=MainWindow();self.assertFalse(window.app_icon.isNull());self.assertIsNotNone(window.tray);self.assertEqual(window.tray.toolTip(),"Oni Thermal LCD Control")
        self.assertEqual(set(window.tray_actions),{"Show / Open","Hide","Pause All","Resume All","Stop All","Exit"})
        self.assertLessEqual(window.left.mode.maximumWidth(),110);self.assertLessEqual(window.left.profile_box.maximumWidth(),170);self.assertTrue(window.left.profile_box.isEditable());self.assertLessEqual(window.left.profile_save_button.width(),70);self.assertLessEqual(window.left.profile_save_as_button.width(),80);self.assertLessEqual(window.layout_selector.maximumWidth(),130)
        self.assertTrue(window.left.product_photo.property("assetPath"));self.assertTrue(window.right.product_photo.property("assetPath"));window.shutdown()
    def test_sidebar_drawer_collapses_reclaims_space_and_persists(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            window=MainWindow();self.assertEqual(window.sidebar.width(),140);window.set_sidebar_expanded(False);self.assertEqual(window.sidebar.width(),58);self.assertEqual(window.nav["Home"].text(),"⌂");window.shutdown()
            restored=MainWindow();self.assertFalse(restored.settings.sidebar_expanded);self.assertEqual(restored.sidebar.width(),58);self.assertEqual(restored.nav["Hardware Monitor"].toolTip(),"Hardware Monitor");restored.shutdown()
    def test_layout_switch_and_card_order_do_not_recreate_device_sessions(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}):
            window=MainWindow();sessions=(window.left.session,window.right.session);window.left.playing=True;window.right.playing=True;schedulers=(window.left.scheduler,window.right.scheduler)
            window.set_display_layout("stacked");self.assertEqual(window.display_splitter.orientation(),Qt.Vertical)
            window.swap_display_order();self.assertEqual(window.settings.display_order,["0416:5302","0416:5408"])
            self.assertEqual((window.left.session,window.right.session),sessions);self.assertEqual((window.left.scheduler,window.right.scheduler),schedulers);self.assertTrue(window.left.playing and window.right.playing)
            window.setGeometry(5,5,840,600);self.app.processEvents();window.display_splitter.setSizes([420,280]);window.shutdown()
            restored=MainWindow();self.assertEqual(restored.settings.display_layout,"stacked");self.assertEqual(restored.settings.display_order,["0416:5302","0416:5408"]);self.assertEqual((restored.width(),restored.height()),(840,600));restored.shutdown()
    def test_unified_view_switch_preserves_sessions_schedulers_and_playback(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}):
            window=MainWindow();window.sync_toggle.setChecked(True);window.left.playing=window.right.playing=True;sessions=(window.left.session,window.right.session);schedulers=(window.left.scheduler,window.right.scheduler)
            window.set_unified_view(True);self.assertTrue(window.unified_panel.isVisible() or window.settings.unified_sync_view);window.set_unified_view(False)
            self.assertEqual((window.left.session,window.right.session),sessions);self.assertEqual((window.left.scheduler,window.right.scheduler),schedulers);self.assertTrue(window.left.playing and window.right.playing);window.shutdown()
    def test_home_quick_editor_toggle_mutation_and_persistence(self):
        from thermalright_lcd.device_connection import DisabledHardwareSender
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            window=MainWindow();card=window.left;session=card.session;card.quick_edit.setChecked(True);editor=card.home_quick_editor;self.assertIs(card.preview_stack.currentWidget(),editor)
            element=editor.layout.elements[0];editor.scene.controller.select([element.id]);before=element.x;self.assertTrue(editor.scene.controller.move(17,0));editor.changed.emit();self.assertEqual(element.x,before+17);self.assertIs(card.session,session)
            card.quick_edit.setChecked(False);self.assertIs(card.preview_stack.currentWidget(),card.preview);window.shutdown()
            restored=MainWindow();raw=restored.settings.monitor_layouts[restored.settings.active_profile]["0416:5408"];self.assertEqual(raw["elements"][0]["x"],before+17);restored.shutdown()
    def test_static_media_sensor_overlay_invalidates_and_recomposes_held_frame(self):
        from thermalright_lcd.hardware_monitor import templates
        senders={}
        def sender(pid):senders[pid]=RecordingSender();return senders[pid]
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=sender):
            media=Path(d)/"still.png";Image.new("RGB",(64,32),"navy").save(media);window=MainWindow();card=window.right;card.load(media);card.fps.setCurrentText("Event-driven");before=card.pipeline.total_prepares;window.start_monitor_overlay(card.device_id,templates(card.device_id)["Gaming Dashboard"])
            limit=time.time()+.5
            while card.pipeline.total_prepares==before and time.time()<limit:self.app.processEvents();time.sleep(.01)
            self.assertGreater(card.pipeline.total_prepares,before);self.assertIsNotNone(card._sensor_overlay);window.shutdown()
    def test_sync_same_media_uses_one_shared_decoder_and_independent_branches(self):
        import numpy as np
        from thermalright_lcd.playback import MediaFrame
        from thermalright_lcd.device_connection import DisabledHardwareSender
        class Source:
            backend="test shared";source_fps=60
            def __init__(self):self.index=0;self.closed=False;self.buffer=np.zeros((32,64,3),dtype=np.uint8)
            def next_frame(self):result=MediaFrame(None,1/60,self.index,self.index/60,self.buffer);self.index+=1;return result
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()),patch("thermalright_lcd.gui.open_frame_source",return_value=Source()) as decoder:
            media=Path(d)/"same.mp4";media.write_bytes(b"fixture");window=MainWindow();window.left.load(media);window.right.load(media);window.sync_toggle.setChecked(True);window.left.play();time.sleep(.08)
            self.assertEqual(decoder.call_count,1);self.assertIs(window.left.shared_hub,window.right.shared_hub);self.assertIsNotNone(window.shared_hub)
            window.left.brightness_slider.setValue(40);self.assertNotEqual(window.right.brightness_slider.value(),40);window.link_brightness.setChecked(True);window.left.brightness_slider.setValue(41);self.assertEqual(window.right.brightness_slider.value(),41);window.left.stop();self.assertIsNone(window.shared_hub);window.shutdown()
    def test_play_routes_generated_protocol_frame_to_injected_hardware_session(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"new.png";Image.new("RGB",(80,30),"magenta").save(p);sender=RecordingSender();card=DisplayCard("x",(1920,462),"0416:5408",hardware_sender=sender)
            card.load(p);self.assertFalse(sender.frames);card.play()
            for _ in range(30):
                if sender.frames:break
                time.sleep(.01);self.app.processEvents()
            self.assertTrue(sender.frames);self.assertEqual((sender.frames[0].vid_pid,sender.frames[0].dimensions),("0416:5408",(1920,462)))
            card.stop();self.assertTrue(sender.closed)
    def test_animated_gif_routes_bounded_generated_frames_to_hardware_session(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.gif";frames=[Image.new("RGB",(20,10),x) for x in ("red","blue")];frames[0].save(p,save_all=True,append_images=frames[1:],duration=[60,60],loop=0)
            sender=RecordingSender();card=DisplayCard("x",(1280,480),"0416:5302",hardware_sender=sender);card.load(p);card.play()
            limit=time.time()+.7
            while len(sender.frames)<2 and time.time()<limit:time.sleep(.02);self.app.processEvents()
            card.stop();self.assertGreaterEqual(len(sender.frames),2);self.assertTrue(all(x.vid_pid=="0416:5302" and x.dimensions==(1280,480) for x in sender.frames));self.assertLessEqual(len(card.session.queue),1)
    def test_video_routes_generated_frames_to_hardware_session(self):
        try:import cv2, numpy as np
        except ImportError:self.skipTest("OpenCV unavailable")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"v.avi";writer=cv2.VideoWriter(str(p),cv2.VideoWriter_fourcc(*"MJPG"),6,(32,16))
            if not writer.isOpened():self.skipTest("MJPG writer unavailable")
            writer.write(np.zeros((16,32,3),dtype=np.uint8));writer.write(np.full((16,32,3),255,dtype=np.uint8));writer.release()
            sender=RecordingSender();card=DisplayCard("x",(1920,462),"0416:5408",hardware_sender=sender);card.load(p);card.play()
            limit=time.time()+1
            while len(sender.frames)<2 and time.time()<limit:time.sleep(.02);self.app.processEvents()
            card.stop();self.assertGreaterEqual(len(sender.frames),2);self.assertTrue(all(x.vid_pid=="0416:5408" for x in sender.frames));self.assertLessEqual(len(card.session.queue),1)

    def test_synced_video_stop_then_independent_gif_restarts_both_output_paths(self):
        import numpy as np
        from thermalright_lcd.playback import MediaFrame
        class EndlessSource:
            backend="test shared";source_fps=60;fps=60;sequential_stream=True
            def __init__(self):self.index=0;self.buffer=np.zeros((32,64,3),dtype=np.uint8);self.closed=False
            def next_frame(self):
                result=MediaFrame(None,1/60,self.index,self.index/60,self.buffer);self.index+=1;return result
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:RecordingSender()),patch("thermalright_lcd.gui.open_frame_source",side_effect=[EndlessSource(),None,None]) as decoder:
            # The first source is the synchronized video decoder. Independent
            # GIF sources are supplied by the real Pillow path after the patch
            # side effect is exhausted below.
            video=Path(d)/"same.mp4";video.write_bytes(b"fixture");gif=Path(d)/"next.gif";frames=[Image.new("RGB",(20,10),x) for x in ("red","blue")];frames[0].save(gif,save_all=True,append_images=frames[1:],duration=60,loop=0)
            window=MainWindow();window.left.load(video);window.right.load(video);window.sync_toggle.setChecked(True);window.left.play();time.sleep(.08);window.left.stop();window.sync_toggle.setChecked(False)
            # Stop mocking source creation after the shared-video call so GIF
            # detection/decoding exercises the real independent implementation.
            decoder.side_effect=None
            from thermalright_lcd.playback import open_frame_source as real_open
            decoder.side_effect=lambda *args,**kwargs:real_open(*args,**kwargs)
            before=(len(window.left.hardware_sender.frames),len(window.right.hardware_sender.frames))
            for card in (window.left,window.right):card.load(gif);card.fps.setCurrentText("30");card.play(coordinated=True)
            limit=time.time()+1.2
            while time.time()<limit and (len(window.left.hardware_sender.frames)<before[0]+4 or len(window.right.hardware_sender.frames)<before[1]+4):time.sleep(.02);self.app.processEvents()
            self.assertGreaterEqual(len(window.left.hardware_sender.frames),before[0]+4,window.left.scheduler.metrics.last_error if window.left.scheduler else "no left scheduler")
            self.assertGreaterEqual(len(window.right.hardware_sender.frames),before[1]+4,window.right.scheduler.metrics.last_error if window.right.scheduler else "no right scheduler")
            self.assertIsNone(window.shared_hub);window.shutdown()

if __name__=="__main__":unittest.main()
