import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("donor_interfaces", ROOT /
    "tools/audit_donor_interfaces.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MatrixTests(unittest.TestCase):
    def test_required_and_optional_hals(self):
        xml = """<compatibility-matrix version="1.0" type="framework">
        <hal format="hidl"><name>android.hardware.camera.provider</name>
          <version>2.4</version></hal>
        <hal optional="true" format="aidl"><name>android.hardware.foo</name>
          <version>1</version></hal></compatibility-matrix>"""
        data = m.parse_hals(xml)
        self.assertEqual(data["android.hardware.camera.provider"][0]["versions"], ["2.4"])
        self.assertEqual(data["android.hardware.foo"][0]["optional"], "true")

    def test_dynamic_framework_matrix_paths(self):
        lists = {
            "/system/etc/vintf": ["manifest.xml",
                                   "compatibility_matrix.2026.xml",
                                   "compatibility_matrix.device.xml"],
            "/system_ext/etc/vintf": ["compatibility_matrix.xml"],
            "/product/etc/vintf": None,
        }
        self.assertEqual(m.matrix_paths_from_listings(lists), [
            "/system/etc/vintf/compatibility_matrix.2026.xml",
            "/system/etc/vintf/compatibility_matrix.device.xml",
            "/system_ext/etc/vintf/compatibility_matrix.xml"
        ])

    def test_target_level_7_not_all_matrices(self):
        manifest = '<manifest type="device" target-level="7"/>'
        matrices = {
            "/system/etc/vintf/compatibility_matrix.7.xml":
                m.parse_hals('<compatibility-matrix><hal format="hidl"><name>android.hardware.audio</name><version>7.0</version></hal></compatibility-matrix>'),
            "/system/etc/vintf/compatibility_matrix.8.xml":
                m.parse_hals('<compatibility-matrix><hal format="aidl"><name>android.hardware.audio.core</name><version>1</version></hal></compatibility-matrix>')
        }
        level, path, details = m.audit_target_level(manifest, matrices)
        self.assertEqual(level, "7")
        self.assertEqual(path, "/system/etc/vintf/compatibility_matrix.7.xml")
        self.assertEqual(details[path]["total_hal_names"], 1)

    def test_missing_device_target_level_blocks(self):
        with self.assertRaises(ValueError):
            m.audit_target_level('<manifest type="device"/>', {})

    def test_no_raw_properties_leaked(self):
        raw = """ro.build.version.sdk=37
persist.security.key=secret
ro.build.version.release=17
"""
        props = m.parse_props(raw)
        self.assertEqual(props["ro.build.version.release"], "17")
        self.assertNotIn("persist.security.key", props)

    def test_missing_xml_fails_closed(self):
        with self.assertRaises(ValueError):
            m.parse_hals("<hal")


if __name__ == "__main__":
    unittest.main()
