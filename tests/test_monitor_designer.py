import os,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
try:
    from PySide6.QtCore import QPointF,Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication,QGraphicsItem,QMessageBox
    from thermalright_lcd.monitor_designer import DesignerScene,HardwareMonitorDesigner,PropertiesPanel,SensorBrowser
    from thermalright_lcd.hardware_monitor import MonitorElement,MonitorLayout
    from thermalright_lcd.sensors import SensorDefinition,SensorValue
    from thermalright_lcd.settings import AppSettings,SettingsStore
    HAS_QT=True
except ImportError:HAS_QT=False

@unittest.skipUnless(HAS_QT,"PySide6 unavailable")
class DesignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_drag_snap_group_lock_and_z_order_model(self):
        a=MonitorElement("text value",0,0,100,40,group_id="g");b=MonitorElement("text value",100,0,100,40,group_id="g");layout=MonitorLayout("x","0416:5302",1280,480,elements=[a,b],grid_size=10);scene=DesignerScene(layout);scene.items_by_id[a.id].setPos(QPointF(23,17));self.assertEqual((a.x,a.y),(20,20));self.assertEqual((b.x,b.y),(120,20));a.locked=True;scene.items_by_id[a.id]._sync_flags();self.assertFalse(bool(scene.items_by_id[a.id].flags() & QGraphicsItem.ItemIsMovable))
    def test_properties_expose_every_required_editable_field(self):
        panel=PropertiesPanel();required={"sensor_id","provider","custom_label","format_string","unit","decimals","prefix","suffix","x","y","width","height","align","vertical_align","font_family","font_size","font_weight","text_style","color","opacity","background","border_color","border_width","padding","spacing","visibility_condition","minimum","maximum","visible","locked","z_index"};self.assertTrue(required.issubset(panel.controls));self.assertEqual(panel.toolbox.count(),5)
    def test_keyboard_nudge_duplicate_and_delete_shortcuts(self):
        element=MonitorElement("text value",20,20,100,40);scene=DesignerScene(MonitorLayout("x","0416:5302",1280,480,elements=[element],snap_to_grid=False));item=scene.items_by_id[element.id];item.setSelected(True)
        scene.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress,Qt.Key_Right,Qt.NoModifier));self.assertEqual(element.x,21)
        duplicate=[];deleted=[];scene.duplicateRequested.connect(lambda:duplicate.append(True));scene.deleteRequested.connect(lambda:deleted.append(True));scene.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress,Qt.Key_D,Qt.ControlModifier));scene.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress,Qt.Key_Delete,Qt.NoModifier));self.assertEqual((len(duplicate),len(deleted)),(1,1))
    def test_multi_selection_group_scale_and_alignment(self):
        a=MonitorElement("text value",20,30,100,40,font_size=20);b=MonitorElement("text value",220,130,120,60,font_size=30);layout=MonitorLayout("x","0416:5302",1280,480,elements=[a,b],snap_to_grid=False);scene=DesignerScene(layout)
        scene.items_by_id[a.id].setSelected(True);scene.items_by_id[b.id].setSelected(True);scene.scale_selected(.5)
        self.assertEqual((a.x,a.y,a.width,a.height,a.font_size),(20,30,50,20,10));self.assertEqual((b.x,b.y,b.width,b.height,b.font_size),(120,80,60,30,15))
        scene.items_by_id[a.id].setSelected(True);scene.items_by_id[b.id].setSelected(True);scene.align_selected("left");self.assertEqual(a.x,b.x)
    def test_layer_visibility_is_persisted_and_undoable(self):
        element=MonitorElement("static label",10,10,text="ONI");layout=MonitorLayout("x","0416:5302",1280,480,elements=[element]);scene=DesignerScene(layout)
        self.assertTrue(scene.controller.set_visibility(element.id,False));self.assertFalse(element.visible)
        scene.undo();self.assertTrue(layout.elements[0].visible)
        scene.redo();self.assertFalse(layout.elements[0].visible)
        restored=MonitorLayout.from_dict(layout.to_dict());self.assertFalse(restored.elements[0].visible)
        old=layout.to_dict();old["elements"][0].pop("visible");self.assertTrue(MonitorLayout.from_dict(old).elements[0].visible)
    def test_sensor_browser_is_dynamic_and_filters_favorites_recent(self):
        favorites=[];recent=[];browser=SensorBrowser(favorites,recent);definition=SensorDefinition("gpu.temp","HWiNFO","GPU Temperature","GPU","°C");value=SensorValue.now(definition,63);browser.records=[value];browser.provider.addItem("HWiNFO");browser.category.setCurrentText("All / Advanced");browser.filter();self.assertEqual(browser.list.count(),1);browser.list.setCurrentRow(0);browser.toggle_favorite();self.assertIn(definition.qualified_id,favorites);browser.list.setCurrentRow(0);chosen=[];browser.sensorChosen.connect(chosen.append);browser.choose();self.assertEqual(chosen[0],value);self.assertEqual(recent[0],definition.qualified_id)
    def test_layouts_save_independently_per_profile_and_lcd(self):
        with tempfile.TemporaryDirectory() as d:
            settings=AppSettings();settings.profiles["Gaming"]={};store=SettingsStore(Path(d)/"settings.json");dialog=HardwareMonitorDesigner(settings,store);dialog.add_element();left_id=dialog.layout.elements[0].id;dialog.save_current();dialog.current_target="0416:5302";dialog.layout=MonitorLayout("right","0416:5302",1280,480,elements=[MonitorElement("static label",3,4,text="right")]);dialog.current_profile="Gaming";dialog.save_current();dialog.save();loaded=store.load();self.assertEqual(loaded.monitor_layouts["Default"]["0416:5408"]["elements"][0]["id"],left_id);self.assertEqual(loaded.monitor_layouts["Gaming"]["0416:5302"]["elements"][0]["text"],"right");dialog.reject()
    def test_template_selection_immediately_previews_finished_semantic_layout(self):
        with tempfile.TemporaryDirectory() as d:
            settings=AppSettings();store=SettingsStore(Path(d)/"settings.json");dialog=HardwareMonitorDesigner(settings,store)
            dialog.template.setCurrentText("Gaming Dashboard")
            self.assertTrue(dialog.template_previewing);self.assertEqual(dialog.layout.name,"Gaming Dashboard")
            ids={element.sensor_id for element in dialog.layout.elements}
            self.assertTrue({"cpu.temperature","cpu.usage","cpu.clock","cpu.power","gpu.temperature","gpu.usage","gpu.clock","gpu.power","gpu.memory_used","game.fps","game.frametime","memory.usage"}.issubset(ids))
            self.assertGreaterEqual(len(dialog.layout.elements),20);dialog.load_template();self.assertFalse(dialog.template_previewing);self.assertEqual(dialog.layout.name,"Custom");dialog.reject()
    def test_named_layout_save_rename_delete_and_restart_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"settings.json";settings=AppSettings();store=SettingsStore(path);dialog=HardwareMonitorDesigner(settings,store)
            dialog.layout=MonitorLayout("Custom","0416:5408",1920,462,elements=[MonitorElement("clock",20,20,format_string="%H:%M:%S")]);dialog.layout_name.setText("Desk Stats")
            self.assertTrue(dialog.save());self.assertIn("Desk Stats",settings.monitor_layout_library["0416:5408"]);self.assertGreaterEqual(dialog.template.findText("Desk Stats"),0)
            with patch("thermalright_lcd.monitor_designer.QInputDialog.getText",return_value=("Night Stats",True)):
                self.assertTrue(dialog.rename_layout())
            self.assertNotIn("Desk Stats",settings.monitor_layout_library["0416:5408"]);self.assertIn("Night Stats",settings.monitor_layout_library["0416:5408"])
            loaded=store.load();self.assertIn("Night Stats",loaded.monitor_layout_library["0416:5408"]);self.assertEqual(loaded.monitor_templates["0416:5408"],"Night Stats")
            with patch("thermalright_lcd.monitor_designer.QMessageBox.question",return_value=QMessageBox.Yes):self.assertTrue(dialog.delete_layout())
            self.assertNotIn("Night Stats",settings.monitor_layout_library["0416:5408"]);dialog.reject()
    def test_clock_and_date_format_property_is_exposed_consistently(self):
        panel=PropertiesPanel();clock=MonitorElement("clock",0,0);panel.set_element(clock)
        self.assertFalse(panel.controls["format_string"].isHidden())

if __name__=="__main__":unittest.main()
