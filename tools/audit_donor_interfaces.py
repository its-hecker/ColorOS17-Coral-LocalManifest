#!/usr/bin/env python3
"""Static ColorOS GSI ↔ coral interface audit, read-only ext4 metadata.

No image repack, binaries, platform signing, changes to system/vendor, or
bypass of biometric/security services. Reports *candidates*, not guaranteed
VINTF compatibility: deployed vendor VINTF fragments are not present here.
"""
import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_READ = 512 * 1024
PROPS = [
    "ro.build.version.sdk", "ro.build.version.release", "ro.build.version.codename",
    "ro.build.version.security_patch", "ro.treble.enabled", "ro.vndk.version",
    "ro.product.first_api_level", "ro.system.build.version.sdk",
]
VINTF_DIRS = (
    "/system/etc/vintf",
    "/system_ext/etc/vintf",
    "/product/etc/vintf",
)
LINKS = ("/system/product", "/system/system_ext", "/product", "/system_ext",
         "/init", "/adb_keys")
INIT_DIRS = ("/system/etc/init", "/system_ext/etc/init", "/product/etc/init")


def debugfs(image, command):
    r = subprocess.run(["debugfs", "-R", command, str(image)],
                       capture_output=True, timeout=45, check=False)
    stderr = r.stderr.decode("utf-8", errors="replace")
    if r.returncode or "File not found" in stderr or "not found by ext2_lookup" in stderr:
        return None
    if len(r.stdout) > MAX_READ:
        raise ValueError("debugfs read exceeded safe metadata limit: " + command)
    return r.stdout.decode("utf-8", errors="replace")


def read(image, path):
    return debugfs(image, "cat " + path)


def parse_props(text):
    records = {}
    if not text:
        return records
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, val = line.split("=", 1)
        records[key.strip()] = val.strip()
    return {name: records[name] for name in PROPS if name in records}


