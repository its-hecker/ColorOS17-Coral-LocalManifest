import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "coloros_firstboot", ROOT / "tools/firstboot_preflight.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class DonorGeometryTests(unittest.TestCase):
    def test_inspected_system_only_ext4(self):
        lock = json.loads((ROOT / "sources.lock.json").read_text())
        self.assertEqual(mod.validate_donor(lock["donor"]), 6584750080)

    def test_unverified_packed_directories_rejected(self):
        donor = json.loads(json.dumps(mod.LOCK["donor"]))
        donor["internal_layout"]["fs_root_dirs"].remove("system_ext")
        with self.assertRaises(ValueError):
            mod.validate_donor(donor)

    def test_unknown_donor_digest_rejected(self):
        donor = json.loads(json.dumps(mod.LOCK["donor"]))
        donor["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            mod.validate_donor(donor)


if __name__ == "__main__":
    unittest.main()
