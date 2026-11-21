#!/usr/bin/env python3
"""Run a *partial*, host-side VINTF comparison on exported ColorOS/Pixel XML.

The existing boot-compat inventory exports VINTF XML but does NOT extract
APEX containers or activate APEX VINTF fragments. AOSP checkvintf requires an
/apex directory mapping even when APEX info has not been exported. Map it to
an empty, explicitly marked directory, and never interpret COMPATIBLE as a
complete compatibility verdict. No partition/image modifications are made.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def make_command(bin_path, root):
    mapping = {
        "/system": root / "coloros_system/system",
        "/system_ext": root / "coloros_system/system_ext",
        "/product": root / "coloros_system/product",
        "/odm": root / "coloros_system/odm",
        "/vendor": root / "pixel_vendor",
        "/apex": root / "_unavailable_apex",
    }
    for where in mapping.values():
        where.mkdir(parents=True, exist_ok=True)
    args = [str(bin_path), "--check-compat"]
    for src, dst in mapping.items():
        args += ["--dirmap", src + ":" + str(dst)]
    args += [
        "--property", "ro.product.first_api_level=29",
        "--property", "ro.boot.product.hardware.sku=",
        "--property", "ro.boot.product.vendor.sku=",
    ]
    return args


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aosp", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True,
                   help="path to prior boot-compat-audit-* directory")
    p.add_argument("--log", type=Path, required=True)
    args = p.parse_args()
    binary = args.aosp / "out/host/linux-x86/bin/checkvintf"
    if not binary.is_file():
        raise ValueError("checkvintf executable missing: " + str(binary))
    inventory = args.audit / "boot-compat-inventory.json"
    if not inventory.is_file():
        raise ValueError("Missing image-derived inventory " + str(inventory))
    source = json.loads(inventory.read_text())
    parts = source.get("partitions", {})
    system = parts.get("coloros_system", {})
    vendor = parts.get("pixel_vendor", {})
    system_files = system.get("vintf_files", [])
    vendor_files = vendor.get("vintf_files", [])
    has_system_matrix = any(
        x.get("xml_kind") == "compatibility-matrix" for x in system_files)
    has_vendor_manifest = any(
        x.get("xml_kind") == "manifest" for x in vendor_files)
    if not (has_system_matrix and has_vendor_manifest):
        raise ValueError(
            "Incomplete VINTF inputs: ColorOS framework compatibility matrix=" +
            str(has_system_matrix) + ", Pixel device manifest=" +
            str(has_vendor_manifest) +
            ". Inspect boot-compat-inventory.json before rerunning.")
    root = args.audit / "vintf"
    cmd = make_command(binary, root)
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(
        "PARTIAL STATIC VINTF CHECK — APEX VINTF fragments omitted; "
        "kernel, runtime, and SELinux not checked.\n\n" + result.stdout)
    status = (
        "BASE_VINTF_COMPATIBLE_APEX_UNCHECKED"
        if result.returncode == 0 and result.stdout.strip().endswith("COMPATIBLE")
        else "BASE_VINTF_INCOMPATIBLE_APEX_UNCHECKED"
        if result.stdout.strip().endswith("INCOMPATIBLE")
        else "CHECKER_INPUT_OR_RUNTIME_ERROR"
    )
    report = {"status": status, "exit_code": result.returncode,
              "apex_fragments_checked": False,
              "complete_vintf_compatibility_verified": False,
              "boot_verified": False,
              "log": str(args.log),
              "warning": "An empty /apex mapping prevents path-resolution errors "
                         "but does not replace AOSP apexd_host activation of real "
                         "ColorOS/Pixel APEX files. Do not flash based on this check."}
    args.log.with_suffix(".json").write_text(
        json.dumps(report, indent=2) + "\n")
    print(result.stdout[-10000:])
    print(json.dumps(report, indent=2))
    if status == "CHECKER_INPUT_OR_RUNTIME_ERROR":
        return 2
    if status == "BASE_VINTF_INCOMPATIBLE_APEX_UNCHECKED":
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print("ERROR:", error, file=sys.stderr)
        sys.exit(2)
