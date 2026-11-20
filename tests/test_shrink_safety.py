import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "shrink_system", Path(__file__).resolve().parents[1] /
    "tools/shrink_system_ext4.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ShrinkGuardTests(unittest.TestCase):
    def test_non_ext4_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src.img", Path(tmp) / "out.img"
            src.write_bytes(b"NOT-EXT4" * 1024)
            with self.assertRaises(ValueError):
                mod.prepare(src, dst)
            self.assertFalse(dst.exists())

    def test_inplace_resize_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.img"
            src.write_bytes(b"irrelevant")
            with self.assertRaises(ValueError):
                mod.prepare(src, src)


if __name__ == "__main__":
    unittest.main()
