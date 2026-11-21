#!/usr/bin/env python3
"""Generate an *uninstalled* Pixel-specific VINTF framework matrix candidate.

Reads the device-HAL incompatibility list produced by the repo's base VINTF
checker and confirms every missing HAL/version/instance against the extracted,
actual Pixel vendor VINTF manifest. Makes a small copy of the exported XML,
updates only compatibility_matrix.device.xml in that copy, runs checkvintf,
and writes an audit report. NEVER edits system.img, vendor.img, AVB, or a device.
APEX fragments, kernel, SELinux and runtime compatibility remain unverified.
"""
import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from check_coloros_vintf_base import make_command

MISSING_START = (
    "The following instances are in the device manifest "
    "but not specified in framework compatibility matrix:"
)
MISSING_END = "Suggested fix:"
HIDL = re.compile(r"^([A-Za-z_][\w.]*)@(\d+\.\d+)::([A-Za-z_]\w*)/([\w.-]+)$")
AIDL = re.compile(r"^([A-Za-z_][\w.]*)\.(I[A-Za-z_]\w*)/([\w.-]+)\s+\(@(\d+)\)$")
FQ_HIDL = re.compile(r"^@(\d+\.\d+)::([A-Za-z_]\w*)/([\w.-]+)$")
FQ_AIDL = re.compile(r"^([A-Za-z_]\w*)/([\w.-]+)$")


def parse_missing_log(data):
    if MISSING_START not in data or MISSING_END not in data:
        raise ValueError("No exact missing-device-HAL section in checkvintf log")
    section = data.split(MISSING_START, 1)[1].split(MISSING_END, 1)[0]
    missing = []
    for line in section.splitlines():
        line = line.strip()
        if not line:
            continue
        h = HIDL.fullmatch(line)
        a = AIDL.fullmatch(line)
        if h:
            package, version, interface, instance = h.groups()
            missing.append(("hidl", package, version, interface, instance))
        elif a:
            package, interface, instance, version = a.groups()
            missing.append(("aidl", package, version, interface, instance))
        else:
            raise ValueError("Unrecognized HAL instance in VINTF output: " + line)
    if not missing or len(missing) > 40 or len(missing) != len(set(missing)):
        raise ValueError("Missing HAL list empty, suspiciously large, or duplicated")
    return sorted(missing)


def read_vendor_hal_instances(vendor_root):
    """Collect actual vendor declarations, supporting fqname and interface forms."""
    xmlpaths = sorted((vendor_root / "etc/vintf").glob("*.xml"))
    xmlpaths += sorted((vendor_root / "etc/vintf/manifest").glob("*.xml"))
    result = set()
    for path in xmlpaths:
        root = ET.parse(path).getroot()
        if root.tag != "manifest" or root.get("type") != "device":
            continue
        for hal in root.findall("hal"):
            package = hal.findtext("name")
            fmt = hal.get("format", "hidl")
            if fmt not in ("hidl", "aidl") or not package:
                continue
            versions = [x.text for x in hal.findall("version") if x.text]
            for fq in hal.findall("fqname"):
                if not fq.text:
                    continue
                if fmt == "hidl":
                    m = FQ_HIDL.fullmatch(fq.text.strip())
                    if m:
                        version, interface, instance = m.groups()
                        result.add((fmt, package, version, interface, instance))
                elif fmt == "aidl":
                    m = FQ_AIDL.fullmatch(fq.text.strip())
                    if m:
                        interface, instance = m.groups()
                        for version in versions or ["1"]:
                            result.add((fmt, package, version, interface, instance))
            for iface in hal.findall("interface"):
                interface = iface.findtext("name")
                if not interface:
                    continue
                for instance_element in iface.findall("instance"):
                    if instance_element.text:
                        for version in versions or (["1"] if fmt == "aidl" else []):
                            result.add((fmt, package, version,
                                        interface, instance_element.text.strip()))
                for rx in iface.findall("regex-instance"):
                    # Do not convert broad manifest regexes into fabricated
                    # concrete matrix instances; manual review is required.
                    if rx.text:
                        pass
    return result


