import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "prop_apply", ROOT / "tools/apply_property_contexts.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PropertyApplicationTests(unittest.TestCase):
    def test_only_systemext_and_product_contexts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            file = root / "product/etc/selinux/product_property_contexts"
            file.parent.mkdir(parents=True)
            file.write_text("test\n")
            self.assertEqual(m.ensure_safe(root, "product/etc/selinux/product_property_contexts"), file)

    def test_platform_context_overwrite_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            file = root / "system/etc/selinux/plat_property_contexts"
            file.parent.mkdir(parents=True)
            file.write_text("test\n")
            with self.assertRaises(ValueError):
                m.ensure_safe(root, "system/etc/selinux/plat_property_contexts")

    def test_parent_path_traversal_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                m.ensure_safe(root, "../danger")
