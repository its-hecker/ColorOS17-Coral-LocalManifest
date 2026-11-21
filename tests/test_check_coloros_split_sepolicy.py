"""Regression tests for read-only host split-policy compilation."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_coloros_split_sepolicy as split


class FakeExt4:
    absent = set()
    def __init__(self, image):
        self.role = "vendor" if image.name == "vendor-raw.img" else "coloros"

    def exists(self, path):
        if (self.role, path) in FakeExt4.absent:
            return False
        if path == "/etc/selinux/genfs_labels_version.txt":
            return False
        return (path.endswith(".cil") or path.endswith("plat_sepolicy_vers.txt"))

    def info(self, path):
        return {"type": "regular", "size": (7 if path.endswith(".txt") else 4)}

    def export_file(self, path, dest):
        dest.write_text("202604\n" if path.endswith(".txt") else "(a)\n")


class SplitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "engineering"
        self.out.mkdir()
        for name in ("system.img", "vendor-raw.img"):
            (self.out / name).write_bytes(b"synthetic")
        self.aosp = self.dir / "aosp"
        binary = self.aosp / "out/host/linux-x86/bin/secilc"
        binary.parent.mkdir(parents=True)
        binary.write_text("synthetic")
        FakeExt4.absent = set()

    def test_input_order_contains_base_policy_mapping_and_vendor(self):
        files = split.input_list("202604")
        self.assertEqual(files[0], (
            "coloros", "/system/etc/selinux/plat_sepolicy.cil", True))
        self.assertEqual(files[1], (
            "coloros", "/system/etc/selinux/mapping/202604.cil", True))
        self.assertIn(("vendor", "/etc/selinux/vendor_sepolicy.cil", True), files)
        self.assertIn(("vendor", "/etc/selinux/plat_pub_versioned.cil", True), files)

    def test_success_never_claims_enforcing_or_boot(self):
        def run(args, **kwargs):
            Path(args[args.index("-o") + 1]).write_bytes(b"policy")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(split, "Ext4", FakeExt4), \
             patch.object(split.subprocess, "run", side_effect=run):
            status = split.compile_policy(
                self.out, self.dir / "report", self.aosp, None)
        self.assertEqual(status, "HOST_CIL_COMPILES_RUNTIME_UNVERIFIED")
        report = json.loads((self.dir / "report/selinux-compile-report.json").read_text())
        self.assertFalse(report["boot_verified"])
        self.assertFalse(report["enforcing_selinux_verified"])
        self.assertFalse(report["images_modified"])

    def test_missing_platform_mapping_prevents_compilation(self):
        FakeExt4.absent = {
            ("coloros", "/system/etc/selinux/mapping/202604.cil"),
        }
        with patch.object(split, "Ext4", FakeExt4), \
             patch.object(split.subprocess, "run") as cmd:
            status = split.compile_policy(
                self.out, self.dir / "report", self.aosp)
        self.assertEqual(status, "MISSING_REQUIRED_CIL_INPUTS")
        cmd.assert_not_called()
        report = json.loads((self.dir / "report/selinux-compile-report.json").read_text())
        self.assertEqual(len(report["required_missing"]), 1)

    def test_compiler_failure_is_not_success(self):
        with patch.object(split, "Ext4", FakeExt4), \
             patch.object(split.subprocess, "run", return_value=SimpleNamespace(
                 returncode=1, stdout="", stderr="unknown type")):
            status = split.compile_policy(
                self.out, self.dir / "report", self.aosp, 33)
        self.assertEqual(status, "HOST_CIL_COMPILATION_FAILED")
        self.assertIn("unknown type", (self.dir / "report/secilc.log").read_text())


if __name__ == "__main__":
    unittest.main()
