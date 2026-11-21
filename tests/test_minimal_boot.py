"""Minimal-boot CLI must skip optional APK requirements before image copying."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_firstboot_images as build


class MinimalBootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.rom = self.folder / "aosp"
        self.built = self.rom / "out/target/product/coral"
        self.built.mkdir(parents=True)
        (self.built / "vendor.img").write_bytes(b"not validated in check-only path")
        self.work = self.folder / "work"
        donor = self.work / "donor/system-for-inspection.img"
        donor.parent.mkdir(parents=True)
        data = bytearray(4096)
        data[1080:1082] = b"\x53\xef"
        donor.write_bytes(data)

    def test_minimal_check_inputs_skips_feature_apks(self):
        args = ["program", "--rom-root", str(self.rom),
                "--output", str(self.folder / "engineering"),
                "--rootless", "--minimal-boot", "--check-inputs-only"]
        output = io.StringIO()
        with patch.object(build, "WORK", self.work), \
             patch.object(sys, "argv", args), \
             contextlib.redirect_stdout(output):
            build.main()
        self.assertIn("MINIMAL_INPUTS_READY", output.getvalue())
        self.assertFalse((self.folder / "engineering").exists())

    def test_feature_profile_still_requires_motion_settings(self):
        args = ["program", "--rom-root", str(self.rom),
                "--output", str(self.folder / "engineering"),
                "--rootless", "--check-inputs-only"]
        with patch.object(build, "WORK", self.work), \
             patch.object(sys, "argv", args):
            with self.assertRaisesRegex(ValueError, "FloralMotionSenseSettings"):
                build.main()

    def test_minimal_rejects_privileged_mode(self):
        args = ["program", "--rom-root", str(self.rom),
                "--output", str(self.folder / "engineering"),
                "--minimal-boot", "--check-inputs-only"]
        with patch.object(build, "WORK", self.work), \
             patch.object(sys, "argv", args):
            with self.assertRaisesRegex(ValueError, "requires --rootless"):
                build.main()


if __name__ == "__main__":
    unittest.main()
