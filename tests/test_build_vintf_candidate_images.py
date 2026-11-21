"""Fail-closed tests for building a separate ColorOS VINTF candidate image."""
import json
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_vintf_candidate_images as candidate


class VintfImageBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.xml = (self.candidate /
                    "vintf/coloros_system/system/etc/vintf/"
                    "compatibility_matrix.device.xml")
        self.xml.parent.mkdir(parents=True)
        self.xml.write_text(
            '<compatibility-matrix version="1.0" type="framework">'
            '<hal format="aidl" optional="true">'
            '<name>com.google.hardware.pixel.display</name>'
            '<version>1</version><interface>'
            '<name>IDisplay</name><instance>default</instance>'
            '</interface></hal></compatibility-matrix>')
        self.entries = [
            {"format": "aidl", "package": "com.google.hardware.pixel.display",
             "version": "1", "interface": "IDisplay", "instance": "default"}]
        (self.candidate / "candidate-report.json").write_text(json.dumps({
            "status": "CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED",
            "checker_exit_code": 0,
            "installed_into_image": False,
            "hal_entries_added": 1,
            "matched_vendor_manifest_instances": self.entries,
        }))
        self.aosp = self.root / "aosp"
        checker = self.aosp / "out/host/linux-x86/bin/checkvintf"
        checker.parent.mkdir(parents=True)
        checker.write_text("fake")

    def test_matrix_parser_accepts_single_reviewed_hal(self):
        found = candidate.candidate_entries(self.xml)
        self.assertEqual(found, {(
            "aidl", "com.google.hardware.pixel.display", "1",
            "IDisplay", "default")})

    def test_matrix_parser_rejects_mandatory_hal(self):
        self.xml.write_text(self.xml.read_text().replace(
            'optional="true"', 'optional="false"'))
        with self.assertRaisesRegex(ValueError, "mandatory"):
            candidate.candidate_entries(self.xml)

    def test_candidate_integrity_and_checker(self):
        expected = {("aidl", "com.google.hardware.pixel.display",
                     "1", "IDisplay", "default")}
        with patch.object(candidate, "read_vendor_hal_instances",
                          return_value=expected), \
             patch.object(candidate, "validate_matrix_delta_against_donor",
                          return_value=expected), \
             patch.object(candidate.subprocess, "run",
                          return_value=SimpleNamespace(
                              stdout="COMPATIBLE\n", returncode=0)):
            matrix, report, entries = candidate.verify_candidate(
                self.candidate, self.aosp, self.root / "donor.img")
        self.assertEqual(matrix, self.xml)
        self.assertEqual(entries, expected)
        self.assertEqual(report["hal_entries_added"], 1)

    def test_candidate_changes_block_build(self):
        self.xml.write_text(self.xml.read_text().replace(
            "<version>1</version>", "<version>9</version>"))
        expected = {("aidl", "com.google.hardware.pixel.display",
                     "1", "IDisplay", "default")}
        class EmptyDonor:
            def __init__(self, path):
                pass
            def exists(self, path):
                return False
        with patch.object(candidate, "Ext4", EmptyDonor), \
             self.assertRaisesRegex(ValueError, "differs from original"):
            candidate.validate_matrix_delta_against_donor(
                self.root / "donor.img", self.xml, expected)

    def test_unchanged_mandatory_donor_hal_is_preserved(self):
        expected = {("aidl", "com.google.hardware.pixel.display",
                     "1", "IDisplay", "default")}
        original = (
            '<compatibility-matrix version="1.0" type="framework">'
            '<hal format="hidl"><name>vendor.coloros.existing</name>'
            '<version>1.0</version><interface><name>IExisting</name>'
            '<instance>default</instance></interface></hal>'
            '</compatibility-matrix>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            before = (folder / "coloros_system/system/etc/vintf/"
                      "compatibility_matrix.device.xml")
            before.parent.mkdir(parents=True)
            before.write_text(original)
            generated = candidate.ensure_matrix(folder, sorted(expected))
            shutil.copyfile(generated, self.xml)

        class DonorWithExistingMatrix:
            def __init__(self, image):
                pass
            def exists(self, path):
                return path == candidate.DESTINATION
            def export_file(self, path, dst):
                dst.write_text(original)

        with patch.object(candidate, "Ext4", DonorWithExistingMatrix):
            self.assertEqual(
                candidate.validate_matrix_delta_against_donor(
                    self.root / "donor.img", self.xml, expected),
                expected)
        # A change to the preexisting mandatory HAL must be rejected.
        self.xml.write_text(self.xml.read_text().replace(
            "vendor.coloros.existing", "vendor.coloros.changed"))
        with patch.object(candidate, "Ext4", DonorWithExistingMatrix), \
             self.assertRaisesRegex(ValueError, "differs from original"):
            candidate.validate_matrix_delta_against_donor(
                self.root / "donor.img", self.xml, expected)

    def test_build_refuses_to_overwrite_previous_directory(self):
        out = self.root / "finished"
        out.mkdir()
        with self.assertRaisesRegex(ValueError, "already exists"):
            candidate.run_build(self.aosp, self.candidate,
                                self.root / "baseline", out)


if __name__ == "__main__":
    unittest.main()
