"""Read-only boot-compat inventory regression tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import audit_coloros_boot_compat as inventory


class FakeFs:
    def __init__(self, image):
        self.image = image
    def exists(self, path):
        return path in ("/system/etc/vintf", "/etc/vintf") or (
            path in inventory.SELINUX_INPUTS[
                "coloros_system" if self.image.name == "system.img" else "pixel_vendor"]
            and path.endswith("property_contexts"))
    def info(self, path):
        return {"type": "directory"} if path in (
            "/system/etc/vintf", "/etc/vintf") else {"type": "regular", "size": 60}
    def children(self, path):
        return ["compatibility_matrix.xml"] if path == "/system/etc/vintf" else ["manifest.xml"]
    def export_file(self, path, destination):
        if path.endswith("compatibility_matrix.xml"):
            body = '<compatibility-matrix type="framework"><hal><name>android.hardware.foo</name></hal></compatibility-matrix>'
        else:
            body = '<manifest type="device"><hal><name>android.hardware.foo</name></hal></manifest>'
        destination.write_text(body)


class BootInventoryTests(unittest.TestCase):
    def test_xml_manifest(self):
        record = inventory.xml_inventory(
            b'<manifest type="device"><hal><name>android.hardware.camera.provider</name></hal></manifest>')
        self.assertEqual(record["type"], "device")
        self.assertEqual(record["hal_names"], ["android.hardware.camera.provider"])

    def test_incorrect_xml_root_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected root"):
            inventory.xml_inventory(b"<random/>")

    def test_inventory_does_not_claim_boot_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "engineering"
            out.mkdir()
            for name in ("system.img", "vendor-raw.img"):
                (out / name).write_bytes(b"synthetic")
            with patch.object(inventory, "Ext4", side_effect=FakeFs):
                result = inventory.audit(out, Path(tmp) / "reports")
            self.assertFalse(result["boot_compatibility_verified"])
            self.assertEqual(result["status"],
                             "VINTF_SELINUX_STATIC_INVENTORY_ONLY")
            self.assertEqual(len(result["partitions"]["coloros_system"]["vintf_files"]), 1)
            self.assertEqual(len(result["partitions"]["pixel_vendor"]["vintf_files"]), 1)
            report = json.loads(
                (Path(tmp) / "reports/boot-compat-inventory.json").read_text())
            self.assertFalse(report["boot_compatibility_verified"])


if __name__ == "__main__":
    unittest.main()
