#!/usr/bin/env python3
"""Isolated, non-deployable test of two known ColorOS17/coral CIL collisions.

Only exported host CIL from a previous compilation report is read. A new
scratch copy of the vendor CIL is generated for secilc. The probe renames the
vendor-only hal_imsrtp domain and temporarily omits two genfscon
rules from that *scratch copy*. It never edits donor/vendor partitions,
regenerates an image, or changes production SELinux permissions.

Compilation success is ONLY a diagnostic and MUST NOT be deployed as a fix.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from diagnose_genfscon_collisions import GENFS, scan
from probe_imsrtp_cil_rename import NEW, DOMAIN_DECL, ATTR_DECL, TOKEN

EXPECTED = {
    ('sysfs', '/class/powercap'): ('sysfs_thermal', 'sysfs_powercap'),
    ('sysfs', '/devices/virtual/powercap'): ('sysfs_thermal', 'sysfs_powercap'),
}
CTX = re.compile(r'\(u\s+object_r\s+([A-Za-z0-9_]+)\s')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def genfs_key_context(line):
    match = GENFS.match(line)
    if not match:
        return None
    filesystem, path, rest = match.groups()
    context = CTX.search(rest)
    if not context:
        return None
    return (filesystem, path.strip('"')), context.group(1)


def prepare_probe(report_file, output_dir):
    report_file = report_file.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise ValueError('Refusing to overwrite an existing probe directory')
    report = json.loads(report_file.read_text())
    if report.get('status') != 'HOST_CIL_COMPILATION_FAILED':
        raise ValueError('Expected an original failed split-policy report')
    items = report.get('cil_inputs')
    if not isinstance(items, list) or not items:
        raise ValueError('Missing exported CIL provenance')
    for item in items:
        if not Path(item['host']).is_file():
            raise ValueError('Missing exported CIL: ' + str(item['host']))
    audit = scan(report_file)
    if audit['unparsed_rule_count'] or audit['identical_context_path_count']:
        raise ValueError('Unexpected unparsed or identical genfscon duplicates')
    if audit['different_context_path_count'] != len(EXPECTED):
        raise ValueError('Unexpected number of conflicting genfscon paths')
    for row in audit['different_context_examples']:
        key = (row['filesystem'], row['path'].strip('"'))
        if key not in EXPECTED or len(row['declarations']) != 2:
            raise ValueError('Unexpected conflicting genfscon path: ' + str(key))
        seen = set()
        for decl in row['declarations']:
            parsed = genfs_key_context(decl['declaration'])
            if parsed is None or parsed[0] != key:
                raise ValueError('Unexpected genfscon syntax')
            seen.add((decl['role'], parsed[1]))
        if seen != {('vendor', EXPECTED[key][0]), ('coloros', EXPECTED[key][1])}:
            raise ValueError('Unexpected label provenance: ' + str(key))
    vendor_inputs = [x for x in items if x.get('role') == 'vendor'
                     and x.get('path') == '/etc/selinux/vendor_sepolicy.cil']
    system_ext = [x for x in items if x.get('role') == 'coloros'
                  and x.get('path') == '/system_ext/etc/selinux/system_ext_sepolicy.cil']
    if len(vendor_inputs) != 1 or len(system_ext) != 1:
        raise ValueError('Required vendor/system_ext policy modules not unique')
    vendor = Path(vendor_inputs[0]['host'])
    original = vendor.read_bytes()
    source = original.decode('utf-8')
    coloros = Path(system_ext[0]['host']).read_text()
    if len(DOMAIN_DECL.findall(source)) != 1 or ATTR_DECL.search(source):
        raise ValueError('Unexpected vendor hal_imsrtp declaration')
    if not ATTR_DECL.search(coloros):
        raise ValueError('Missing ColorOS system_ext hal_imsrtp attribute conflict')
    if re.search(r'(?<![A-Za-z0-9_])' + re.escape(NEW) + r'(?![A-Za-z0-9_])', source):
        raise ValueError('Replacement domain already exists in vendor CIL')
    changed, occurrences = TOKEN.subn(NEW, source)
    if occurrences < 2 or DOMAIN_DECL.search(changed):
        raise ValueError('Vendor IMS domain rename probe failed')
    removed = {}
    kept = []
    for line in changed.splitlines(keepends=True):
        if '(genfscon ' in line:
            parsed = genfs_key_context(line)
            if parsed and parsed[0] in EXPECTED:
                key, label = parsed
                if label != EXPECTED[key][0] or key in removed:
                    raise ValueError('Unexpected duplicate vendor genfscon declaration')
                removed[key] = line.rstrip('\r\n')
                continue
        kept.append(line)
    if set(removed) != set(EXPECTED):
        raise ValueError('The two required vendor powercap rules were not found')
    rewritten = ''.join(kept).encode('utf-8')
    output_dir.mkdir(parents=True)
    staged = output_dir / 'vendor_sepolicy.cil.probe'
    staged.write_bytes(rewritten)
    if vendor.read_bytes() != original:
        raise ValueError('Original vendor policy changed during probe preparation')
    return report, items, vendor_inputs[0], staged, {
        'renamed_vendor_ims_token_occurrences': occurrences,
        'temporarily_omitted_vendor_genfscon': [
            {'filesystem': fs, 'path': path,
             'original_label': EXPECTED[(fs, path)][0],
             'coloros_label': EXPECTED[(fs, path)][1]}
            for fs, path in sorted(removed)
        ],
        'original_vendor_cil_sha256': sha256(original),
        'scratch_vendor_cil_sha256': sha256(rewritten),
        'source_cil_unchanged': True,
    }


def compile_probe(report_file, aosp, output_dir):
    aosp = aosp.resolve()
    binary = aosp / 'out/host/linux-x86/bin/secilc'
    if not binary.is_file():
        raise ValueError('Missing host secilc: ' + str(binary))
    report, inputs, vendor, staged, changes = prepare_probe(report_file, output_dir)
    target = output_dir / 'host-compiled-policy.bin'
    args = [str(binary), '-m', '-M', 'true', '-G', '-N']
    version = report.get('policy_version_override')
    if version is not None:
        if not isinstance(version, int) or not (15 <= version <= 40):
            raise ValueError('Invalid policy version')
        args.extend(['-c', str(version)])
    args += ['-o', str(target), '-f', '/dev/null']
    args += [str(staged) if x is vendor else x['host'] for x in inputs]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    logfile = output_dir / 'secilc-probe.log'
    logfile.write_text('SCRATCH CIL DIAGNOSTIC ONLY; NEVER A FLASHABLE POLICY\n\n'
                       + proc.stdout + '\n' + proc.stderr)
    compiled = proc.returncode == 0 and target.is_file() and target.stat().st_size > 0
    result = {
        'status': 'HOST_CIL_PROBE_COMPILED_RUNTIME_UNVERIFIED' if compiled
                  else 'HOST_CIL_PROBE_FAILED',
        'compiler_exit_code': proc.returncode,
        'compiler_log': str(logfile),
        'policy_version_override': version,
        'changes': changes,
        'source_tree_modified': False,
        'images_modified': False,
        'production_policy_modified': False,
        'boot_verified': False,
        'enforcing_selinux_verified': False,
        'warning': 'Proof of failure isolation only. Omitting vendor labels or renaming '
                   'a HAL domain in the shipped policy could break runtime access. '
                   'Do not flash or treat this host probe as a production fix.',
    }
    (output_dir / 'probe-report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--aosp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = compile_probe(a.report, a.aosp, a.output)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'HOST_CIL_PROBE_COMPILED_RUNTIME_UNVERIFIED' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, UnicodeError) as err:
        print('ERROR:', err, file=sys.stderr)
        sys.exit(2)
