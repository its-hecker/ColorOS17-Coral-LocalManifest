import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_device",
    ROOT / "tools/prepare_device.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PrepareTests(unittest.TestCase):
    def test_hash_deterministic(self):
        self.assertEqual(m.digest(b"a"), m.digest(b"a"))
        self.assertNotEqual(m.digest(b"a"), m.digest(b"b"))
    def test_refuses_missing_checkout(self):
        with self.assertRaises(ValueError):
            m.prepare(Path("/missing/rom"), ROOT / "work/missing-test")
