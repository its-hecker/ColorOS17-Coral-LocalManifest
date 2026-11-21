"""The VINTF runner cannot mistake an empty APEX view for a full result."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_coloros_vintf_base as check


class BaseVintfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.aosp = self.base / "aosp"
        binary = self.aosp / "out/host/linux-x86/bin/checkvintf"
        binary.parent.mkdir(parents=True)
        binary.write_text("fake")
        self.audit = self.base / "audit"
        self.audit.mkdir()
        self.inventory = {
            "partitions": {
                "coloros_system": {"vintf_files": [
                    {"xml_kind": "compatibility-matrix"}]},
                "pixel_vendor": {"vintf_files": [
                    {"xml_kind": "manifest"}]},
            }
        }
        (self.audit / "boot-compat-inventory.json").write_text(
            json.dumps(self.inventory))
        self.log = self.base / "base_vintf.log"

    def run_main(self, output, code=0):
        with patch.object(sys, "argv", [
            "check", "--aosp", str(self.aosp), "--audit", str(self.audit),
            "--log", str(self.log)]), patch.object(
                check.subprocess, "run", return_value=SimpleNamespace(
                    stdout=output, returncode=code)) as cmd:
            status = check.main()
        return status, cmd.call_args.args[0]

    def test_maps_apex_and_denies_full_certification(self):
        status, command = self.run_main("COMPATIBLE\n")
        self.assertEqual(status, 0)
        self.assertIn("/apex:" + str(self.audit / "vintf/_unavailable_apex"),
                      command)
        report = json.loads(self.log.with_suffix(".json").read_text())
        self.assertEqual(report["status"], "BASE_VINTF_COMPATIBLE_APEX_UNCHECKED")
        self.assertFalse(report["complete_vintf_compatibility_verified"])
        self.assertFalse(report["apex_fragments_checked"])
        self.assertFalse(report["boot_verified"])

    def test_separate_incompatibility_result(self):
        status, _ = self.run_main("INCOMPATIBLE\n", 65)
        self.assertEqual(status, 1)
        report = json.loads(self.log.with_suffix(".json").read_text())
        self.assertEqual(report["status"], "BASE_VINTF_INCOMPATIBLE_APEX_UNCHECKED")

    def test_framework_matrix_missing_fails_closed(self):
        self.inventory["partitions"]["coloros_system"]["vintf_files"] = []
        (self.audit / "boot-compat-inventory.json").write_text(
            json.dumps(self.inventory))
        with self.assertRaisesRegex(ValueError, "Incomplete VINTF inputs"):
            self.run_main("COMPATIBLE\n")


if __name__ == "__main__":
    unittest.main()
