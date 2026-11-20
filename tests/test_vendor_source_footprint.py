import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "vendor_footprint", HERE / "tools/vendor_source_footprint.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FootprintTests(unittest.TestCase):
    def test_lfs_size_is_logical_not_pointer_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Path(temp) / "blob"
            f.write_bytes(b"version https://git-lfs.github.com/spec/v1\n"
                          + b"oid sha256:" + b"0" * 64 + b"\nsize 98432101\n")
            self.assertEqual(m.source_bytes(f), (98432101, "lfs_pointer"))

    def test_invalid_pointer_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Path(temp) / "bad"
            f.write_bytes(b"version https://git-lfs.github.com/spec/v1\n"
                          b"oid sha256:" + b"0" * 64 + b"\n")
            with self.assertRaises(ValueError):
                m.source_bytes(f)

    def test_ordinary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Path(temp) / "ordinary"
            f.write_bytes(b"abcd")
            self.assertEqual(m.source_bytes(f), (4, "ordinary"))


if __name__ == "__main__":
    unittest.main()