def ensure_matrix(vintf_copy, missing):
    """Merge into one known device-specific FCM path, preserving existing entries."""
    dest = (vintf_copy / "coloros_system/system/etc/vintf/"
            "compatibility_matrix.device.xml")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        matrix = ET.parse(dest).getroot()
        if matrix.tag != "compatibility-matrix" or matrix.get("type") != "framework":
            raise ValueError("Existing device FCM has unexpected XML type: " + str(dest))
        if matrix.get("level") is not None:
            raise ValueError("Device FCM unexpectedly declares platform level")
    else:
        matrix = ET.Element("compatibility-matrix", {
            "version": "1.0", "type": "framework",
        })
    # Refuse package-level collisions with existing metadata; these need a
    # real FCM merge, not a duplicate <hal> entry.
    existing_names = {x.findtext("name") for x in matrix.findall("hal")}
    new_packages = {x[1] for x in missing}
    collisions = new_packages & existing_names
    if collisions:
        raise ValueError("Existing device-specific HAL entries need review: " +
                         ", ".join(sorted(collisions)))
    by_package = {}
    for fmt, package, version, interface, instance in missing:
        by_package.setdefault((fmt, package, version), []).append(
            (interface, instance))
    for (fmt, package, version), interfaces in sorted(by_package.items()):
        element = ET.SubElement(matrix, "hal", {
            "format": fmt, "optional": "true",
        })
        ET.SubElement(element, "name").text = package
        ET.SubElement(element, "version").text = version
        for name, instance in sorted(interfaces):
            i = ET.SubElement(element, "interface")
            ET.SubElement(i, "name").text = name
            ET.SubElement(i, "instance").text = instance
    ET.indent(matrix, space="  ")
    ET.ElementTree(matrix).write(dest, encoding="unicode", xml_declaration=True)
    return dest


def generate(aosp, audit, checklog, candidate):
    if candidate.exists():
        raise ValueError("Candidate directory already exists; choose a fresh path: " +
                         str(candidate))
    inv = json.loads((audit / "boot-compat-inventory.json").read_text())
    if inv.get("status") != "VINTF_SELINUX_STATIC_INVENTORY_ONLY":
        raise ValueError("VINTF inventory provenance missing")
    missing = parse_missing_log(checklog.read_text())
    actual = read_vendor_hal_instances(audit / "vintf/pixel_vendor")
    not_found = [x for x in missing if x not in actual]
    if not_found:
        raise ValueError("Missing versioned HALs not found in exported vendor manifest: " +
                         repr(not_found))
    copyroot = candidate / "vintf"
    shutil.copytree(audit / "vintf", copyroot)
    matrix = ensure_matrix(copyroot, missing)
    binpath = aosp / "out/host/linux-x86/bin/checkvintf"
    if not binpath.is_file():
        raise ValueError("Compiled checkvintf missing: " + str(binpath))
    command = make_command(binpath, copyroot)
    output = subprocess.run(command, capture_output=True, text=True, check=False)
    (candidate / "checkvintf-after.txt").write_text(output.stdout + output.stderr)
    text = (output.stdout + output.stderr).strip()
    if output.returncode == 0 and text.endswith("COMPATIBLE"):
        status = "CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED"
    elif text.endswith("INCOMPATIBLE"):
        status = "CANDIDATE_BASE_VINTF_STILL_INCOMPATIBLE"
    else:
        status = "CANDIDATE_CHECKER_INPUT_ERROR"
    report = {
        "status": status, "checker_exit_code": output.returncode,
        "hal_entries_added": len(missing),
        "matched_vendor_manifest_instances": [
            {"format": fmt, "package": pkg, "version": version,
             "interface": interface, "instance": instance}
            for fmt, pkg, version, interface, instance in missing
        ],
        "matrix_candidate": str(matrix),
        "installed_into_image": False, "avb_modified": False,
        "full_vintf_compatibility_verified": False, "boot_verified": False,
        "apex_fragments_checked": False,
        "warning": "This is an extracted-XML candidate only; no on-device "
                   "compatibility or runtime service behavior is established.",
    }
    (candidate / "candidate-report.json").write_text(
        json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aosp", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--log", type=Path, required=True,
                   help="previous incompatible checkvintf-base-coloros-coral.log")
    p.add_argument("--candidate", type=Path, required=True,
                   help="NEW output directory for extracted-XML candidate")
    x = p.parse_args()
    result = generate(x.aosp, x.audit, x.log, x.candidate)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == \
        "CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, ET.ParseError) as error:
        print("ERROR:", error, file=sys.stderr)
        sys.exit(2)
