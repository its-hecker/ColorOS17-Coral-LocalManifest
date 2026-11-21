"""Isolated 202604 powercap genfscon + IMS symbol collision tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import probe_powercap_genfscon as probe


class PowercapProbeTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.aosp = self.root / 'aosp'
        secilc = self.aosp / 'out/host/linux-x86/bin/secilc'
        secilc.parent.mkdir(parents=True)
        secilc.write_bytes(b'fake')
        self.vendor = self.root / 'vendor.cil'
        self.vendor.write_text('''(type hal_imsrtp)
(allow hal_imsrtp radio (binder (call)))
(genfscon sysfs "/class/powercap" (u object_r sysfs_thermal ((s0) (s0))))
(genfscon sysfs "/devices/virtual/powercap" (u object_r sysfs_thermal ((s0) (s0))))
(genfscon proc /net (u object_r proc_net ((s0) (s0))))
''')
        self.system = self.root / 'plat.cil'
        self.system.write_text('''(genfscon sysfs "/class/powercap" (u object_r sysfs_powercap ((s0) (s0))))
(genfscon sysfs "/devices/virtual/powercap" (u object_r sysfs_powercap ((s0) (s0))))
''')
        self.systemext = self.root / 'systemext.cil'
        self.systemext.write_text('(typeattribute hal_imsrtp)\n')
        self.report = self.root / 'original.json'
        self.report.write_text(json.dumps({
            'status': 'HOST_CIL_COMPILATION_FAILED',
            'policy_version_override': None,
            'cil_inputs': [
                {'role': 'coloros', 'path': '/system/etc/selinux/plat_sepolicy_genfs_202604.cil',
                 'host': str(self.system)},
                {'role': 'coloros', 'path': '/system_ext/etc/selinux/system_ext_sepolicy.cil',
                 'host': str(self.systemext)},
                {'role': 'vendor', 'path': '/etc/selinux/vendor_sepolicy.cil',
                 'host': str(self.vendor)},
            ],
        }))
        self.out = self.root / 'probe'

    def test_probe_only_changes_scratch_and_compiles(self):
        original = [f.read_bytes() for f in [self.vendor, self.system, self.systemext]]
        def fake_run(args, **kwargs):
            Path(args[args.index('-o') + 1]).write_bytes(b'compiled')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(probe.subprocess, 'run', side_effect=fake_run):
            report = probe.compile_probe(self.report, self.aosp, self.out)
        self.assertEqual(report['status'], 'HOST_CIL_PROBE_COMPILED_RUNTIME_UNVERIFIED')
        self.assertEqual(len(report['changes']['temporarily_omitted_vendor_genfscon']), 2)
        self.assertEqual(original, [f.read_bytes() for f in [self.vendor, self.system, self.systemext]])
        scratch = (self.out / 'vendor_sepolicy.cil.probe').read_text()
        self.assertIn('(type pixel_imsrtp_domain)', scratch)
        self.assertIn('(genfscon proc /net', scratch)
        self.assertNotIn('/class/powercap', scratch)
        self.assertNotIn('/devices/virtual/powercap', scratch)

    def test_mismatched_labels_rejected(self):
        self.vendor.write_text(self.vendor.read_text().replace('sysfs_thermal', 'sysfs_wrong'))
        with self.assertRaisesRegex(ValueError, 'Unexpected label provenance'):
            probe.prepare_probe(self.report, self.out)
        self.assertFalse(self.out.exists())

    def test_extra_conflict_rejected(self):
        with self.vendor.open('a') as file:
            file.write('(genfscon proc /bad (u object_r vendor_label ((s0) (s0))))\n')
        with self.system.open('a') as file:
            file.write('(genfscon proc /bad (u object_r platform_label ((s0) (s0))))\n')
        with self.assertRaisesRegex(ValueError, 'Unexpected number'):
            probe.prepare_probe(self.report, self.out)
        self.assertFalse(self.out.exists())

    def test_existing_output_rejected(self):
        self.out.mkdir()
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            probe.prepare_probe(self.report, self.out)


if __name__ == '__main__':
    unittest.main()
