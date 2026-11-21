"""Fail-closed tests for building a separate ColorOS VINTF candidate image."""
import json
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
             patch.object(candidate.subprocess, "run",
                          return_value=SimpleNamespace(
                              stdout="COMPATIBLE\n", returncode=0)):
            matrix, report, entries = candidate.verify_candidate(
                self.candidate, self.aosp)
        self.assertEqual(matrix, self.xml)
        self.assertEqual(entries, expected)
        self.assertEqual(report["hal_entries_added"], 1)

    def test_candidate_changes_block_build(self):
        self.xml.write_text(self.xml.read_text().replace(
            "<version>1</version>", "<version>9</version>"))
        with self.assertRaisesRegex(ValueError, "does not match"):
            candidate.verify_candidate(self.candidate, self.aosp)

    def test_build_refuses_to_overwrite_previous_directory(self):
        out = self.root / "finished"
        out.mkdir()
        with self.assertRaisesRegex(ValueError, "already exists"):
            candidate.run_build(self.aosp, self.candidate,
                                self.root / "baseline", out)


if __name__ == "__main__":
    unittest.main()
