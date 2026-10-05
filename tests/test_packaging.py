import ast
import re
import tomllib
import unittest
from pathlib import Path

from thermalright_lcd import __version__


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_frozen_entry_is_import_safe(self):
        source = (ROOT / "packaging/oni_gui_entry.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertTrue(any(isinstance(node, ast.If) for node in tree.body))
        self.assertIn("freeze_support()", source)

    def test_spec_uses_public_reviewed_device_definitions(self):
        source = (ROOT / "packaging/oni_thermal_lcd.spec").read_text(encoding="utf-8")
        reviewed = (ROOT / "src/thermalright_lcd/reviewed_devices.py").read_text(encoding="utf-8")
        for private_name in ("device-allowlist.json", "session-report.json", "pid5408-new-session-first-frame.json", "pid5302-same-session-first-frame.json"):
            self.assertNotIn(private_name, source)
        self.assertIn('"0416:5408"', reviewed); self.assertIn('"0416:5302"', reviewed)
        self.assertIn('console=False', source)
        self.assertIn('ERROR_PROC_NOT_FOUND', source)
        self.assertIn('"ICUUC.DLL", "ICUDT78.DLL"', source)
        self.assertIn('upx=False', source)
        self.assertIn("COLLECT(", source)
        self.assertIn('name="."', source)

    def test_version_metadata_matches_project(self):
        metadata = (ROOT / "packaging/version_info.txt").read_text(encoding="utf-8")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime = (ROOT / "src/thermalright_lcd/gui.py").read_text(encoding="utf-8")
        installer = (ROOT / "packaging/oni_thermal_lcd.iss").read_text(encoding="utf-8")
        self.assertEqual(__version__, "0.2.0-beta.1")
        self.assertEqual(project["project"]["version"], "0.2.0b1")
        self.assertIn("filevers=(0, 2, 0, 1)", metadata)
        self.assertIn("StringStruct(u'FileVersion', u'0.2.0.1')", metadata)
        self.assertIn("StringStruct(u'ProductVersion', u'0.2.0-beta.1')", metadata)
        self.assertIn("setApplicationVersion(__version__)", runtime)
        self.assertIn('#define AppVersion "0.2.0-beta.1"', installer)
        self.assertIn("VersionInfoVersion=0.2.0.1", installer)
        self.assertIn("Oni-Thermal-LCD-Control-0.2.0-beta.1-Setup", installer)
        self.assertIn("Oni Thermal LCD Control.exe", metadata)

    def test_beta_installer_has_distinct_side_by_side_identity(self):
        installer = (ROOT / "packaging/oni_thermal_lcd.iss").read_text(encoding="utf-8")
        self.assertIn('#define AppName "Oni Thermal LCD Control Beta"', installer)
        app_id = re.search(r"^AppId=\{\{([^}]+)\}$", installer, re.MULTILINE)
        self.assertIsNotNone(app_id)
        self.assertNotEqual(app_id.group(1), "8A71E29B-7E5B-4A61-9E2E-B79A7F6EF5A1")
        self.assertIn(r"DefaultDirName={autopf}\Oni Thermal LCD Control Beta", installer)

    def test_sidebar_contract_version_is_not_release_version(self):
        runtime = (ROOT / "src/thermalright_lcd/gui.py").read_text(encoding="utf-8")
        self.assertIn('QLabel("v1.6.0")', runtime)

    def test_build_clean_is_scoped_to_repository(self):
        source = (ROOT / "packaging/build-portable.ps1").read_text(encoding="utf-8")
        self.assertIn("StartsWith($RepoRoot", source)
        self.assertNotIn("--hidden-import", source)
        self.assertNotIn("UPX", source.upper().replace("UPX=FALSE", ""))

    def test_dependency_notices_and_collection_are_present(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        collector = (ROOT / "packaging/collect_licenses.py").read_text(encoding="utf-8")
        for dependency in ("PySide6", "Pillow", "psutil", "opencv-python", "numpy"):
            self.assertIn(dependency.lower(), (notices + collector).lower())
        self.assertIn("third-party-licenses", collector)


if __name__ == "__main__":
    unittest.main()