def parse_hals(xml):
    """Return HAL names grouped by format/version; exact FCM match is not inferred."""
    if not xml:
        return {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise ValueError("Malformed VINTF XML") from err
    output = {}
    for elem in root.findall("./hal"):
        name = (elem.findtext("name") or "").strip()
        if not name:
            continue
        info = {"format": elem.get("format", "hidl"),
                "optional": elem.get("optional", "false"),
                "versions": [v.text.strip() for v in elem.findall("version") if v.text],
                "interfaces": [i.findtext("name", default="").strip()
                               for i in elem.findall("interface")],
                "fqnames": [x.text.strip() for x in elem.findall("fqname") if x.text]}
        output.setdefault(name, []).append(info)
    return output


def directory_entry_names(image, directory):
    raw = debugfs(image, "ls -p " + directory)
    if raw is None:
        return None
    return sorted(set(re.findall(r"/\d+/\d+/\d+/\d+/([^/\n]+)/", raw)) - {".", ".."})


def matrix_paths_from_listings(listings):
    paths = []
    for directory, entries in listings.items():
        if entries is None:
            continue
        for entry in entries:
            if entry.startswith("compatibility_matrix") and entry.endswith(".xml"):
                paths.append(directory + "/" + entry)
    return sorted(set(paths))


def inspect_links(image):
    result = {}
    for path in LINKS:
        raw = debugfs(image, "stat " + path)
        if raw is None:
            result[path] = {"exists": False}
            continue
        typ = re.search(r"Type:\s*(\w+)", raw)
        link = re.search(r"(?:Fast link dest|Link target):\s*[\"']?([^\n\"']+)", raw)
        result[path] = {"exists": True,
                        "inode_type": typ.group(1) if typ else "unknown",
                        "link_target": link.group(1).strip() if link else None}
    return result


def required_names(hals):
    return {name for name, descriptors in hals.items()
            if any(str(hal["optional"]).lower() != "true" for hal in descriptors)}


def audit_target_level(manifest_xml, matrices):
    try:
        target = ET.fromstring(manifest_xml).get("target-level")
    except ET.ParseError as exc:
        raise ValueError("Malformed coral device VINTF manifest") from exc
    if not target or not target.isdigit() or int(target) > 100:
        raise ValueError("Missing or unexpected coral VINTF target-level")
    selected = f"/system/etc/vintf/compatibility_matrix.{target}.xml"
    levels = {name: {"total_hal_names": len(hals),
                     "potentially_required_hal_names": len(required_names(hals)),
                     "oplus_hal_names": sorted(n for n in hals
                                               if n.startswith("vendor.oplus."))}
              for name, hals in matrices.items()}
    return target, selected, levels


def analyze(image, device_manifest):
    with image.open("rb") as stream:
        stream.seek(1080)
        if stream.read(2) != b"\x53\xef":
            raise ValueError("Expected pinned raw ext4 donor")
    if not device_manifest.is_file():
        raise ValueError("Missing pinned coral device HAL manifest")
    device_xml = device_manifest.read_text()
    coral_hals = parse_hals(device_xml)
    listings = {path: directory_entry_names(image, path) for path in VINTF_DIRS}
    matrix_files = matrix_paths_from_listings(listings)
    matrix = {}
    matrix_presence = {}
    for path in matrix_files:
        content = read(image, path)
        matrix_presence[path] = content is not None
        if content is not None:
            matrix[path] = parse_hals(content)

    target_level, target_path, per_matrix = audit_target_level(device_xml, matrix)
    selected = matrix.get(target_path)
    target_required = required_names(selected) if selected else set()
    target_missing = sorted(target_required - set(coral_hals))

    # The donor's "device" matrix can contain optional OPPO features. Keep it
    # separate; never count the whole set as universal device requirements.
    donor_specific = matrix.get("/system/etc/vintf/compatibility_matrix.device.xml", {})
    donor_oplus = sorted(name for name in donor_specific
                         if name.startswith("vendor.oplus."))
    dirs = {name: directory_entry_names(image, name) for name in INIT_DIRS}
    oplus_init = sorted({entry for names in dirs.values() if names
                         for entry in names if "oplus" in entry.lower() or
                         "coloros" in entry.lower()})
    builds = {part: parse_props(read(image, part + "/build.prop"))
              for part in ("/system", "/system_ext", "/product", "/my_product")}
    link_info = inspect_links(image)
    return {
        "target": "coral",
        "status": ("STATIC_REVIEW_ONLY_NOT_BOOTABLE" if selected else
                   "BLOCKED_TARGET_LEVEL_MATRIX_MISSING"),
        "build_props": builds, "coral_target_fcm_level": target_level,
        "target_level_matrix": target_path,
        "vintf_directories": listings,
        "vintf_matrix_candidates": matrix_files,
        "vintf_matrix_present": matrix_presence,
        "per_matrix_summary": per_matrix,
        "target_level_potentially_required_names": sorted(target_required),
        "target_level_names_absent_from_base_coral_manifest": target_missing,
        "target_level_absent_name_count": len(target_missing),
        "donor_device_matrix_oplus_names": donor_oplus,
        "coral_base_manifest_hal_names": sorted(coral_hals),
        "warning_vintf": (
            "VINTF FCM levels 7/8 and dated matrices are ALTERNATIVES, not one "
            "merged list. Missing names are rough static triage, NOT proof of "
            "missing HALs; assembled vendor/odm fragments, versions, optional "
            "requirements, kernel compatibility and checkvintf decide viability."),
        "mount_links": link_info,
        "oplus_init_file_count": len(oplus_init),
        "oplus_init_sample": oplus_init[:40],
        "gating_questions": [
            "Can the FCM level 7 framework matrix be satisfied by full assembled Pixel vendor/odm fragments?",
            "Do embedded system_ext/product symlinks resolve during first-stage mount?",
            "Can ColorOS init and Pixel service property contexts coexist with enforcing SELinux?",
            "Does ColorOS userspace support Pixel Citadel/IR and CHRE/Oslo interfaces?",
            "Can all donor-supplied ADB authorization artifacts be excluded?"
        ],
        "adb_keys_link_present": link_info.get("/adb_keys", {}).get("exists", False),
        "adb_keys_target_present": (
            debugfs(image, "stat /product/etc/security/adb_keys") is not None),
        "security": "Never package pre-authorized donor ADB host keys.",
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--device-manifest", type=Path, required=True)
    p.add_argument("--output", type=Path,
                   default=ROOT / "work/donor-interfaces.json")
    args = p.parse_args()
    result = analyze(args.image.resolve(), args.device_manifest.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired) as err:
        print("ERROR:", err, file=sys.stderr)
        raise SystemExit(2)
