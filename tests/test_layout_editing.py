import os
import unittest
from copy import deepcopy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from thermalright_lcd.hardware_monitor import MonitorElement, MonitorLayout
from thermalright_lcd.layout_editing import LayoutEditController, PreviewTransform
from thermalright_lcd.monitor_designer import DesignerScene, HomeQuickEditor


class LayoutEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def layout(self,width=1920,height=462):
        return MonitorLayout("quick","0416:5408" if width==1920 else "0416:5302",width,height,elements=[MonitorElement("text",10,20,100,40),MonitorElement("text",210,120,100,40),MonitorElement("text",410,220,100,40)])
    def test_edit_mode_selection_and_disabled_no_mutation(self):
        layout=self.layout();c=LayoutEditController(layout);before=layout.to_dict();c.select([layout.elements[0].id]);self.assertFalse(c.move(10,10));self.assertEqual(layout.to_dict(),before)
        c.set_enabled(True);c.select([layout.elements[0].id]);self.assertTrue(c.move(10,10));self.assertEqual((layout.elements[0].x,layout.elements[0].y),(20,30));c.set_enabled(False);self.assertFalse(c.selected_ids)
    def test_multi_move_scale_align_distribute_undo_redo(self):
        layout=self.layout();layout.elements[1].x=250;c=LayoutEditController(layout);c.set_enabled(True);c.select([e.id for e in layout.elements]);original=layout.to_dict();self.assertTrue(c.scale(1.1));self.assertTrue(c.align("top"));self.assertTrue(c.distribute("horizontal"));changed=layout.to_dict();self.assertNotEqual(changed,original);self.assertTrue(c.undo());self.assertTrue(c.redo());self.assertEqual(layout.to_dict(),changed)
    def test_duplicate_delete_z_and_roundtrip_persistence(self):
        layout=self.layout(1280,480);c=LayoutEditController(layout);c.set_enabled(True);c.select([layout.elements[0].id]);self.assertTrue(c.duplicate());self.assertEqual(len(layout.elements),4);self.assertTrue(c.change_z(1));self.assertTrue(c.delete());restored=MonitorLayout.from_dict(layout.to_dict());self.assertEqual(restored.to_dict(),layout.to_dict())
    def test_preview_native_coordinate_conversion_for_both_devices(self):
        for native in ((1920,462),(1280,480)):
            transform=PreviewTransform(*native,500,190);point=(native[0]*.37,native[1]*.61);preview=transform.native_to_preview(*point);roundtrip=transform.preview_to_native(*preview);self.assertAlmostEqual(roundtrip[0],point[0]);self.assertAlmostEqual(roundtrip[1],point[1])
    def test_full_designer_and_home_controller_mutation_parity(self):
        a=self.layout();b=deepcopy(a);ids=[e.id for e in a.elements[:2]]
        scene=DesignerScene(a);[scene.items_by_id[x].setSelected(True) for x in ids];scene.scale_selected(1.1)
        controller=LayoutEditController(b);controller.set_enabled(True);controller.select(ids);controller.scale(1.1)
        self.assertEqual(a.to_dict(),b.to_dict())
    def test_home_quick_editor_activation_and_selection(self):
        layout=self.layout();editor=HomeQuickEditor(layout);self.assertTrue(editor.scene.controller.enabled);item=editor.scene.items_by_id[layout.elements[0].id];item.setSelected(True);self.assertEqual(editor.selected_ids(),{layout.elements[0].id});editor.hide();editor.deleteLater()


if __name__=="__main__":unittest.main()
