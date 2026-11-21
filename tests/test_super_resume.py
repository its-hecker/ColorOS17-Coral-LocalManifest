"""Minimal-boot recovery: generated super metadata and signed-image resume."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_firstboot_images as port


class SuperResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.aosp = self.root / "aosp"
        self.packaging = (self.aosp / "out/target/product/coral/obj/PACKAGING")
        self.metadata = (self.packaging /
                         "super_empty_intermediates/misc_info.txt")
        self.metadata.parent.mkdir(parents=True)
        self.misc = (
            "super_metadata_device=super\n"
            "super_block_devices=super\n"
            "super_super_device_size=16106127360\n"
            "super_partition_groups=google_dynamic_partitions\n"
            "super_google_dynamic_partitions_group_size=8048869376\n"
            "ab_update=true\n"
            "super_partition_size=16106127360\n"
            "super_google_dynamic_partitions_partition_list=system vendor product system_ext\n"
        )
        self.metadata.write_text(self.misc)
        self.work = self.root / "work"
        board = self.work / "hardware/device/BoardConfig-common.mk"
        board.parent.mkdir(parents=True)
        board.write_text("BOARD_SUPER_PARTITION_SIZE := 16106127360\n"
                         "BOARD_GOOGLE_DYNAMIC_PARTITIONS_SIZE := 8048869376\n")

    def test_accepts_aosp_generated_super_empty_metadata(self):
        with patch.object(port, "WORK", self.work):
            info, source = port.load_base_misc(self.aosp)
        self.assertEqual(source, self.metadata)
        self.assertEqual(info["super_google_dynamic_partitions_group_size"],
                         "8048869376")
        self.assertEqual(info["ab_update"], "true")

    def test_geometry_mismatch_rejected(self):
        self.metadata.write_text(self.misc.replace(
            "super_super_device_size=16106127360\n",
            "super_super_device_size=16106127360\n").replace(
            "super_partition_size=16106127360",
            "super_partition_size=16000000000"))
        with patch.object(port, "WORK", self.work):
            with self.assertRaisesRegex(ValueError, "geometry differs"):
                port.load_base_misc(self.aosp)

    def test_missing_super_metadata_reports_recovery_command(self):
        self.metadata.unlink()
        with self.assertRaisesRegex(ValueError, "target-files-package"):
            port.load_base_misc(self.aosp)

    def test_signed_stage_reuses_without_modification(self):
        out = self.root / "engineering"
        (out / "propctx").mkdir(parents=True)
        donor = self.root / "donor.img"
        donor.write_bytes(b"original donor data")
        system = out / "system.img"
        system.write_bytes(donor.read_bytes() + b"appended verity hash tree")
        vendor = out / "vendor-raw.img"
        vendor.write_bytes(b"synthetic vendor")
        vbmeta = out / "vbmeta_system.img"
        vbmeta.write_bytes(b"signed test metadata")
        (out / "propctx/report.json").write_text(json.dumps({
            "status": "CANDIDATE_ONLY",
            "unmodified": [{"status": "no changes"}],
            "blocked": [],
        }))
        def avb_info(_avb, path):
            if Path(path) == vbmeta:
                return ("Rollback Index: 1793491200\n"
                        "Rollback Index Location: 0\nHashtree descriptor:\n")
            return "Rollback Index: 1793491200\nRollback Index Location: 0\n"
        with patch.object(port, "check_raw_ext4"), \
             patch.object(port, "avb_args", return_value=["avbtool"]), \
             patch.object(port, "avb_info", side_effect=avb_info), \
             patch.object(port, "run"):
            result = port.checked_resume_signed_minimal(out, self.aosp, donor)
        self.assertEqual(result[0], system)
        self.assertEqual(result[2], vbmeta)
        self.assertEqual(result[3]["rollback_location"], 0)
        self.assertEqual(system.read_bytes(), donor.read_bytes() +
                         b"appended verity hash tree")


if __name__ == "__main__":
    unittest.main()
