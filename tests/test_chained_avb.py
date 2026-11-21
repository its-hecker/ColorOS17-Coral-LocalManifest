"""Regression coverage for Android AVB chained rollback locations."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_firstboot_images as build


class ChainedAvbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.aosp = self.root / "aosp"
        self.key = self.aosp / "external/avb/test/data/testkey_rsa2048.pem"
        self.key.parent.mkdir(parents=True)
        self.key.write_bytes(b"synthetic-only")
        self.baseline = self.aosp / "out/target/product/coral"
        self.baseline.mkdir(parents=True)
        self.system = self.root / "donor.img"
        self.system.write_bytes(b"synthetic-ext4-test")
        self.output = self.root / "engineering"
        self.output.mkdir()

    def test_preflight_accepts_chain_one_with_header_zero(self):
        def info(_avb, image):
            if Path(image).name == "vbmeta.img":
                return "Flags: 0\n"
            if Path(image).name == "vbmeta_system.img":
                return "Rollback Index: 123\nRollback Index Location: 0\n"
            raise AssertionError(image)
        with patch.object(build, "avb_args", return_value=["avbtool"]), \
             patch.object(build, "avb_info", side_effect=info), \
             patch.object(build, "validate_root_vbmeta_chain", return_value="good-key"):
            result = build.avb_preflight(self.aosp)
        self.assertEqual(result["root_chain_location"], 1)
        self.assertEqual(result["chained_header_location"], 0)
        self.assertEqual(result["base_rollback_index"], 123)

    def test_preflight_rejects_nonzero_chained_header_location(self):
        def info(_avb, image):
            if Path(image).name == "vbmeta.img":
                return "Flags: 0\n"
            return "Rollback Index: 123\nRollback Index Location: 1\n"
        with patch.object(build, "avb_args", return_value=["avbtool"]), \
             patch.object(build, "avb_info", side_effect=info), \
             patch.object(build, "validate_root_vbmeta_chain", return_value="good-key"):
            with self.assertRaisesRegex(ValueError, "header rollback location 0"):
                build.avb_preflight(self.aosp)

    def test_signing_keeps_zero_header_and_original_rollback_index(self):
        calls = []
        def record(*args, **_kwargs):
            calls.append(list(map(str, args)))
            return ""
        def info(_avb, image):
            path = Path(image)
            if path.name == "vbmeta.img":
                return "Flags: 0\n"
            if path.name == "vbmeta_system.img" and self.baseline in path.parents:
                return "Rollback Index: 456\nRollback Index Location: 0\n"
            return "Hashtree descriptor:\n"
        with patch.object(build, "avb_args", return_value=["avbtool"]), \
             patch.object(build, "run", side_effect=record), \
             patch.object(build, "avb_info", side_effect=info), \
             patch.object(build, "validate_root_vbmeta_chain", return_value="good-key"):
            result = build.sign_system(self.aosp, self.system,
                                       self.output / "vbmeta_system.img",
                                       self.output)
        self.assertEqual(result["rollback_index"], 456)
        self.assertEqual(result["rollback_location"], 0)
        make = next(row for row in calls if "make_vbmeta_image" in row)
        self.assertEqual(make[make.index("--rollback_index_location") + 1], "0")
        self.assertEqual(make[make.index("--rollback_index") + 1], "456")


if __name__ == "__main__":
    unittest.main()
