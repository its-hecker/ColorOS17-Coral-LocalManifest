"""Tests for finding exact genfscon duplicates without editing SELinux policy."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import diagnose_genfscon_collisions as d


class GenfsconTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.platform = self.root / "plat.cil"
        self.vendor = self.root / "vendor.cil"
        self.platform.write_text(
            "(genfscon proc /net (u object_r proc_net ((s0) (s0))))\n"
            "(genfscon sysfs /devices (u object_r sysfs_devices ((s0) (s0))))\n"
        )
        self.vendor.write_text(
            "(genfscon proc /net (u object_r vendor_proc_net ((s0) (s0))))\n"
            "(genfscon sysfs /devices (u object_r sysfs_devices ((s0) (s0))))\n"
            "(genfscon debugfs /clock (u object_r debugfs_clock ((s0) (s0))))\n"
        )
        self.report = self.root / "report.json"
        self.report.write_text(json.dumps({
            "status": "HOST_CIL_COMPILATION_FAILED",
            "cil_inputs": [
                {"role": "coloros",
                 "path": "/system/etc/selinux/plat_sepolicy.cil",
                 "host": str(self.platform)},
                {"role": "vendor",
                 "path": "/etc/selinux/vendor_sepolicy.cil",
                 "host": str(self.vendor)},
            ],
        }))

    def test_distinguishes_conflicting_and_identical_labels(self):
        old = self.platform.read_bytes(), self.vendor.read_bytes()
        report = d.scan(self.report)
        self.assertEqual(report["rules_scanned"], 5)
        self.assertEqual(report["duplicate_path_count"], 2)
        self.assertEqual(report["different_context_path_count"], 1)
        self.assertEqual(report["identical_context_path_count"], 1)
        self.assertEqual(report["different_context_examples"][0]["filesystem"], "proc")
        self.assertEqual(report["different_context_examples"][0]["path"], "/net")
        self.assertEqual(report["different_context_examples"][0]["declarations"][0]["line"], 1)
        self.assertEqual(old, (self.platform.read_bytes(), self.vendor.read_bytes()))
        self.assertFalse(report["cil_modified"])

    def test_unparsed_rule_is_reported(self):
        self.vendor.write_text("(genfscon broken)\n")
        report = d.scan(self.report)
        self.assertEqual(report["unparsed_rule_count"], 1)
        self.assertEqual(report["rules_scanned"], 2)

    def test_wrong_compilation_status_rejected(self):
        obj = json.loads(self.report.read_text())
        obj["status"] = "HOST_CIL_COMPILES_RUNTIME_UNVERIFIED"
        self.report.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError, "Expected original failed"):
            d.scan(self.report)


if __name__ == "__main__":
    unittest.main()
