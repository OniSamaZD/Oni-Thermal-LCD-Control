from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thermalright_lcd.device_connection import (
    DisabledHardwareSender, GeneratedFrameConnection, _legacy_gui_configuration,
    build_gui_sender,
)
from thermalright_lcd.gui import MainWindow
from thermalright_lcd.live_state import DeviceIdentity, DryRunUsbTransport, SafetyError, validate_ready
from thermalright_lcd.reviewed_devices import reviewed_device_definition, reviewed_lifecycle
from thermalright_lcd.settings import AppSettings, SettingsStore


def bound_target(device_id: str) -> dict:
    target = reviewed_device_definition(device_id)
    if device_id == "0416:5408":
        target.update(stable_instance_id="USB\\VID_0416&PID_5408\\PUBLIC", interface_instance_id="USB\\VID_0416&PID_5408\\PUBLIC",
                      container_id="{PUBLIC-5408}", confirmed_device_path="\\\\?\\USB#VID_0416&PID_5408#PUBLIC#{3876E417-E089-4BCC-BBF8-47ABA55E46FB}")
    else:
        target.update(stable_instance_id="USB\\VID_0416&PID_5302\\PUBLIC", interface_instance_id="USB\\VID_0416&PID_5302\\PUBLIC",
                      container_id="{PUBLIC-5302}", confirmed_device_path="\\\\?\\HID#VID_0416&PID_5302&MI_00#PUBLIC#{4d1e55b2-f16f-11cf-88cb-001111000030}")
    return target


class PublicOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_fresh_machine_without_local_files_starts_gui_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"public-zip";root.mkdir()
            with patch("thermalright_lcd.device_connection._public_gui_configuration",side_effect=RuntimeError("no supported LCD connected")):
                self.assertIsInstance(build_gui_sender("0416:5408",root),DisabledHardwareSender)
                self.assertIsInstance(build_gui_sender("0416:5302",root),DisabledHardwareSender)
                with patch.dict(os.environ,{"LOCALAPPDATA":folder}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=lambda device_id:build_gui_sender(device_id,root)):
                    window=MainWindow();self.assertIsNotNone(window.left);self.assertIsNotNone(window.right);window.shutdown()

    def test_reviewed_5408_has_public_authorization_path(self):
        target=bound_target("0416:5408");transport=Mock()
        with tempfile.TemporaryDirectory() as folder,patch("thermalright_lcd.device_connection._public_gui_configuration",return_value=(target,reviewed_lifecycle("0416:5408"),"public-reviewed")),patch("thermalright_lcd.device_connection.RealUsbTransport",return_value=transport),patch("thermalright_lcd.windows_usb.CtypesWinUsbApi",return_value=Mock()):
            sender=build_gui_sender("0416:5408",Path(folder))
        self.assertTrue(sender.enabled);self.assertIs(sender.transport,transport);self.assertEqual(sender.target["authorization_source"],"public-reviewed-v1")

    def test_reviewed_5302_has_public_authorization_path(self):
        target=bound_target("0416:5302");transport=Mock()
        with tempfile.TemporaryDirectory() as folder,patch("thermalright_lcd.device_connection._public_gui_configuration",return_value=(target,reviewed_lifecycle("0416:5302"),"public-reviewed")),patch("thermalright_lcd.windows_hid.RealHidTransport",return_value=transport),patch("thermalright_lcd.windows_hid.CtypesWindowsHidApi",return_value=Mock()):
            sender=build_gui_sender("0416:5302",Path(folder))
        self.assertTrue(sender.enabled);self.assertIs(sender.transport,transport);self.assertEqual(sender.target["authorization_source"],"public-reviewed-v1")

    def test_unknown_device_remains_blocked(self):
        with patch("thermalright_lcd.device_connection._public_gui_configuration") as public:
            sender=build_gui_sender("0416:9999",Path("missing"))
        self.assertIsInstance(sender,DisabledHardwareSender);public.assert_not_called()

    def test_incompatible_identity_is_rejected_before_any_write(self):
        target=bound_target("0416:5408")
        actual=DeviceIdentity("0416:5408",target["stable_instance_id"],target["container_id"],0,"0x08","0x81","bulk","WINUSB",device_path=target["confirmed_device_path"],maximum_transfer_size=4096)
        transport=DryRunUsbTransport(actual,[]);sender=GeneratedFrameConnection(target,reviewed_lifecycle("0416:5408"),transport)
        with self.assertRaises(SafetyError):sender.open()
        self.assertEqual(transport.writes,[])

    def test_reviewed_readiness_fields_still_fail_closed(self):
        bad_5408=bytearray(512);bad_5408[:2]=b"\x03\xff";bad_5408[24:26]=(1280).to_bytes(2,"little");bad_5408[28:30]=(480).to_bytes(2,"little");bad_5408[44]=18
        with self.assertRaises(SafetyError):validate_ready("0416:5408",bytes(bad_5408),bytes(512),validation="reviewed-fields")
        bad_5302=bytearray(36);bad_5302[:8]=bytes.fromhex("dadbdcdd01800000");bad_5302[20:27]=b"UNKNOWN"
        with self.assertRaises(SafetyError):validate_ready("0416:5302",bytes(bad_5302),bytes(36),validation="reviewed-fields")

    def test_corrupt_local_configuration_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"config").mkdir();(root/"config/device-allowlist.json").write_text("{broken",encoding="utf-8")
            with patch("thermalright_lcd.device_connection._public_gui_configuration",side_effect=RuntimeError("no device")):
                sender=build_gui_sender("0416:5408",root)
            self.assertIsInstance(sender,DisabledHardwareSender);self.assertIn("unavailable",sender.reason.casefold())

    def test_corrupt_user_settings_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"settings.json";path.write_text("not-json",encoding="utf-8")
            loaded=SettingsStore(path).load()
        self.assertIsInstance(loaded,AppSettings);self.assertEqual(loaded.output_modes["0416:5408"],"stopped")

    def test_existing_exact_configuration_remains_compatible(self):
        target=bound_target("0416:5408");target["allowGuiGeneratedMedia"]=True
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"config").mkdir();(root/"config/device-allowlist.json").write_text(json.dumps({"schema":1,"devices":[target]}),encoding="utf-8")
            with patch("thermalright_lcd.device_connection.load_sequence",return_value=reviewed_lifecycle("0416:5408")):
                loaded=_legacy_gui_configuration(root,"0416:5408")
        self.assertEqual(loaded[0]["stable_instance_id"],target["stable_instance_id"]);self.assertEqual(loaded[2],"legacy-exact")

    def test_launchers_preserve_diagnostics_and_exit_status(self):
        root=Path(__file__).resolve().parents[1];normal=(root/"run-gui.bat").read_text(encoding="utf-8");debug=(root/"run-gui-debug.bat").read_text(encoding="utf-8");gui=(root/"src/thermalright_lcd/gui.py").read_text(encoding="utf-8")
        self.assertIn("ONI_LCD_GUI_SMOKE_TEST",normal);self.assertIn("-X faulthandler",debug)
        self.assertIn("ONI_EXIT_CODE",debug);self.assertIn("traceback",debug.casefold());self.assertIn("exit /b %ONI_EXIT_CODE%",debug)
        self.assertIn("traceback.print_exc()",gui)


if __name__=="__main__":unittest.main()
