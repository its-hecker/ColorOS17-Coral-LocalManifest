#!/usr/bin/env python3
"""Probe an IMS RTP domain-name collision without changing ROM images or sources.

A real ColorOS system_ext policy declares (typeattribute hal_imsrtp), while the
Pixel vendor policy declares (type hal_imsrtp). Copy only the exported vendor
CIL into an isolated work directory, rename *whole* vendor-domain identifiers,
and retry the same host secilc invocation. Never skip any policy modules,
remove type rules, suppress neverallows, alter hashes, or patch a signed image.
A successful probe is a diagnostic, NOT a deployable or boot-proven fix.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

OLD = "hal_imsrtp"
NEW = "pixel_imsrtp_domain"
DOMAIN_DECL = re.compile(r"\(type\s+hal_imsrtp\s*\)")
ATTR_DECL = re.compile(r"\(typeattribute\s+hal_imsrtp\s*\)")
TOKEN = re.compile(r"(?<![A-Za-z0-9_])hal_imsrtp(?![A-Za-z0-9_])")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_probe(report_file, aosp, output_dir):
    report_file, aosp, output_dir = (
        report_file.resolve(), aosp.resolve(), output_dir.resolve())
    original = json.loads(report_file.read_text())
    if original.get("status") != "HOST_CIL_COMPILATION_FAILED":
        raise ValueError("Expected failed host CIL compilation report")
    inputs = original.get("cil_inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("No exported CIL inputs in compilation report")
    compiler = aosp / "out/host/linux-x86/bin/secilc"
    if not compiler.is_file():
        raise ValueError("Missing secilc in AOSP host output")
    if output_dir.exists():
        raise ValueError("Refusing to overwrite existing probe directory")
    selected = [x for x in inputs
                if x.get("role") == "vendor"
                and x.get("path") == "/etc/selinux/vendor_sepolicy.cil"]
    if len(selected) != 1:
        raise ValueError("Expected exactly one Pixel vendor_sepolicy.cil")
    vendor = Path(selected[0]["host"])
    vendor_text = vendor.read_text()
    if len(DOMAIN_DECL.findall(vendor_text)) != 1 or ATTR_DECL.search(vendor_text):
        raise ValueError("Vendor CIL must contain exactly one domain TYPE declaration "
                         "and no competing typeattribute for " + OLD)
    has_system_ext_attr = False
    for item in inputs:
        if (item.get("role") == "coloros"
                and item.get("path") ==
                "/system_ext/etc/selinux/system_ext_sepolicy.cil"):
            text = Path(item["host"]).read_text()
            if ATTR_DECL.search(text):
                has_system_ext_attr = True
    if not has_system_ext_attr:
        raise ValueError("Missing verified ColorOS system_ext typeattribute conflict")
    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(NEW) +
                 r"(?![A-Za-z0-9_])", vendor_text):
        raise ValueError("Replacement domain name already used in original vendor CIL")
    rewritten, occurrences = TOKEN.subn(NEW, vendor_text)
    if occurrences < 2 or DOMAIN_DECL.search(rewritten):
        raise ValueError("Vendor-domain rename failed integrity checks")

    # Validate all inputs before creating output, then write just a temporary
    # copy of the single modified CIL. The other CIL modules stay unmodified.
    for item in inputs:
        if not Path(item["host"]).is_file():
            raise ValueError("Missing exported policy input " + item["host"])
    output_dir.mkdir(parents=True)
    probe_cil = output_dir / "vendor_sepolicy.cil.probe"
    probe_cil.write_text(rewritten)
    binary = output_dir / "host-compiled-policy.bin"
    args = [str(compiler), "-m", "-M", "true", "-G", "-N"]
    version = original.get("policy_version_override")
    if version is not None:
        if not isinstance(version, int) or not 15 <= version <= 40:
            raise ValueError("Bad policy version recorded in report")
        args += ["-c", str(version)]
    args += ["-o", str(binary), "-f", "/dev/null"]
    args += [str(probe_cil) if x is selected[0] else x["host"] for x in inputs]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    log_file = output_dir / "secilc-probe.log"
    log_file.write_text(
        "TEMPORARY CIL RENAME PROBE ONLY; original source/image unchanged\n\n"
        + proc.stdout + "\n" + proc.stderr)
    success = proc.returncode == 0 and binary.is_file() and binary.stat().st_size > 0
    result = {
        "status": ("HOST_CIL_RENAME_PROBE_COMPILED_RUNTIME_UNVERIFIED"
                   if success else "HOST_CIL_RENAME_PROBE_FAILED"),
        "replacement": {OLD: NEW},
        "vendor_token_occurrences_changed": occurrences,
        "original_vendor_sha256": sha256(vendor),
        "temporary_vendor_sha256": sha256(probe_cil),
        "original_vendor_policy_unchanged": sha256(vendor) ==
                                            hashlib.sha256(vendor_text.encode()).hexdigest(),
        "compiler_exit_code": proc.returncode,
        "secilc_log": str(log_file),
        "policy_version_override": version,
        "source_tree_modified": False,
        "signed_images_modified": False,
        "runtime_compatibility_verified": False,
        "boot_verified": False,
        "warning": "A policy type/typeattribute namespace probe only. "
                   "A successful compile does not authorize flashing, "
                   "nor demonstrate runtime telephony/HAL functionality.",
    }
    (output_dir / "probe-report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--aosp", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = compile_probe(args.report, args.aosp, args.output)
    print(json.dumps(result, indent=2))
    return 0 if result["status"].startswith("HOST_CIL_RENAME_PROBE_COMPILED") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(2)
