import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from thermalright_lcd.profile_package import (
    Compatibility, MAX_FILE_BYTES, classify_compatibility, device_manifest,
    export_profile, import_profile, normalize_profile_name,
)
from thermalright_lcd.profiles import duplicate_profile, rename_profile, save_device_profile
from thermalright_lcd.settings import AppSettings, DisplayProfile
from thermalright_lcd.devices import DEVICES,DeviceDefinition,device_definition,register_device


class ProfilePackageTests(unittest.TestCase):
    def test_device_registry_preserves_proven_distinct_protocols(self):
        wide=device_definition("0416:5408");compact=device_definition("0416:5302")
        self.assertEqual((wide.interface,wide.out_endpoint,wide.in_endpoint,wide.frame_ack_required),(0,"0x09","0x81",True))
        self.assertEqual((compact.interface,compact.out_endpoint,compact.in_endpoint,compact.frame_ack_required),(1,"0x02","0x83",False))
        test=DeviceDefinition("0416:ffff","Thermalright","Contributor Test",(1,1),(1,1),"test",0,"0x01",None,"bulk",1,False)
        register_device(test);self.assertIs(DEVICES[test.vid_pid],test);DEVICES.pop(test.vid_pid)
    def test_named_save_unicode_save_vs_save_as_and_duplicate(self):
        settings=AppSettings();profile=DisplayProfile(brightness=61)
        self.assertEqual(save_device_profile(settings,"  Anime 白  ","0416:5408",profile),"Anime 白")
        with self.assertRaises(FileExistsError):save_device_profile(settings,"Anime 白","0416:5408",profile)
        save_device_profile(settings,"Anime 白","0416:5408",DisplayProfile(brightness=72),overwrite=True)
        self.assertEqual(settings.profiles["Anime 白"]["0416:5408"].brightness,72)
        duplicate_profile(settings,"Anime 白","Anime 白 Copy");rename_profile(settings,"Anime 白 Copy","Desk Night")
        self.assertIn("Desk Night",settings.profiles)
    def test_maximum_twenty_user_profiles(self):
        settings=AppSettings()
        for index in range(20):save_device_profile(settings,f"P{index}","0416:5408",DisplayProfile())
        with self.assertRaisesRegex(OverflowError,"20 profiles"):save_device_profile(settings,"P20","0416:5408",DisplayProfile())
    def test_empty_and_control_names_rejected(self):
        with self.assertRaises(ValueError):normalize_profile_name("  ")
        with self.assertRaises(ValueError):normalize_profile_name("bad\x01name")
    def test_export_import_assets_and_exact_device(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);media=root/"dragon ü.png";media.write_bytes(b"png fixture");background=root/"panel.jpg";background.write_bytes(b"jpg fixture")
            profile=DisplayProfile(str(media),"Fill",90,"45",False,7,-2,1.25,"Balanced",73,"Paused")
            package=export_profile(root/"Dragon Gold", "Dragon Gold", "0416:5408",profile,monitor_layout={"width":1920,"height":462,"elements":[],"background_source":"custom_image","background_image":str(background)},output_mode="media_with_sensor_overlay",sensor_template="Gaming Dashboard",preview_scale=125)
            self.assertEqual(package.suffix,".oniprofile")
            with zipfile.ZipFile(package) as archive:self.assertEqual(set(archive.namelist()),{"manifest.json","profile.json","assets/media.png","assets/background.jpg"})
            imported=import_profile(package,root/"managed", "0416:5408")
            self.assertEqual(imported.compatibility,Compatibility.EXACT);self.assertEqual(imported.name,"Dragon Gold");self.assertTrue(Path(imported.profile.media).is_file());self.assertTrue(Path(imported.profile.media).is_relative_to(root/"managed"));self.assertTrue(Path(imported.monitor_layout["background_image"]).is_file());self.assertTrue(Path(imported.monitor_layout["background_image"]).is_relative_to(root/"managed"));self.assertEqual(imported.preview_scale,125)
    def test_device_compatibility_levels(self):
        exact=device_manifest("0416:5408")
        self.assertEqual(classify_compatibility(exact,"0416:5408"),Compatibility.EXACT)
        compatible=dict(exact,pid="9999",model="Other")
        self.assertEqual(classify_compatibility(compatible,"0416:5408"),Compatibility.COMPATIBLE)
        self.assertEqual(classify_compatibility(exact,"0416:5302"),Compatibility.MISMATCH)
        self.assertEqual(classify_compatibility({},"0416:5302"),Compatibility.UNKNOWN)
    def test_cross_device_import_warns_but_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);package=export_profile(root/"x.oniprofile","Wide","0416:5408",DisplayProfile())
            imported=import_profile(package,root/"managed","0416:5302")
            self.assertEqual(imported.compatibility,Compatibility.MISMATCH);self.assertTrue(imported.warnings)
    def test_corrupt_invalid_future_missing_media_and_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);bad=root/"bad.oniprofile";bad.write_bytes(b"not zip")
            with self.assertRaises(zipfile.BadZipFile):import_profile(bad,root/"managed","0416:5408")
            future=root/"future.oniprofile"
            with zipfile.ZipFile(future,"w") as z:
                z.writestr("manifest.json",json.dumps({"format":"oni-profile","format_version":99,"profile_name":"x"}));z.writestr("profile.json",json.dumps({"profile":{}}))
            with self.assertRaisesRegex(ValueError,"version"):import_profile(future,root/"managed","0416:5408")
            missing=root/"missing.oniprofile"
            with zipfile.ZipFile(missing,"w") as z:
                z.writestr("manifest.json",json.dumps({"format":"oni-profile","format_version":1,"profile_name":"x","device":device_manifest("0416:5408")}));z.writestr("profile.json",json.dumps({"profile":{"media":"assets/media.png"}}))
            imported=import_profile(missing,root/"managed","0416:5408");self.assertEqual(imported.profile.media,"");self.assertTrue(imported.warnings)
            traversal=root/"traversal.oniprofile"
            with zipfile.ZipFile(traversal,"w") as z:z.writestr("../evil.txt",b"x");z.writestr("manifest.json",b"{}");z.writestr("profile.json",b"{}")
            with self.assertRaisesRegex(ValueError,"unsafe"):import_profile(traversal,root/"managed","0416:5408")
    def test_invalid_manifest_and_unsupported_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);bad=root/"bad.oniprofile"
            with zipfile.ZipFile(bad,"w") as z:z.writestr("manifest.json",json.dumps({"format":"wrong","format_version":1}));z.writestr("profile.json",json.dumps({"profile":{}}))
            with self.assertRaisesRegex(ValueError,"format"):import_profile(bad,root/"managed","0416:5408")
            exe=root/"x.exe";exe.write_bytes(b"MZ")
            with self.assertRaisesRegex(ValueError,"unsupported"):export_profile(root/"x.oniprofile","x","0416:5408",DisplayProfile(media=str(exe)))
            injected=root/"injected.oniprofile"
            with zipfile.ZipFile(injected,"w") as z:z.writestr("manifest.json",b"{}");z.writestr("profile.json",b"{}");z.writestr("assets/run.exe",b"MZ")
            with self.assertRaisesRegex(ValueError,"unsupported archive"):import_profile(injected,root/"managed","0416:5408")
    def test_oversized_asset_is_rejected_on_export_and_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);media=root/"big.png";media.write_bytes(b"12345")
            with patch("thermalright_lcd.profile_package.MAX_FILE_BYTES",4),self.assertRaisesRegex(ValueError,"single-file"):export_profile(root/"x.oniprofile","x","0416:5408",DisplayProfile(media=str(media)))
            package=root/"big.oniprofile"
            with zipfile.ZipFile(package,"w") as z:z.writestr("manifest.json",json.dumps({"format":"oni-profile","format_version":1,"profile_name":"x"}));z.writestr("profile.json",json.dumps({"profile":{}}));z.writestr("assets/media.png",b"12345")
            with patch("thermalright_lcd.profile_package.MAX_FILE_BYTES",4),self.assertRaisesRegex(ValueError,"too large"):import_profile(package,root/"managed","0416:5408")


if __name__=="__main__":unittest.main()
