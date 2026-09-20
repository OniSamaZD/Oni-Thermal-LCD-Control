import unittest
from thermalright_lcd.hardware_monitor import BoundedSensorHistory,MonitorElement,MonitorLayout,MonitorRenderer,WIDGET_KINDS,condition_visible,templates

class HardwareMonitorTests(unittest.TestCase):
    def test_polished_factory_theme_catalog_is_independent_per_device(self):
        required={"Oni Crimson","Cyber Red","Neon Blue","Ice / White","Minimal Dark","Carbon","Racing","Sci-Fi HUD","Clean Hardware","Gaming Wide"}
        wide,compact=templates("0416:5408"),templates("0416:5302");self.assertTrue(required.issubset(wide));self.assertTrue(required.issubset(compact))
        self.assertEqual((wide["Oni Crimson"].width,wide["Oni Crimson"].height),(1920,462));self.assertEqual((compact["Oni Crimson"].width,compact["Oni Crimson"].height),(1280,480));self.assertIsNot(wide["Oni Crimson"],compact["Oni Crimson"])
    def test_templates_target_exact_device_dimensions(self):
        self.assertEqual(MonitorRenderer(templates("0416:5408")["Gaming"]).render({"game.fps":144}).size,(1920,462))
        self.assertEqual(templates("0416:5302")["Minimal"].height,480)
        self.assertGreaterEqual(len(templates("0416:5408")),15)
        self.assertGreaterEqual(len(templates("0416:5302")),15)
        required={"Gaming Dashboard","Benchmark Mode","Minimal CPU/GPU","Full System Overview","Thermal Dashboard","CPU Focus","GPU Focus","GPU Overclock","CPU Overclock","Power Monitor","FPS + Frametime","Network Monitor","Storage Monitor","Cooling / Fans","Clean Dark","Cyber Telemetry","Neon Gaming","Compact Essentials","Clock + Hardware","Diagnostic / Stress Test"}
        self.assertTrue(required.issubset(templates("0416:5408")));self.assertTrue(required.issubset(templates("0416:5302")))
        for target,size in (("0416:5408",(1920,462)),("0416:5302",(1280,480))):
            for name in required:
                layout=templates(target)[name];self.assertEqual((layout.width,layout.height),size);self.assertTrue(layout.elements);self.assertTrue(any(e.sensor_id for e in layout.elements))
            gpu_sensors={element.sensor_id for element in templates(target)["GPU Focus"].elements if element.sensor_id}
            self.assertTrue({"gpu.usage","gpu.temperature","gpu.hotspot","gpu.clock","gpu.power","gpu.memory_used","gpu.fan"}.issubset(gpu_sensors))
        self.assertTrue({"clock","date","panel","rectangle","separator"}.issubset(WIDGET_KINDS))
    def test_layout_round_trip_and_sensor_render(self):
        layout=MonitorLayout("x","0416:5302",1280,480,elements=[MonitorElement("sensor",10,10,text="CPU {value}{unit}",sensor_id="cpu",unit="°C")])
        restored=MonitorLayout.from_dict(layout.to_dict());image=MonitorRenderer(restored).render({"cpu":55});self.assertEqual(image.size,(1280,480));self.assertNotEqual(image.getbbox(),None)
    def test_bar_and_graph_tolerate_missing_values(self):
        layout=MonitorLayout("x","0416:5408",1920,462,elements=[MonitorElement("bar",0,0,100,10,sensor_id="load"),MonitorElement("graph",0,20,100,50,sensor_id="load")])
        image=MonitorRenderer(layout).render({},{});self.assertEqual(image.size,(1920,462))
    def test_freeform_fields_formula_bindings_and_visibility(self):
        element=MonitorElement("label + value",17,29,411,83,sensor_id="HWiNFO:power",provider="HWiNFO",custom_label="GPU",format_string="{gpu_name} {gpu_usage}% {gpu_power}W",unit="W",decimals=2,prefix="[",suffix="]",align="right",vertical_align="bottom",font_family="Consolas",font_weight=700,text_style="italic",opacity=180,background="#101010",border_color="#ffffff",border_width=2,padding=9,spacing=3,visibility_condition="gpu_usage > 0",minimum=0,maximum=500,locked=True,group_id="g",z_index=7)
        layout=MonitorLayout("custom","0416:5408",1920,462,elements=[element],bindings={"gpu_name":"Native:name","gpu_usage":"Afterburner:usage","gpu_power":"HWiNFO:power"})
        restored=MonitorLayout.from_dict(layout.to_dict());self.assertEqual(restored.elements[0].format_string,element.format_string);self.assertEqual(restored.bindings["gpu_power"],"HWiNFO:power")
        image=MonitorRenderer(restored).render({"Native:name":"RTX","Afterburner:usage":82,"HWiNFO:power":280});self.assertEqual(image.size,(1920,462));self.assertTrue(condition_visible("gpu_usage > 0",{"gpu.usage":10}));self.assertFalse(condition_visible("__import__('os')",{}))
    def test_every_widget_kind_renders_and_element_count_is_unbounded(self):
        elements=[MonitorElement(kind,(i%6)*100,(i//6)*60,90,50,sensor_id="value",minimum=0,maximum=100) for i,kind in enumerate(WIDGET_KINDS*3)]
        layout=MonitorLayout("many","0416:5302",1280,480,elements=elements);self.assertEqual(len(MonitorLayout.from_dict(layout.to_dict()).elements),len(WIDGET_KINDS)*3);self.assertEqual(MonitorRenderer(layout).render({"value":55},{"value":[1,4,9]}).size,(1280,480))
    def test_graph_history_is_strictly_bounded(self):
        history=BoundedSensorHistory(10)
        for value in range(100):history.append("cpu",value)
        self.assertEqual(len(history.get("cpu")),10);self.assertEqual(history.get("cpu")[0],90)
    def test_overlay_is_transparent_and_background_options_round_trip(self):
        layout=MonitorLayout("overlay","0416:5302",1280,480,elements=[MonitorElement("label + value",10,10,300,70,sensor_id="cpu")],background_source="transparent",background_opacity=65,background_darken=20)
        restored=MonitorLayout.from_dict(layout.to_dict());self.assertEqual(restored.background_source,"transparent");self.assertEqual(restored.background_opacity,65)
        overlay=MonitorRenderer(restored).render_overlay({"cpu":42});self.assertEqual(overlay.mode,"RGBA");self.assertEqual(overlay.getpixel((1279,479))[3],0)
    def test_hidden_layer_persists_and_is_not_rendered(self):
        visible=MonitorElement("rectangle",0,0,20,20,background="#ffffff")
        hidden=MonitorElement("rectangle",30,0,20,20,background="#ffffff",visible=False)
        restored=MonitorLayout.from_dict(MonitorLayout("layers","0416:5302",80,40,background="#000000",background_source="solid",elements=[visible,hidden]).to_dict())
        image=MonitorRenderer(restored).render({})
        self.assertEqual(image.getpixel((5,5)),(255,255,255));self.assertEqual(image.getpixel((35,5)),(0,0,0));self.assertFalse(restored.elements[1].visible)

if __name__=="__main__":unittest.main()
