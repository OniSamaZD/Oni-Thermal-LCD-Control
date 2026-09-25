from __future__ import annotations

from datetime import datetime
from io import BytesIO
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from PIL import Image

from thermalright_lcd.sensor_theme import (
    DISPLAY_PRESETS,
    ELEMENT_TYPES,
    SCHEMA_VERSION,
    SUPPORTED_SENSOR_BINDINGS,
    SensorBindingResolver,
    SensorTheme,
    ThemeCanvas,
    ThemeElement,
    ThemeValidationError,
    format_sensor_value,
)
from thermalright_lcd.sensor_theme_package import (
    MAX_MEMBER_BYTES,
    export_theme_package,
    import_theme_package,
    read_theme_package,
)
from thermalright_lcd.sensor_theme_renderer import SensorThemeRenderer
from thermalright_lcd.sensor_theme_store import SensorThemeStore, default_user_theme_directory
from thermalright_lcd.sensors import SensorDefinition, SensorValue


ROOT = Path(__file__).resolve().parents[1]


def element(element_id: str = "value", element_type: str = "sensor_value", **changes) -> ThemeElement:
    raw = {
        "id": element_id, "name": element_id.title(), "type": element_type,
        "x": 0, "y": 0, "width": 120, "height": 60,
    }
    if element_type in {
        "sensor_value", "sensor_label", "sensor_label_value", "value_unit", "fps", "frametime",
        "progress_bar", "progress_indicator", "horizontal_bar", "vertical_bar",
        "ring_gauge", "arc_gauge", "line_graph", "area_graph",
    }:
        raw["sensor_binding"] = "cpu.usage"
    if element_type in {"image", "icon"}:
        raw["asset"] = "assets/sample.png"
    raw.update(changes)
    return ThemeElement(**raw)


def theme(elements=None, *, theme_id="test-theme", canvas=None) -> SensorTheme:
    return SensorTheme(theme_id, "Test Theme", canvas or ThemeCanvas(320, 180), list(elements or []))


def write_package(path: Path, manifest: object, members: dict[str, bytes] | None = None) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("theme.json", json.dumps(manifest) if not isinstance(manifest, bytes) else manifest)
        for name, payload in (members or {}).items():
            package.writestr(name, payload)


class SensorThemeModelTests(unittest.TestCase):
    def test_empty_theme_creation_and_round_trip(self):
        original = theme()
        loaded = SensorTheme.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(loaded.to_dict(), original.to_dict())
        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)

    def test_every_initial_element_type_is_supported(self):
        self.assertEqual(ELEMENT_TYPES, {
            "text", "sensor_value", "sensor_label", "sensor_label_value", "value_unit", "fps", "frametime",
            "image", "icon", "progress_bar", "progress_indicator", "horizontal_bar", "vertical_bar",
            "ring_gauge", "arc_gauge", "line_graph", "area_graph", "clock", "date",
        })
        for index, kind in enumerate(sorted(ELEMENT_TYPES)):
            self.assertEqual(element(f"element-{index}", kind).type, kind)

    def test_display_presets_and_custom_canvas(self):
        for preset, size in DISPLAY_PRESETS.items():
            self.assertEqual((ThemeCanvas(*size, preset).width, ThemeCanvas(*size, preset).height), size)
        custom = ThemeCanvas(777, 333, "custom", "cover")
        self.assertEqual((custom.width, custom.height, custom.scale_mode), (777, 333, "cover"))

    def test_invalid_properties_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(ThemeValidationError):
            element("bad", "sensor_value", opacity=2)
        with self.assertRaises(ThemeValidationError):
            element("bad", "unknown")
        with self.assertRaisesRegex(ThemeValidationError, "visible"):
            element("bad", "text", visible="false")
        with self.assertRaisesRegex(ThemeValidationError, "font_weight"):
            element("bad", "text", font_weight="heavy")
        with self.assertRaises(ThemeValidationError):
            ThemeElement.from_dict({**element().to_dict(), "arbitrary_code": "print('no')"})
        duplicate = element("same")
        with self.assertRaisesRegex(ThemeValidationError, "duplicate"):
            theme([duplicate, element("same", "text")])
        with self.assertRaisesRegex(ThemeValidationError, "unsafe"):
            SensorTheme.from_dict({**theme().to_dict(), "background_asset": "../private.png"})
        with self.assertRaisesRegex(ThemeValidationError, "animation"):
            element("bad-animation", "text", animation="execute")
        with self.assertRaisesRegex(ThemeValidationError, "padding"):
            element("bad-padding", "text", padding=-1)

    def test_schema_zero_migration(self):
        migrated = SensorTheme.from_dict({
            "version": 0, "id": "legacy", "name": "Legacy", "width": 640, "height": 240,
            "elements": [{
                "id": "load", "name": "Load", "kind": "bar", "sensor_id": "cpu.usage",
                "x": 1, "y": 2, "width": 100, "height": 10, "min": 0, "max": 100,
            }],
        })
        self.assertEqual((migrated.schema_version, migrated.canvas.width, migrated.elements[0].type), (1, 640, "horizontal_bar"))
        with self.assertRaisesRegex(ThemeValidationError, "unsupported"):
            SensorTheme.from_dict({**migrated.to_dict(), "schema_version": 99})


