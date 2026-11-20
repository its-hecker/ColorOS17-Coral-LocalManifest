import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "partition_budget", Path(__file__).resolve().parents[1] /
    "tools/partition_budget.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class BudgetTests(unittest.TestCase):
    def test_known_gsi_cannot_prove_fit_without_other_images(self):
        sizes = {"system": 6584750080, "vendor": None,
                 "product": None, "system_ext": None}
        r = mod.assess(8048869376, sizes)
        self.assertEqual(r["status"], "BLOCKED_UNMEASURED")
        self.assertEqual(r["remaining_after_reservation_bytes"], 1430564864)

    def test_oversize_fails(self):
        sizes = {"system": 6584750080, "vendor": 1400000000,
                 "product": 300000000, "system_ext": 100000000}
        self.assertEqual(mod.assess(8048869376, sizes)["status"], "BLOCKED_OVERSIZE")

    def test_fits_only_as_geometry(self):
        sizes = {"system": 400, "vendor": 200, "product": 100, "system_ext": 100}
        self.assertEqual(mod.assess(1000, sizes, reserve=100)["status"], "FITS_BYTES_ONLY")

    def test_sparse_uses_expanded_size(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "x.img"
            file.write_bytes(struct.pack("<IHHHHIIII", mod.SPARSE_MAGIC, 1, 0,
                                         28, 12, 4096, 100, 0, 0))
            self.assertEqual(mod.image_bytes(file), 409600)


if __name__ == "__main__":
    unittest.main()
