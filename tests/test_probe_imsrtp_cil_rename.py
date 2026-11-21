"""Fail closed on unexpected SELinux declarations; never mutate original CIL."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import probe_imsrtp_cil_rename as p


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.aosp = self.root / "aosp"
        binary = self.aosp / "out/host/linux-x86/bin/secilc"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"dummy")
        self.vendor = self.root / "vendor.cil"
        self.vendor.write_text(
            "(type hal_imsrtp)\n"
            "(roletype object_r hal_imsrtp)\n"
            "(allow radio hal_imsrtp (binder (call)))\n"
            "(type hal_imsrtp_exec)\n")
        self.coloros = self.root / "systemext.cil"
        self.coloros.write_text("(typeattribute hal_imsrtp)\n")
        self.report = self.root / "selinux-compile-report.json"
        self.report.write_text(json.dumps({
            "status": "HOST_CIL_COMPILATION_FAILED",
            "policy_version_override": None,
            "cil_inputs": [
                {"role": "coloros",
                 "path": "/system_ext/etc/selinux/system_ext_sepolicy.cil",
                 "host": str(self.coloros)},
                {"role": "vendor", "path": "/etc/selinux/vendor_sepolicy.cil",
                 "host": str(self.vendor)},
            ],
        }))
        self.out = self.root / "probe"

    def test_rewrite_only_exact_domain_symbol(self):
        original = self.vendor.read_bytes()
        def fake_run(args, **kwargs):
            Path(args[args.index("-o") + 1]).write_bytes(b"compiled")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(p.subprocess, "run", side_effect=fake_run):
            result = p.compile_probe(self.report, self.aosp, self.out)
        self.assertEqual(result["status"],
                         "HOST_CIL_RENAME_PROBE_COMPILED_RUNTIME_UNVERIFIED")
        self.assertEqual(result["vendor_token_occurrences_changed"], 3)
        self.assertEqual(self.vendor.read_bytes(), original)
        staged = (self.out / "vendor_sepolicy.cil.probe").read_text()
        self.assertIn("(type pixel_imsrtp_domain)", staged)
        self.assertIn("(type hal_imsrtp_exec)", staged)
        self.assertFalse(result["signed_images_modified"])

    def test_missing_conflicting_attribute_rejected(self):
        self.coloros.write_text("(typeattribute another_hal)\n")
        with self.assertRaisesRegex(ValueError, "Missing verified"):
            p.compile_probe(self.report, self.aosp, self.out)
        self.assertFalse(self.out.exists())

    def test_multiple_vendor_types_rejected(self):
        self.vendor.write_text(self.vendor.read_text() + "(type hal_imsrtp)\n")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            p.compile_probe(self.report, self.aosp, self.out)
        self.assertFalse(self.out.exists())

    def test_output_must_be_new(self):
        self.out.mkdir()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            p.compile_probe(self.report, self.aosp, self.out)


if __name__ == "__main__":
    unittest.main()
