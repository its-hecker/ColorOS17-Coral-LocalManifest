import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_firstboot", ROOT / "tools/build_firstboot_images.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AssemblyTests(unittest.TestCase):
    def test_avb_details_parse(self):
        self.assertEqual(m.parse_avb_value("Flags: 0\nRollback Index: 123\n",
                                            "Rollback Index"), 123)
        with self.assertRaises(ValueError):
            m.parse_avb_value("Flags: 0\n", "Rollback Index")

    def test_staging_refuses_wrong_ext4(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "fake.img"
            bad.write_bytes(b"not an image")
            with self.assertRaises(ValueError):
                m.check_raw_ext4(bad)

    def test_selected_pixel_dependencies_present(self):
        self.assertTrue({"FloralGoogleCamera", "FloralMotionSenseBridge",
                         "FloralMotionSenseSettings",
                         "FloralOsloFeedback", "ims"}.issubset(m.PIXEL_REQUIRED))

    def test_unknown_images_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "candidate.img"
            fake.write_bytes(b"already here")
            with self.assertRaises(ValueError):
                m.disk_image(fake, fake, "/bin/false")


if __name__ == "__main__":
    unittest.main()
