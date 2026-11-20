import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "runtime_dependencies", ROOT / "tools/pixel_runtime_dependencies.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RuntimeDependenciesTests(unittest.TestCase):
    def test_missing_source_stays_review_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = mod.audit(root)
            self.assertEqual(report["status"], "PLAN_ONLY_NOT_INSTALLED")
            self.assertEqual(report["dependencies_present"], 0)
            self.assertGreater(report["dependencies_checked"], 10)

    def test_present_file_is_not_marked_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "proprietary/system_ext/framework/google-ril.jar"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"fake-file-for-test")
            report = mod.audit(root)
            found = next(x for x in report["candidates"]
                         if x["destination"] == "/system_ext/framework/google-ril.jar")
            self.assertTrue(found["present"])
            self.assertEqual(found["action"], "REVIEW_DONOR_COLLISION_AND_PERMISSIONS")


if __name__ == "__main__":
    unittest.main()
