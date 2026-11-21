"""VINTF FCM candidate: match *exact* Pixel HAL versions, never modify images."""
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prepare_coloros_device_fcm as fcm


ERROR = """ERROR: files are incompatible: The following instances are in the device manifest but not specified in framework compatibility matrix:
    com.google.hardware.pixel.display.IDisplay/default (@1)
    hardware.google.bluetooth.sar@1.0::IBluetoothSar/default
    vendor.google.airbrush.manager@1.0::IAirbrushManager/default
    vendor.lineage.health.IChargingControl/default (@2)
Suggested fix:
1. Update deprecated HALs to the latest version.
INCOMPATIBLE
"""


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audit = self.root / "audit"
        self.export = self.audit / "vintf"
        vendor = self.export / "pixel_vendor/etc/vintf"
        system = self.export / "coloros_system/system/etc/vintf"
        vendor.mkdir(parents=True)
        system.mkdir(parents=True)
        (vendor / "manifest.xml").write_text(
            """<manifest version="2.0" type="device" target-level="7">
              <hal format="aidl"><name>com.google.hardware.pixel.display</name>
                <version>1</version><fqname>IDisplay/default</fqname></hal>
              <hal format="hidl"><name>hardware.google.bluetooth.sar</name>
                <transport>hwbinder</transport><version>1.0</version>
                <interface><name>IBluetoothSar</name><instance>default</instance></interface></hal>
              <hal format="hidl"><name>vendor.google.airbrush.manager</name>
                <fqname>@1.0::IAirbrushManager/default</fqname></hal>
              <hal format="aidl"><name>vendor.lineage.health</name>
                <version>2</version><fqname>IChargingControl/default</fqname></hal>
            </manifest>""")
        (system / "compatibility_matrix.7.xml").write_text(
            '<compatibility-matrix version="1.0" type="framework" level="7"/>')
        (self.audit / "boot-compat-inventory.json").write_text(json.dumps({
            "status": "VINTF_SELINUX_STATIC_INVENTORY_ONLY"
        }))
        self.log = self.root / "base.log"
        self.log.write_text(ERROR)
        self.aosp = self.root / "aosp"
        binary = self.aosp / "out/host/linux-x86/bin/checkvintf"
        binary.parent.mkdir(parents=True)
        binary.write_text("fake")

    def test_parses_aidl_and_hidl_exact(self):
        found = fcm.parse_missing_log(ERROR)
        self.assertEqual(len(found), 4)
        self.assertIn(
            ("aidl", "vendor.lineage.health", "2", "IChargingControl", "default"),
            found)
        self.assertIn(
            ("hidl", "hardware.google.bluetooth.sar", "1.0", "IBluetoothSar", "default"),
            found)

    def test_matches_real_manifest(self):
        actual = fcm.read_vendor_hal_instances(self.export / "pixel_vendor")
        self.assertTrue(set(fcm.parse_missing_log(ERROR)).issubset(actual))

    def test_candidate_writes_only_export_and_marks_partial(self):
        candidate = self.root / "candidate"
        with patch.object(fcm.subprocess, "run", return_value=SimpleNamespace(
                stdout="COMPATIBLE\n", stderr="", returncode=0)):
            report = fcm.generate(self.aosp, self.audit, self.log, candidate)
        self.assertEqual(report["hal_entries_added"], 4)
        self.assertEqual(report["status"],
                         "CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED")
        self.assertFalse(report["installed_into_image"])
        self.assertFalse(report["full_vintf_compatibility_verified"])
        target = candidate / "vintf/coloros_system/system/etc/vintf/compatibility_matrix.device.xml"
        self.assertTrue(target.is_file())
        xml = ET.parse(target).getroot()
        self.assertEqual(len(xml.findall("hal")), 4)
        self.assertTrue(all(hal.get("optional") == "true"
                            for hal in xml.findall("hal")))
        # Original extracted directory must remain unmodified.
        self.assertFalse(
            (self.export / "coloros_system/system/etc/vintf/compatibility_matrix.device.xml").exists())

    def test_version_mismatch_rejected(self):
        self.log.write_text(ERROR.replace("IChargingControl/default (@2)",
                                          "IChargingControl/default (@3)"))
        with self.assertRaisesRegex(ValueError, "not found"):
            fcm.generate(self.aosp, self.audit, self.log,
                         self.root / "bad-candidate")

    def test_ambiguous_error_lines_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            fcm.parse_missing_log(ERROR.replace(
                "    com.google.hardware.pixel.display.IDisplay/default (@1)",
                "    ?? malformed entry"))


if __name__ == "__main__":
    unittest.main()
