"""Regression tests for read-only APEX and SELinux inventory."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import audit_apex_selinux_inputs as audit


class FakeExt4:
    def __init__(self, file):
        self.role = "coloros" if file.name == "system.img" else "pixel_vendor"

    def exists(self, path):
        if path in ("/system/apex", "/apex"):
            return True
        if path.endswith(".sha256"):
            return True
        return path.endswith(("plat_sepolicy.cil", "vendor_sepolicy.cil"))

    def info(self, path):
        if path in ("/system/apex", "/apex"):
            return {"type": "directory"}
        return {"type": "regular", "size": 65}

    def children(self, path):
        if path == "/system/apex":
            return ["com.android.runtime.apex", "notes.txt"]
        return ["com.pixel.vendor.apex"]

    def export_file(self, path, dest):
        dest.write_text("a" * 64 + "\n")


class ApexSelinuxTests(unittest.TestCase):
    def test_apex_classification(self):
        fs = FakeExt4(Path("system.img"))
        inventory = audit.apex_inventory(fs, ["/system/apex", "/product/apex"])
        self.assertEqual(inventory[0]["apex_files"], ["com.android.runtime.apex"])
        self.assertEqual(inventory[0]["other_entries"], ["notes.txt"])
        self.assertFalse(inventory[1]["exists"])

    def test_hash_missing_is_not_match(self):
        class Missing(FakeExt4):
            def exists(self, path):
                return False
        self.assertIsNone(audit.small_file(Missing(Path("vendor.img")), "/hash"))

    def test_full_report_never_certifies_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for name in ("system.img", "vendor-raw.img"):
                (out / name).write_bytes(b"synthetic")
            with patch.object(audit, "Ext4", FakeExt4):
                result = audit.collect(out)
            self.assertFalse(result["boot_verified"])
            self.assertFalse(result["full_vintf_verified"])
            self.assertFalse(result["selinux_policy_compilation_verified"])
            self.assertEqual(
                [x["status"] for x in result["precompiled_policy_hashes"]],
                ["MATCH", "MATCH", "MATCH"])


if __name__ == "__main__":
    unittest.main()
