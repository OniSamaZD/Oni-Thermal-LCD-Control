import subprocess, sys
from pathlib import Path
import unittest

class UiLockTests(unittest.TestCase):
    def test_approved_interface_contract_is_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "ui_lock.py"), "check"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

if __name__ == "__main__":
    unittest.main()
