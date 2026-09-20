import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_frozen_entry_is_import_safe(self):
        source = (ROOT / "packaging/oni_gui_entry.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertTrue(any(isinstance(node, ast.If) for node in tree.body))
        self.assertIn("freeze_support()", source)

    def test_spec_includes_runtime_safety_data(self):
        source = (ROOT / "packaging/oni_thermal_lcd.spec").read_text(encoding="utf-8")
        for required in (
            "device-allowlist.json", "session-report.json",
            "pid5408-new-session-first-frame.json",
            "pid5302-same-session-first-frame.json",
        ):
            self.assertIn(required, source)
        self.assertIn('console=False', source)
        self.assertIn('ERROR_PROC_NOT_FOUND', source)
        self.assertIn('"ICUUC.DLL", "ICUDT78.DLL"', source)
        self.assertIn('upx=False', source)
        self.assertIn("COLLECT(", source)
        self.assertIn('name="."', source)

    def test_version_metadata_matches_project(self):
        metadata = (ROOT / "packaging/version_info.txt").read_text(encoding="utf-8")
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.1.0"', project)
        self.assertIn("StringStruct(u'ProductVersion', u'0.1.0')", metadata)
        self.assertIn("Oni Thermal LCD Control.exe", metadata)

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
