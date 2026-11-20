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