class SensorBindingTests(unittest.TestCase):
    def test_bindings_are_derived_from_existing_sensor_aliases(self):
        required = {"cpu.temperature", "cpu.usage", "cpu.package_power", "gpu.temperature", "gpu.usage", "gpu.memory_usage", "gpu.power", "gpu.fan_speed", "memory.usage"}
        self.assertTrue(required.issubset(SUPPORTED_SENSOR_BINDINGS))

    def test_exact_semantic_and_unavailable_resolution(self):
        resolver = SensorBindingResolver()
        exact = SensorValue.now(SensorDefinition("cpu", "Windows Basic", "CPU Usage", "CPU", "%", "cpu.usage"), 41)
        semantic = SensorValue.now(SensorDefinition("temp", "HWiNFO", "CPU (Tctl/Tdie)", "CPU", "°C"), 63.25)
        self.assertEqual(resolver.resolve("cpu.usage", [exact]).value, 41)
        self.assertEqual(resolver.resolve("cpu.temperature", [semantic]).value, 63.25)
        self.assertFalse(resolver.resolve("gpu.temperature", []).available)
        invalid = SensorValue.now(SensorDefinition("gpu", "HWiNFO", "GPU Temperature", "GPU", "°C", "gpu.temperature"), None, valid=False)
        self.assertFalse(resolver.resolve("gpu.temperature", [invalid]).available)

    def test_formatting_and_missing_value(self):
        resolver = SensorBindingResolver()
        formatted = element(prefix="[", suffix="]", unit="%", decimal_precision=2)
        self.assertEqual(format_sensor_value(formatted, resolver.resolve("cpu.usage", {"cpu.usage": 12.345})), "[12.35%]")
        self.assertEqual(format_sensor_value(formatted, resolver.resolve("cpu.usage", {})), "--")


class SensorThemeRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        Image.new("RGBA", (40, 30), "#ff0000").save(self.root / "assets" / "sample.png")

    def test_every_element_renders_on_one_custom_canvas(self):
        elements = []
        for index, kind in enumerate(sorted(ELEMENT_TYPES)):
            elements.append(element(
                f"kind-{index}", kind, x=(index % 5) * 120, y=(index // 5) * 90,
                width=105, height=75, text=kind, font_size=14, alignment="center",
            ))
        sample = SensorTheme("all-types", "All Types", ThemeCanvas(600, 270), elements)
        values = {"cpu.usage": 67}
        history = {"cpu.usage": [10, 20, 50, 67]}
        image = SensorThemeRenderer().render(sample, values, history=history, asset_root=self.root, now=datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(image.size, (600, 270))
        self.assertIsNotNone(image.getbbox())

    def test_preset_scaling_and_thumbnail_dimensions(self):
        sample = theme([element()], canvas=ThemeCanvas(320, 180))
        renderer = SensorThemeRenderer()
        for preset, size in DISPLAY_PRESETS.items():
            self.assertEqual(renderer.render(sample, {"cpu.usage": 10}, output_size=preset).size, size)
        self.assertEqual(renderer.thumbnail(sample, {"cpu.usage": 10}).size, (480, 120))

    def test_z_order_visibility_opacity_and_rotation(self):
        Image.new("RGBA", (20, 20), "#0000ff").save(self.root / "assets" / "blue.png")
        red = element("red", "image", width=20, height=20, asset="assets/sample.png", image_fit="stretch", z_index=1)
        blue = element("blue", "image", width=20, height=20, asset="assets/blue.png", image_fit="stretch", z_index=2, rotation=15)
        hidden = element("hidden", "text", x=20, visible=False, text="SHOULD NOT RENDER")
        image = SensorThemeRenderer().render(theme([red, blue, hidden], canvas=ThemeCanvas(40, 40)), {}, asset_root=self.root)
        pixel = image.convert("RGB").getpixel((10, 10))
        self.assertGreater(pixel[2], pixel[0])
        translucent = element("alpha", "image", width=20, height=20, asset="assets/sample.png", image_fit="stretch", opacity=.5)
        alpha_image = SensorThemeRenderer().render(theme([translucent], canvas=ThemeCanvas(20, 20)), {}, asset_root=self.root)
        self.assertLess(alpha_image.getpixel((10, 10))[0], 255)

    def test_shared_clock_drives_animation_without_widget_timers(self):
        animated = element("pulse", "text", text="ONI", animation="pulse", animation_duration=1)
        sample = theme([animated], canvas=ThemeCanvas(160, 80))
        dim = SensorThemeRenderer().render(sample, {}, now=datetime(2026, 1, 2, 3, 4, 5, 0))
        bright = SensorThemeRenderer().render(sample, {}, now=datetime(2026, 1, 2, 3, 4, 5, 500000))
        self.assertNotEqual(dim.tobytes(), bright.tobytes())

    def test_smooth_animation_interpolates_sensor_values(self):
        animated = element("smooth", "sensor_value", animation="smooth", animation_duration=1, decimal_precision=0)
        sample = theme([animated], canvas=ThemeCanvas(160, 80)); renderer = SensorThemeRenderer()
        renderer.render(sample, {"cpu.usage": 0}, now=datetime(2026, 1, 2, 3, 4, 5)).close()
        changed = renderer.render(sample, {"cpu.usage": 100}, now=datetime(2026, 1, 2, 3, 4, 5, 100000))
        halfway = renderer.render(sample, {"cpu.usage": 100}, now=datetime(2026, 1, 2, 3, 4, 5, 600000))
        final = renderer.render(sample, {"cpu.usage": 100}, now=datetime(2026, 1, 2, 3, 4, 6, 100000))
        self.assertNotEqual(changed.tobytes(), halfway.tobytes()); self.assertNotEqual(halfway.tobytes(), final.tobytes())
        bordered = element("border", "horizontal_bar", width=30, height=20, border_color="#00FF00", border_width=2)
        border_image = SensorThemeRenderer().render(theme([bordered], canvas=ThemeCanvas(30, 20)), {"cpu.usage": 50})
        self.assertGreater(border_image.getpixel((0, 10))[1], 200)

    def test_missing_sensor_and_missing_runtime_image_do_not_crash(self):
        missing_value = element("missing-value", unavailable_text="N/A")
        missing_image = element("missing-image", "image", x=130, asset="assets/sample.png")
        image = SensorThemeRenderer().render(theme([missing_value, missing_image]), {}, asset_root=self.root / "absent")
        self.assertEqual(image.size, (320, 180))

    def test_renderer_has_no_device_or_session_dependency(self):
        import thermalright_lcd.sensor_theme_renderer as module
        source = inspect.getsource(module)
        for forbidden in ("device_connection", "DisplaySession", "windows_usb", "build_gui_sender"):
            self.assertNotIn(forbidden, source)
        state = {"opens": 0, "resets": 0, "disconnects": 0}
        SensorThemeRenderer().render(theme([element()]), {"cpu.usage": 50})
        self.assertEqual(state, {"opens": 0, "resets": 0, "disconnects": 0})

    def test_bundled_theme_library_is_empty_and_blank_theme_renders(self):
        store = SensorThemeStore(builtin_directory=ROOT / "assets" / "sensor-themes", user_directory=self.root / "user")
        builtins = store.list_builtin()
        self.assertEqual(builtins, [])
        blank = store.create("Blank", preset="0416:5408"); self.assertEqual(blank.elements, [])
        self.assertEqual(SensorThemeRenderer().render(blank, {}).size, (1920, 462))


class SensorThemePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        Image.new("RGB", (32, 24), "#12aaff").save(self.root / "assets" / "sample.png")

    def test_export_import_roundtrip_with_asset_and_preview(self):
        original = theme([element("picture", "image")])
        package_path = export_theme_package(original, self.root / "shared.oni-theme", asset_root=self.root, preview=Image.new("RGB", (160, 40)))
        package = read_theme_package(package_path)
        self.assertEqual(package.theme.to_dict(), original.to_dict())
        self.assertIn("assets/sample.png", package.resources)
        self.assertIsNotNone(package.preview)
        imported, destination = import_theme_package(package_path, self.root / "user")
        self.assertEqual(imported.id, original.id)
        self.assertTrue((destination / "assets" / "sample.png").is_file())

    def test_zip_slip_and_duplicate_member_are_rejected(self):
        path = self.root / "unsafe.oni-theme"
        write_package(path, theme().to_dict(), {"../escape.png": b"bad"})
        with self.assertRaisesRegex(ThemeValidationError, "unsafe"):
            read_theme_package(path)
        duplicate = self.root / "duplicate.oni-theme"
        with zipfile.ZipFile(duplicate, "w") as package:
            package.writestr("theme.json", json.dumps(theme().to_dict()))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                package.writestr("theme.json", json.dumps(theme().to_dict()))
        with self.assertRaisesRegex(ThemeValidationError, "duplicate"):
            read_theme_package(duplicate)
        case_collision = self.root / "case-collision.oni-theme"
        with zipfile.ZipFile(case_collision, "w") as package:
            package.writestr("theme.json", json.dumps(theme().to_dict()))
            package.writestr("assets/A.png", b"one")
            package.writestr("assets/a.png", b"two")
        with self.assertRaisesRegex(ThemeValidationError, "duplicate"):
            read_theme_package(case_collision)

    def test_malformed_version_missing_asset_and_oversized_member(self):
        malformed = self.root / "malformed.oni-theme"
        write_package(malformed, b"{")
        with self.assertRaisesRegex(ThemeValidationError, "malformed"):
            read_theme_package(malformed)
        unsupported = self.root / "unsupported.oni-theme"
        write_package(unsupported, {**theme().to_dict(), "schema_version": 999})
        with self.assertRaisesRegex(ThemeValidationError, "unsupported"):
            read_theme_package(unsupported)
        missing = self.root / "missing.oni-theme"
        write_package(missing, theme([element("picture", "image")]).to_dict())
        with self.assertRaisesRegex(ThemeValidationError, "missing"):
            read_theme_package(missing)
        oversized = self.root / "oversized.oni-theme"
        write_package(oversized, theme().to_dict(), {"assets/huge.png": b"0" * (MAX_MEMBER_BYTES + 1)})
        with self.assertRaisesRegex(ThemeValidationError, "too large"):
            read_theme_package(oversized)

    def test_unreasonable_image_dimensions_are_rejected(self):
        output = BytesIO()
        Image.new("1", (5000, 5000)).save(output, "PNG")
        path = self.root / "pixels.oni-theme"
        write_package(path, theme([element("picture", "image")]).to_dict(), {"assets/sample.png": output.getvalue()})
        with self.assertRaisesRegex(ThemeValidationError, "unreasonable"):
            read_theme_package(path)


class SensorThemeStoreTests(unittest.TestCase):
    def test_user_storage_create_save_load_duplicate_rename_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            user = Path(folder) / "user"
            store = SensorThemeStore(user, ROOT / "assets" / "sensor-themes")
            created = store.create("My Theme", preset="custom", width=777, height=333)
            store.save(created)
            self.assertEqual(store.get(created.id).theme.canvas.width, 777)
            duplicate = store.duplicate(created.id, "My Copy")
            renamed = store.rename(duplicate.id, "Renamed Copy")
            self.assertEqual(renamed.name, "Renamed Copy")
            store.delete(duplicate.id)
            with self.assertRaises(KeyError):
                store.get(duplicate.id)
            self.assertEqual(store.list_builtin(), [])

    def test_default_user_storage_is_local_app_data(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            self.assertEqual(default_user_theme_directory(), Path(folder) / "OniThermalLcd" / "sensor-themes")


if __name__ == "__main__":
    unittest.main()
