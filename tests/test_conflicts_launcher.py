import unittest
from pathlib import Path

from thermalright_lcd.conflicts import thermalright_processes


ROOT = Path(__file__).resolve().parents[1]


class FakeProcessApi:
    def __init__(self, entries=(), *, snapshot_error=False, first_error=False, next_error=False):
        self.entries = list(entries)
        self.snapshot_error = snapshot_error
        self.first_error = first_error
        self.next_error = next_error
        self.index = 0
        self.closed = []

    def snapshot(self):
        if self.snapshot_error:
            raise OSError("snapshot failed")
        return 123

    def first(self, _snapshot):
        if self.first_error:
            raise OSError("first failed")
        if not self.entries:
            raise OSError("empty snapshot")
        self.index = 1
        return self.entries[0][:2]

    def next(self, _snapshot):
        if self.next_error:
            raise OSError("next failed")
        if self.index >= len(self.entries):
            return None
        entry = self.entries[self.index]
        self.index += 1
        return entry[:2]

    def path(self, process_id):
        for _executable, candidate_id, path in self.entries:
            if candidate_id == process_id:
                return path
        return None

    def close(self, handle):
        self.closed.append(handle)


class ConflictAndLauncherTests(unittest.TestCase):
    def test_no_conflicting_process(self):
        api = FakeProcessApi([("explorer.exe", 1, "C:/Windows/explorer.exe")])
        self.assertEqual(thermalright_processes(api), [])
        self.assertEqual(api.closed, [123])

    def test_each_configured_conflict_is_detected(self):
        for name in ("TRCC", "USBLCD", "USBLCDNEW"):
            with self.subTest(name=name):
                result = thermalright_processes(FakeProcessApi([(name + ".exe", 42, f"C:/{name}.exe")]))
                self.assertEqual(result, [{"ProcessName": name, "Id": 42, "Path": f"C:/{name}.exe"}])

    def test_matching_is_case_insensitive_and_exe_is_optional(self):
        api = FakeProcessApi([("trcc.EXE", 2, "C:/trcc.EXE"), ("UsBlCdNeW", 3, None)])
        self.assertEqual([item["Id"] for item in thermalright_processes(api)], [2, 3])

    def test_unrelated_process_is_ignored(self):
        api = FakeProcessApi([("USBLCD-helper.exe", 4, None), ("lcd.exe", 5, None)])
        self.assertEqual(thermalright_processes(api), [])

    def test_multiple_and_duplicate_names_are_preserved_by_pid(self):
        api = FakeProcessApi([("TRCC.exe", 6, "a"), ("TRCC.exe", 7, "b"), ("USBLCD.exe", 8, "c")])
        self.assertEqual([item["Id"] for item in thermalright_processes(api)], [6, 7, 8])

    def test_snapshot_failure_returns_empty_without_close(self):
        api = FakeProcessApi(snapshot_error=True)
        self.assertEqual(thermalright_processes(api), [])
        self.assertEqual(api.closed, [])

    def test_first_failure_returns_empty_and_closes_snapshot(self):
        api = FakeProcessApi(first_error=True)
        self.assertEqual(thermalright_processes(api), [])
        self.assertEqual(api.closed, [123])

    def test_next_failure_keeps_completed_matches_and_closes_snapshot(self):
        api = FakeProcessApi([("TRCC.exe", 9, None)], next_error=True)
        self.assertEqual([item["Id"] for item in thermalright_processes(api)], [9])
        self.assertEqual(api.closed, [123])

    def test_launcher_pins_working_gui_runtime_and_safe_smoke_mode(self):
        text = (ROOT / "run-gui.bat").read_text(encoding="utf-8")
        self.assertIn("py -3.12", text)
        self.assertIn("ONI_LCD_GUI_SMOKE_TEST", text)
        self.assertNotIn("--send", text)
