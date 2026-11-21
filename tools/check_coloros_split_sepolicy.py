#!/usr/bin/env python3
"""Read-only host-side attempt to compile split ColorOS/Pixel SELinux CIL.

Uses the same principal CIL inputs and secilc flags as Android init's
OpenSplitPolicy(), with a host binary and temporary exported image files.
Never patches policies, their hashes, ext4 images, AVB, or a physical device.
A successful host compile is NOT a validated runtime boot/enforcing verdict.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from rootless_ext4 import Ext4

SAFE_VERSION = re.compile(r"^[0-9]{4,8}$")
MAX_CIL_BYTES = 128 * 1024 * 1024


def read_version(fs, path):
    if not fs.exists(path):
        raise ValueError("Missing vendor platform mapping version " + path)
    node = fs.info(path)
    if node["type"] != "regular" or node["size"] > 1024:
        raise ValueError("Unexpected mapping version file metadata: " + path)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="coloros17-platvers-") as temp:
        target = Path(temp) / "version.txt"
        fs.export_file(path, target)
        version = target.read_text().strip()
    if not SAFE_VERSION.fullmatch(version):
        raise ValueError("Invalid vendor policy mapping version: " + repr(version))
    return version


def input_list(version, genfs_version=None):
    """Follow init/selinux.cpp ordering; empty optional entries are skipped."""
    return [
        ("coloros", "/system/etc/selinux/plat_sepolicy.cil", True),
        ("coloros", f"/system/etc/selinux/mapping/{version}.cil", True),
        ("coloros", f"/system/etc/selinux/mapping/{version}.compat.cil", False),
        ("coloros", "/system_ext/etc/selinux/system_ext_sepolicy.cil", False),
        ("coloros", f"/system_ext/etc/selinux/mapping/{version}.cil", False),
        ("coloros", f"/system_ext/etc/selinux/mapping/{version}.compat.cil", False),
        ("coloros", "/product/etc/selinux/product_sepolicy.cil", False),
        ("coloros", f"/product/etc/selinux/mapping/{version}.cil", False),
        ("vendor", "/etc/selinux/plat_pub_versioned.cil", True),
        ("vendor", "/etc/selinux/vendor_sepolicy.cil", True),
        ("coloros", "/odm/etc/selinux/odm_sepolicy.cil", False),
    ] + ([("coloros", f"/system/etc/selinux/plat_sepolicy_genfs_{genfs_version}.cil", False)]
         if genfs_version else [])


def export_cil(fs, path, destination):
    info = fs.info(path)
    if info["type"] != "regular" or not 0 < info["size"] < MAX_CIL_BYTES:
        raise ValueError("Invalid CIL input metadata: " + path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fs.export_file(path, destination)
    if destination.stat().st_size != info["size"]:
        raise ValueError("Exported CIL size differs from ext4 metadata: " + path)


def compile_policy(out, reportdir, aosp, policy_version=None):
    out, reportdir, aosp = out.resolve(), reportdir.resolve(), aosp.resolve()
    system_img = out / "system.img"
    vendor_img = out / "vendor-raw.img"
    secilc = aosp / "out/host/linux-x86/bin/secilc"
    for p in (system_img, vendor_img, secilc):
        if not p.is_file():
            raise ValueError("Required input not found: " + str(p))
    if reportdir.exists():
        raise ValueError("Choose a fresh report directory: " + str(reportdir))
    reportdir.mkdir(parents=True)
    fs = {"coloros": Ext4(system_img), "vendor": Ext4(vendor_img)}
    vendor_vers = read_version(fs["vendor"], "/etc/selinux/plat_sepolicy_vers.txt")
    genfs_path = "/etc/selinux/genfs_labels_version.txt"
    genfs_version = (read_version(fs["vendor"], genfs_path)
                     if fs["vendor"].exists(genfs_path) else None)
    requested = input_list(vendor_vers, genfs_version)
    selected, missing_required, missing_optional = [], [], []
    for role, path, required in requested:
        if fs[role].exists(path):
            dest = reportdir / "cil" / role / path.lstrip("/")
            export_cil(fs[role], path, dest)
            selected.append({"role": role, "path": path, "host": str(dest),
                             "size": dest.stat().st_size})
        elif required:
            missing_required.append({"role": role, "path": path})
        else:
            missing_optional.append({"role": role, "path": path})
    log = reportdir / "secilc.log"
    output = reportdir / "sepolicy-host-compiled.bin"
    if missing_required:
        log.write_text("Compilation NOT run: missing required CIL inputs\n" +
                       "\n".join(x["role"] + ": " + x["path"] for x in missing_required) + "\n")
        exit_code = None
        status = "MISSING_REQUIRED_CIL_INPUTS"
    else:
        args = [str(secilc), "-m", "-M", "true", "-G", "-N"]
        if policy_version is not None:
            if not 15 <= policy_version <= 40:
                raise ValueError("SELinux binary policy version outside expected bounds")
            args += ["-c", str(policy_version)]
        args += ["-o", str(output), "-f", "/dev/null"]
        args += [x["host"] for x in selected]
        p = subprocess.run(args, capture_output=True, text=True, check=False)
        exit_code = p.returncode
        log.write_text(
            "Host-side SELinux split-policy compilation only (not runtime boot)\n" +
            "Policy version: " + (str(policy_version) if policy_version is not None
                                  else "host secilc default; NOT exact init parity") + "\n" +
            "Exit code: " + str(exit_code) + "\n\n" +
            p.stdout + "\n" + p.stderr)
        status = ("HOST_CIL_COMPILES_RUNTIME_UNVERIFIED" if exit_code == 0
                  and output.is_file() and output.stat().st_size > 0
                  else "HOST_CIL_COMPILATION_FAILED")
    report = {
        "status": status,
        "vendor_mapping_version": vendor_vers,
        "genfs_labels_version": genfs_version,
        "policy_version_override": policy_version,
        "exact_android_init_policy_version_verified": False,
        "compilation_exit_code": exit_code,
        "required_missing": missing_required,
        "optional_missing": missing_optional,
        "cil_inputs": selected,
        "log": str(log),
        "binary_output": str(output) if output.is_file() else None,
        "images_modified": False,
        "precompiled_vendor_hashes_modified": False,
        "boot_verified": False,
        "enforcing_selinux_verified": False,
        "apex_vintf_verified": False,
        "warning": "Host secilc compilation is a static compatibility probe. "
                   "A passing result cannot confirm kernel acceptance, device runtime "
                   "services, APEX policy, VINTF or actual enforcing boot.",
    }
    (reportdir / "selinux-compile-report.json").write_text(
        json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": status, "vendor_mapping_version": vendor_vers,
                      "required_missing": missing_required,
                      "policy_version_override": policy_version,
                      "compilation_exit_code": exit_code,
                      "log": str(log),
                      "report": str(reportdir / "selinux-compile-report.json"),
                      "warning": report["warning"]}, indent=2))
    return status


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--aosp", type=Path, required=True)
    p.add_argument("--report-dir", type=Path, required=True)
    p.add_argument("--policy-version", type=int,
                   help="Optional exact init SEPOLICY_VERSION; omit to use host default")
    args = p.parse_args()
    status = compile_policy(args.output, args.report_dir, args.aosp,
                            args.policy_version)
    return 0 if status == "HOST_CIL_COMPILES_RUNTIME_UNVERIFIED" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError) as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(2)
