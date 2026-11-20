import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "avb_partition", ROOT / "tools/avb_partition_audit.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Audits(unittest.TestCase):
    def test_mismatch_flagged_not_silently_patched(self):
        b = """BOARD_AVB_VBMETA_SYSTEM := system system_ext product
BOARD_GOOGLE_DYNAMIC_PARTITIONS_PARTITION_LIST := \
 system product system_ext vendor
AB_OTA_PARTITIONS += system \
 system_ext product vendor
"""
        f = """system /system ext4 ro wait,first_stage_mount
# ColorOS17 embedded: product /product ext4 ro wait,first_stage_mount
# ColorOS17 embedded: system_ext /system_ext ext4 ro wait,first_stage_mount
vendor /vendor ext4 ro wait,first_stage_mount
"""
        report = mod.audit(b, f)
        self.assertEqual(report["status"], "BLOCKED_AVB_AND_SUPER_RECONCILIATION")
        self.assertEqual(report["existing_source_inconsistencies"][
            "vbmeta_system_descriptor_still_references_embedded"], ["product", "system_ext"])

    def test_reject_unmodified_product_fstab(self):
        b = "BOARD_AVB_VBMETA_SYSTEM := system product\n"
        f = "system /system ext4 ro wait,first_stage_mount\n" \
            "product /product ext4 ro wait,first_stage_mount\n" \
            "vendor /vendor ext4 ro wait,first_stage_mount\n"
        with self.assertRaises(ValueError):
            mod.audit(b, f)


if __name__ == "__main__":
    unittest.main()
