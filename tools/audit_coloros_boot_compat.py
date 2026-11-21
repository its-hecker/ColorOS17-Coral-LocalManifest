#!/usr/bin/env python3
"""Read-only ColorOS 17 coral VINTF/SELinux input inventory.

Reads the *assembled* ColorOS system.img and Pixel vendor-raw.img with debugfs.
This is NOT a checkvintf compatibility verdict. It never modifies the images,
the Android source tree, or physical block devices.
"""
import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from rootless_ext4 import Ext4

MAX_XML = 16 * 1024 * 1024
TREES = {
    "coloros_system": ["/system/etc/vintf", "/product/etc/vintf",
                       "/system_ext/etc/vintf", "/odm/etc/vintf"],
    "pixel_vendor": ["/etc/vintf"],
}
SELINUX_INPUTS = {
    "coloros_system": [
        "/system/etc/selinux/plat_sepolicy.cil",
        "/system/etc/selinux/plat_file_contexts",
        "/system/etc/selinux/plat_property_contexts",
        "/product/etc/selinux/product_sepolicy.cil",
        "/system_ext/etc/selinux/system_ext_sepolicy.cil",
    ],
    "pixel_vendor": [
        "/etc/selinux/vendor_sepolicy.cil",
        "/etc/selinux/plat_pub_versioned.cil",
        "/etc/selinux/vendor_file_contexts",
        "/etc/selinux/vendor_property_contexts",
        "/etc/selinux/precompiled_sepolicy",
    ],
}


def xml_inventory(blob):
    """Parse enough of VINTF XML to inventory entries, not to assert compatibility."""
    root = ET.fromstring(blob)
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in ("manifest", "compatibility-matrix"):
        raise ValueError("Unexpected root XML tag: " + kind)
    hals = []
    for hal in root.findall(".//hal"):
        name = hal.findtext("name")
        if name:
            hals.append(name)
    return {"xml_kind": kind, "type": root.get("type"),
            "hal_count": len(hals), "hal_names": sorted(set(hals))}


def walk_vintf(fs, root, destination, missing, problems):
    if not fs.exists(root):
        missing.append(root)
        return []
    found = []

    def visit(path):
        node = fs.info(path)
        if node["type"] == "directory":
            for name in fs.children(path):
                visit(path.rstrip("/") + "/" + name)
        elif node["type"] == "regular" and path.endswith(".xml"):
            if node["size"] > MAX_XML:
                problems.append({"path": path, "error": "XML exceeds 16 MiB limit"})
                return
            local = destination / path.lstrip("/")
            local.parent.mkdir(parents=True, exist_ok=True)
            fs.export_file(path, local)
            content = local.read_bytes()
            try:
                details = xml_inventory(content)
            except (ET.ParseError, ValueError) as exc:
                problems.append({"path": path, "error": str(exc)})
                return
            found.append({"path": path, "size": len(content),
                          "sha256": hashlib.sha256(content).hexdigest(), **details})
        elif node["type"] == "symlink":
            problems.append({"path": path, "error": "Symlink not followed"})

    visit(root)
    return found


def audit(out, reportdir):
    out = out.resolve()
    reportdir = reportdir.resolve()
    sources = {
        "coloros_system": out / "system.img",
        "pixel_vendor": out / "vendor-raw.img",
    }
    for role, path in sources.items():
        if not path.is_file() or not path.stat().st_size:
            raise ValueError("Missing assembled " + role + ": " + str(path))
    reportdir.mkdir(parents=True, exist_ok=True)
    result = {"status": "VINTF_SELINUX_STATIC_INVENTORY_ONLY",
              "boot_compatibility_verified": False,
              "compatibility_checks_performed": ["VINTF XML parsing",
                                                  "SELinux input presence"],
              "sources": {role: str(path) for role, path in sources.items()},
              "partitions": {},
              "warnings": []}
    for role, path in sources.items():
        fs = Ext4(path)
        absent, problems, records = [], [], []
        for root in TREES[role]:
            records += walk_vintf(
                fs, root, reportdir / "vintf" / role, absent, problems)
        selinux = {path: fs.exists(path) for path in SELINUX_INPUTS[role]}
        result["partitions"][role] = {
            "vintf_files": records,
            "missing_vintf_directories": absent,
            "xml_problems": problems,
            "selinux_input_presence": selinux,
        }
    system = result["partitions"]["coloros_system"]
    vendor = result["partitions"]["pixel_vendor"]
    if not any(x["xml_kind"] == "compatibility-matrix"
               for x in system["vintf_files"]):
        result["warnings"].append("No ColorOS framework compatibility matrix found")
    if not any(x["xml_kind"] == "manifest"
               for x in vendor["vintf_files"]):
        result["warnings"].append("No Pixel vendor VINTF manifest found")
    if any(x["xml_problems"] for x in (system, vendor)):
        result["warnings"].append("At least one malformed/unsupported VINTF XML entry")
    result["warnings"].append(
        "No checkvintf comparison, VNDK, linker or enforcing SELinux "
        "compatibility was established by this inventory")
    path = reportdir / "boot-compat-inventory.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"report": str(path),
                      "status": result["status"],
                      "vintf_xml_files": {
                          key: len(val["vintf_files"])
                          for key, val in result["partitions"].items()},
                      "warnings": result["warnings"]}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="existing ColorOS engineering image output directory")
    parser.add_argument("--report-dir", type=Path, required=True,
                        help="new directory for XML exports and read-only inventory")
    args = parser.parse_args()
    audit(args.output, args.report_dir)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
