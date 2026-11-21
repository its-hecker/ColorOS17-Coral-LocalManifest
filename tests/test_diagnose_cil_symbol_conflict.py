"""Ensure CIL conflict diagnosis preserves evidence and does not patch policies."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import diagnose_cil_symbol_conflict as d


class CilConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.platform = self.root / "plat.cil"
        self.vendor = self.root / "vendor.cil"
        self.platform.write_text("(typeattribute hal_imsrtp)\n")
        self.vendor.write_text("; comment\n(type hal_imsrtp)\n")
        log = self.root / "secilc.log"
        log.write_text("Re-declaration of type hal_imsrtp\nFailed to build AST\n")
        self.report = self.root / "selinux-compile-report.json"
        self.report.write_text(json.dumps({
            "status": "HOST_CIL_COMPILATION_FAILED", "log": str(log),
            "cil_inputs": [
                {"role": "coloros", "path": "/system/etc/selinux/plat_sepolicy.cil",
                 "host": str(self.platform)},
                {"role": "vendor", "path": "/etc/selinux/vendor_sepolicy.cil",
                 "host": str(self.vendor)},
            ],
        }))

    def test_cross_kind_collision_reports_paths_and_lines(self):
        result = d.diagnose(self.report)
        self.assertEqual(result["symbol"], "hal_imsrtp")
        self.assertEqual(result["status"], "TYPE_TYPEATTRIBUTE_CONFLICT_FOUND")
        self.assertEqual(len(result["declarations"]), 2)
        self.assertEqual(result["declarations"][0]["kind"], "typeattribute")
        self.assertEqual(result["declarations"][1]["line"], 2)
        self.assertFalse(result["policy_fixed"])

    def test_missing_type_decl_does_not_claim_fix(self):
        self.vendor.write_text("(type some_other_symbol)\n")
        result = d.diagnose(self.report)
        self.assertEqual(result["status"], "DECLARATION_INVENTORY_INCONCLUSIVE")
        self.assertFalse(result["boot_verified"])

    def test_unexpected_report_rejected(self):
        blob = json.loads(self.report.read_text())
        blob["status"] = "HOST_CIL_COMPILES_RUNTIME_UNVERIFIED"
        self.report.write_text(json.dumps(blob))
        with self.assertRaisesRegex(ValueError, "Expected a failed"):
            d.diagnose(self.report)

    def test_bad_symbol_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid CIL symbol"):
            d.diagnose(self.report, "../invalid")


if __name__ == "__main__":
    unittest.main()
