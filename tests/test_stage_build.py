import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "stage_build", ROOT / "tools/stage_build.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StageTests(unittest.TestCase):
    def test_missing_image_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                m.image_info(Path(tmp) / "vendor.img")

    def test_regular_image_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vendor.img"
            path.write_bytes(b"12345")
            data = m.image_info(path)
            self.assertEqual(data["expanded_bytes"], 5)
            self.assertEqual(len(data["sha256"]), 64)

    def test_reports_do_not_claim_ready(self):
        self.assertTrue(any("super.img" in x for x in m.BLOCKERS))
        self.assertTrue(any("SELinux" in x for x in m.BLOCKERS))


if __name__ == "__main__":
    unittest.main()
