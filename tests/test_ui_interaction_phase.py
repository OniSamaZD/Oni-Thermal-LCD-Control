import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QBoxLayout

from thermalright_lcd.device_connection import DisabledHardwareSender
from thermalright_lcd.gui import DisplayCard, MainWindow
from thermalright_lcd.hardware_monitor import MonitorElement, MonitorLayout, templates
from thermalright_lcd.media_types import MediaKind, detect_media_kind, media_filter
from thermalright_lcd.monitor_designer import HomeQuickEditor


class DropEvent:
    def __init__(self, path):
        self.mime = QMimeData();self.mime.setUrls([QUrl.fromLocalFile(str(path))]);self.accepted=False;self.ignored=False
    def mimeData(self):return self.mime
    def acceptProposedAction(self):self.accepted=True
    def ignore(self):self.ignored=True


class UiInteractionPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def card(self):return DisplayCard("test",(1280,480),"0416:5302",hardware_sender=DisabledHardwareSender())
    def drain(self,seconds=.06):
        limit=time.time()+seconds
        while time.time()<limit:self.app.processEvents();time.sleep(.002)

    def test_authoritative_photo_video_gif_and_unsupported_classification(self):
        self.assertIs(detect_media_kind("picture.png"),MediaKind.PHOTO)
        self.assertIs(detect_media_kind("movie.m4v"),MediaKind.VIDEO)
        self.assertIs(detect_media_kind("animation.gif"),MediaKind.GIF)
        self.assertIsNone(detect_media_kind("payload.exe"))
        with tempfile.TemporaryDirectory() as d:
            static=Path(d)/"static.webp";animated=Path(d)/"animated.webp"
            Image.new("RGB",(4,4),"red").save(static)
            frames=[Image.new("RGB",(4,4),color) for color in ("red","blue")];frames[0].save(animated,save_all=True,append_images=frames[1:],duration=50,loop=0)
            self.assertIs(detect_media_kind(static),MediaKind.PHOTO);self.assertIs(detect_media_kind(animated),MediaKind.GIF)

    def test_explicit_mode_changes_chooser_filter_without_changing_last_folder(self):
        card=self.card();card.select_media_kind(MediaKind.VIDEO)
        with patch("thermalright_lcd.gui.QFileDialog.getOpenFileName",return_value=("","")) as dialog:card.choose()
        self.assertEqual(dialog.call_args.args[3],media_filter(MediaKind.VIDEO));self.assertIs(card.selected_media_kind,MediaKind.VIDEO);card.shutdown()

    def test_embedded_media_empty_state_and_add_change_actions(self):
        with tempfile.TemporaryDirectory() as d:
            photo=Path(d)/"photo.png";Image.new("RGB",(8,4),"green").save(photo);card=self.card()
            self.assertIs(card.preview_stack.currentWidget(),card.media_empty_state);self.assertEqual(card.media_empty_title.text(),"Add Media")
            self.assertEqual([card.media_empty_buttons[k].text() for k in (MediaKind.PHOTO,MediaKind.VIDEO,MediaKind.GIF)],["Photo","Video","GIF"])
            self.assertEqual((card.footer_change.text(),card.choose_button.text()),("Add Media","Add Media"))
            card.load(photo);self.assertIs(card.preview_stack.currentWidget(),card.preview);self.assertEqual((card.footer_change.text(),card.choose_button.text()),("Change Media","Change Media"))
            card.clear();self.assertIs(card.preview_stack.currentWidget(),card.media_empty_state);self.assertEqual(card.footer_change.text(),"Add Media");card.shutdown()

    def test_drop_auto_detects_kind_and_unsupported_drop_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            photo=Path(d)/"photo.png";Image.new("RGB",(8,4),"green").save(photo);bad=Path(d)/"bad.txt";bad.write_text("no")
            card=self.card();event=DropEvent(photo);card.dragEnterEvent(event);self.assertTrue(event.accepted);card.dropEvent(event);self.assertIs(card.media_kind,MediaKind.PHOTO)
            rejected=DropEvent(bad);card.dragEnterEvent(rejected);self.assertTrue(rejected.ignored);card.dropEvent(rejected);self.assertEqual(card.path,photo);card.shutdown()

    def test_dynamic_controls_follow_loaded_media_kind(self):
        with tempfile.TemporaryDirectory() as d:
            photo=Path(d)/"photo.png";Image.new("RGB",(8,4),"green").save(photo);video=Path(d)/"video.mp4";video.write_bytes(b"fixture");gif=Path(d)/"a.gif";Image.new("RGB",(4,4),"blue").save(gif)
            card=self.card();card.load(photo);self.assertTrue(card.fps.isHidden());self.assertTrue(card.pause_button.isHidden());self.assertEqual(card.fps.currentText(),"Auto (Recommended)");self.assertEqual(card.output_rate(animated=False).fps,0.1);self.assertEqual(card.play_button.text(),"Show")
            with patch.object(card,"refresh"):card.load(video)
            self.assertFalse(card.fps.isHidden());self.assertTrue(card.pause_button.isHidden());self.assertFalse(card.footer_pause.isHidden());self.assertEqual(card.play_button.text(),"Play")
            with patch.object(card,"refresh"):card.load(gif)
            self.assertIs(card.media_kind,MediaKind.GIF);self.assertFalse(card.fps.isHidden());self.assertIn("Source timing",card.playback_hint.text());self.assertFalse(card.footer_play.isHidden());card.shutdown()

    def test_each_media_kind_retains_its_own_selection(self):
        with tempfile.TemporaryDirectory() as d:
            photo=Path(d)/"photo.png";Image.new("RGB",(8,4),"green").save(photo);video=Path(d)/"video.mp4";video.write_bytes(b"fixture");gif=Path(d)/"clip.gif";Image.new("RGB",(4,4),"blue").save(gif)
            card=self.card()
            with patch.object(card,"refresh"):
                card.load(photo);card.load(video);card.load(gif);card.select_media_kind(MediaKind.PHOTO);self.assertEqual(card.path,photo);card.select_media_kind(MediaKind.VIDEO);self.assertEqual(card.path,video);card.select_media_kind(MediaKind.GIF);self.assertEqual(card.path,gif)
            profile=card.profile();self.assertEqual(profile.media_by_type,{"photo":str(photo),"video":str(video),"gif":str(gif)});card.shutdown()

    def test_selecting_unconfigured_kind_stops_output_without_forgetting_other_media(self):
        with tempfile.TemporaryDirectory() as d:
            photo=Path(d)/"photo.png";Image.new("RGB",(8,4),"green").save(photo);card=self.card();card.load(photo)
            with patch.object(card.session,"stop") as stop,patch.object(card.session,"clear_media") as clear:
                card.select_media_kind(MediaKind.VIDEO);stop.assert_called_once();clear.assert_called_once()
            self.assertIsNone(card.path);self.assertEqual(card._media_paths[MediaKind.PHOTO],photo);self.assertIsNone(card._media_paths[MediaKind.VIDEO]);card.shutdown()

    def test_media_sensor_theme_media_switch_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            video=Path(d)/"video.mp4";video.write_bytes(b"fixture");window=MainWindow();card=window.left
            with patch.object(card,"refresh"):card.load(video)
            selected=card.path
            with patch.object(window,"start_monitor_layout"):
                card.output_selector.setCurrentIndex(card.output_selector.findData("hardware_monitor"));self.app.processEvents()
            with patch.object(card,"play") as play:
                card.output_selector.setCurrentIndex(card.output_selector.findData("media"));self.app.processEvents();play.assert_called_once()
            self.assertEqual(card.path,selected);self.assertEqual(card._media_paths[MediaKind.VIDEO],selected);window.shutdown()

    def test_stacked_home_uses_content_height_and_compact_action_bar(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            window=MainWindow();window.set_display_layout("stacked");self.assertGreaterEqual(window.display_splitter.minimumHeight(),710);self.assertEqual(window.display_splitter.maximumHeight(),16777215);self.assertGreaterEqual(window.left.minimumHeight(),350);self.assertEqual(window.left.maximumHeight(),16777215);self.assertEqual(window.home_actions.height(),54)
            window.set_display_layout("side_by_side");self.assertEqual(window.display_splitter.minimumHeight(),0);self.assertEqual(window.left.minimumHeight(),0);window.shutdown()

    def test_home_uses_auto_fit_and_meaningful_video_rates_only(self):
        card=self.card();self.assertTrue(card.preview_scale_slider.isHidden());self.assertTrue(card.auto_preview.isHidden());self.assertEqual([card.fps.itemText(i) for i in range(card.fps.count())],["Auto (Recommended)","10","15","20","24","25","30","40","50","60"]);card.shutdown()

    def test_initial_show_and_resize_autofit_both_native_aspect_ratios(self):
        for device,size,ratio in (("0416:5408",(1920,480),4.0),("0416:5302",(1280,480),1280/480)):
            card=DisplayCard("test",size,device,hardware_sender=DisabledHardwareSender());card.resize(1180,680);card.show();self.drain(.09)
            self.assertGreater(card.preview.width(),500);self.assertAlmostEqual(card.preview.width()/card.preview.height(),ratio,delta=.025)
            card.resize(920,680);self.drain(.06);self.assertAlmostEqual(card.preview.width()/card.preview.height(),ratio,delta=.025);card.shutdown();card.close()

    def test_live_transform_changes_never_call_refresh_or_recreate_animation(self):
        card=self.card();card.path=Path("active.mp4");card.media_kind=MediaKind.VIDEO;card.playing=True;sentinel=object();card.scheduler=sentinel;card.scheduler_creations=1
        with patch.object(card,"refresh") as refresh:
            card.pan_x_box.setValue(9);card.pan_y_box.setValue(-7);card.zoom_box.setValue(1.25);card.rotation.setCurrentIndex(1);card.mode.setCurrentText("Fill");self.drain()
            refresh.assert_not_called()
        self.assertIs(card.scheduler,sentinel);self.assertEqual(card.scheduler_creations,1);self.assertEqual((card.pan_x,card.pan_y,card.zoom,card.transform_rotation),(9,-7,1.25,90));card.scheduler=None;card.shutdown()

    def test_static_transform_storm_coalesces_to_one_content_refresh(self):
        card=self.card();card.path=Path("photo.png");card.media_kind=MediaKind.PHOTO;card.playing=True
        with patch.object(card,"refresh") as refresh:
            for value in range(1,8):card.pan_x_box.setValue(value)
            card.zoom_box.setValue(1.2);card.rotation.setCurrentIndex(1);self.drain(.09);self.assertEqual(refresh.call_count,1);self.drain(.08);self.assertEqual(refresh.call_count,1)
        card.shutdown()

    def test_preview_sizes_do_not_change_content_zoom_or_control_widths(self):
        card=self.card();card.auto_preview.setChecked(False);zoom=card.zoom_box.value();button_width=card.play_button.width()
        for scale in (100,125,150,175,200):
            card.preview_scale_slider.setValue(scale);self.assertAlmostEqual(card.preview.width()/card.preview.height(),1280/480,delta=.03);self.assertEqual(card.zoom_box.value(),zoom);self.assertEqual(card.play_button.width(),button_width)
        card.shutdown()

    def test_redesigned_context_tabs_and_responsive_reflow(self):
        card=self.card();self.assertTrue(card.context_tabs.isHidden());self.assertIsNotNone(card.unified_inspector)
        card.resize(760,700);card._update_workspace_layout();self.assertEqual(card.workspace_layout.direction(),QBoxLayout.TopToBottom)
        card.resize(1300,700);card.preview_scale_slider.setValue(100);card._update_workspace_layout();self.assertEqual(card.workspace_layout.direction(),QBoxLayout.LeftToRight);card.shutdown()

    def test_preview_keyboard_nudge_uses_native_coordinates(self):
        card=self.card();card.preview.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Right,Qt.NoModifier));self.assertEqual(card.pan_x_box.value(),1)
        card.preview.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Down,Qt.ShiftModifier));self.assertEqual(card.pan_y_box.value(),10);card.shutdown()

    def test_profile_overflow_keeps_secondary_actions_compact(self):
        card=self.card();self.assertTrue(card.profile_save_as_button.isHidden());self.assertEqual([action.text() for action in card.profile_overflow_menu.actions()],["Save As…","Manage, Import or Export…"]);card.shutdown()

    def test_home_inline_inspector_updates_selected_element_and_saved_state(self):
        element=MonitorElement("label + value",10,20,200,60,sensor_id="gpu.usage",custom_label="GPU")
        layout=MonitorLayout("Gaming","0416:5408",1920,462,elements=[element]);editor=HomeQuickEditor(layout);item=editor.scene.items_by_id[element.id];item.setSelected(True);editor.select_element(element.id)
        editor.properties.controls["x"].setValue(42);editor.properties.controls["font_size"].setValue(28);editor.properties.controls["opacity"].setValue(180);editor.properties.controls["sensor_id"].setText("gpu.temperature");editor.properties.controls["sensor_id"].editingFinished.emit();editor.properties.controls["color"].setText("#12abef");editor.properties.apply()
        self.assertEqual((element.x,element.font_size,element.opacity,element.sensor_id,element.color),(42,28,180,"gpu.temperature","#12abef"));self.assertEqual(editor.save_state.text(),"Modified");self.assertEqual(editor.autosave_state.text(),"· Draft autosaved");editor.mark_saved();self.assertEqual(editor.save_state.text(),"Saved");self.assertEqual(editor.autosave_state.text(),"")

    def test_profile_roundtrip_preserves_detected_media_type(self):
        with tempfile.TemporaryDirectory() as d:
            photo=Path(d)/"photo.png";Image.new("RGB",(8,4),"green").save(photo);card=self.card();card.load(photo);profile=card.profile();self.assertEqual(profile.media_type,"photo")
            other=self.card();other.apply_profile(profile);self.assertIs(other.media_kind,MediaKind.PHOTO);self.assertTrue(other.fps.isHidden());card.shutdown();other.shutdown()

    def test_selected_user_layout_is_the_layout_opened_on_home(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"LOCALAPPDATA":d}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda _:DisabledHardwareSender()):
            window=MainWindow();card=window.left;layout=MonitorLayout("Desk Stats",card.device_id,*card.size_target,elements=[MonitorElement("static label",10,10,text="ONI")]);window.settings.monitor_layout_library.setdefault(card.device_id,{})[layout.name]=layout.to_dict();window._refresh_monitor_template_options(card);card.monitor_template.setCurrentText(layout.name);card.quick_edit.setChecked(True);self.app.processEvents();self.assertEqual(card.home_quick_editor.layout.name,"Desk Stats");window.shutdown()


if __name__=="__main__":unittest.main()
