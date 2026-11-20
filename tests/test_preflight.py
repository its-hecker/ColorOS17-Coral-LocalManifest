"""Offline, synthetic tests: never download firmware or flash a phone."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


bootstrap = module("coloros_bootstrap", ROOT / "tools" / "bootstrap.py")
donor = module("coloros_donor", ROOT / "tools" / "donor.py")


class LockTests(unittest.TestCase):
    def test_locked_sources(self):
        lock = json.loads((ROOT / "sources.lock.json").read_text())
        bootstrap.validate(lock["sources"])
        ids = {item["id"] for item in lock["sources"]}
        self.assertTrue({"device-base", "vendor-base", "kernel-base",
                         "gcam", "faceid", "motionsense"}.issubset(ids))
        self.assertEqual(lock["donor"]["expected_android_major"], 17)


class ArchiveTests(unittest.TestCase):
    def test_sparse_image_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "donor.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("images/system.img", b"\x3a\xff\x26\xed" + b"\x00" * 5000)
            report = donor.inspect_zip(path)
            self.assertEqual(report["zip_entries"], 1)
            self.assertEqual(report["images"][0]["image_format"], "android-sparse")
            self.assertIn("NO port", report["stage"])

    def test_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("../escape.img", b"\x00" * 2048)
            with self.assertRaises(ValueError):
                donor.inspect_zip(path)

    def test_filesystem_magic(self):
        erofs = b"\x00" * 1024 + b"\xe2\xe1\xf5\xe0"
        self.assertEqual(donor.kind_from_prefix(erofs), "erofs")
        ext4 = b"\x00" * 1080 + b"\x53\xef"
        self.assertEqual(donor.kind_from_prefix(ext4), "ext4")


if __name__ == "__main__":
    unittest.main()
