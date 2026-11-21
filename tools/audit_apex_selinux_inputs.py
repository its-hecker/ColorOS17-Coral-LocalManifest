#!/usr/bin/env python3
"""Inspect ColorOS/Pixel APEX and SELinux boot inputs without altering images.

This script does NOT activate APEX containers, execute checkvintf with APEX
fragments, compile SELinux policy or declare the images bootable.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from rootless_ext4 import Ext4

APEX_PATHS = {
    "coloros": ("/system/apex", "/product/apex", "/system_ext/apex"),
    "pixel_vendor": ("/apex", "/odm/apex"),
}
POLICY_PATHS = {
    "coloros": (
        "/system/etc/selinux/plat_sepolicy.cil",
        "/system/etc/selinux/mapping",
        "/system/etc/selinux/plat_sepolicy_and_mapping.sha256",
        "/system_ext/etc/selinux/system_ext_sepolicy.cil",
        "/system_ext/etc/selinux/system_ext_sepolicy_and_mapping.sha256",
        "/product/etc/selinux/product_sepolicy.cil",
        "/product/etc/selinux/product_sepolicy_and_mapping.sha256",
    ),
    "pixel_vendor": (
        "/etc/selinux/precompiled_sepolicy",
        "/etc/selinux/vendor_sepolicy.cil",
        "/etc/selinux/plat_pub_versioned.cil",
        "/etc/selinux/odm_sepolicy.cil",
        "/etc/selinux/precompiled_sepolicy.plat_sepolicy_and_mapping.sha256",
        "/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256",
        "/etc/selinux/precompiled_sepolicy.product_sepolicy_and_mapping.sha256",
    ),
}
HASH_PAIRS = (
    ("/system/etc/selinux/plat_sepolicy_and_mapping.sha256",
     "/etc/selinux/precompiled_sepolicy.plat_sepolicy_and_mapping.sha256"),
    ("/system_ext/etc/selinux/system_ext_sepolicy_and_mapping.sha256",
     "/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256"),
    ("/product/etc/selinux/product_sepolicy_and_mapping.sha256",
     "/etc/selinux/precompiled_sepolicy.product_sepolicy_and_mapping.sha256"),
)


def small_file(fs, path):
    if not fs.exists(path):
        return None
    info = fs.info(path)
    if info["type"] != "regular" or not 0 < info["size"] <= 2048:
        raise ValueError("Unexpected policy hash file type/size: " + path)
    with tempfile.TemporaryDirectory(prefix="coloros17-policy-hash-") as folder:
        target = Path(folder) / "hash"
        fs.export_file(path, target)
        text = target.read_text().strip()
    if not text or len(text) > 1024:
        raise ValueError("Empty or excessive policy hash text: " + path)
    return text


def apex_inventory(fs, dirs):
    output = []
    for root in dirs:
        if not fs.exists(root):
            output.append({"path": root, "exists": False, "apex_files": [],
                           "other_entries": []})
            continue
        if fs.info(root)["type"] != "directory":
            raise ValueError("APEX path is not a directory: " + root)
        entries = fs.children(root)
        containers = [name for name in entries
                      if name.endswith((".apex", ".capex"))]
        output.append({
            "path": root, "exists": True,
            "apex_files": sorted(containers),
            "other_entries": sorted(set(entries) - set(containers)),
        })
    return output


def collect(outdir):
    outdir = outdir.resolve()
    files = {
        "coloros": outdir / "system.img",
        "pixel_vendor": outdir / "vendor-raw.img",
    }
    for role, file in files.items():
        if not file.is_file() or file.stat().st_size == 0:
            raise ValueError("Missing image: " + str(file))
    images = {role: Ext4(file) for role, file in files.items()}
    report = {
        "status": "APEX_AND_SELINUX_INPUT_AUDIT_ONLY",
        "boot_verified": False,
        "full_vintf_verified": False,
        "selinux_policy_compilation_verified": False,
        "images": {role: str(file) for role, file in files.items()},
        "apex": {role: apex_inventory(images[role], APEX_PATHS[role])
                 for role in files},
        "selinux_files": {
            role: {path: images[role].exists(path)
                   for path in POLICY_PATHS[role]}
            for role in files},
        "precompiled_policy_hashes": [],
        "caveats": [
            "This is an inventory only: no APEX packages were activated",
            "The VINTF base check did not evaluate APEX VINTF fragments",
            "SELinux CIL modules were not linked or compiled with secilc",
            "Matching precompiled hashes do not prove SELinux runtime correctness",
        ],
    }
    for source, vendor in HASH_PAIRS:
        a, b = small_file(images["coloros"], source), small_file(images["pixel_vendor"], vendor)
        status = ("MISSING_HASH_INPUT" if a is None or b is None
                  else "MATCH" if a == b else "MISMATCH")
        report["precompiled_policy_hashes"].append({
            "platform_file": source,
            "vendor_precompiled_file": vendor,
            "status": status,
        })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new engineering output directory containing signed system.img and raw vendor")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "status": result["status"],
        "apex_containers_by_partition": {
            role: {entry["path"]: len(entry["apex_files"])
                   for entry in entries}
            for role, entries in result["apex"].items()},
        "policy_hash_results": [
            item["status"] for item in result["precompiled_policy_hashes"]],
        "report": str(args.report),
        "warning": "Static inputs only; APEX activation, VINTF and SELinux runtime are unverified",
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print("ERROR:", error, file=sys.stderr)
        raise SystemExit(2)
