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
MATRICES = (
    "/system/etc/vintf/compatibility_matrix.xml",
    "/system_ext/etc/vintf/compatibility_matrix.xml",
    "/product/etc/vintf/compatibility_matrix.xml",
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


def analyze(image, device_manifest):
    with image.open("rb") as stream:
        stream.seek(1080)
        if stream.read(2) != b"\x53\xef":
            raise ValueError("Expected pinned raw ext4 donor")
    if not device_manifest.is_file():
        raise ValueError("Missing pinned coral device HAL manifest")
    coral_hals = parse_hals(device_manifest.read_text())
    matrix = {}
    matrix_presence = {}
    for path in MATRICES:
        content = read(image, path)
        matrix_presence[path] = content is not None
        if content is not None:
            matrix[path] = parse_hals(content)
    donor_hals = {name: desc for section in matrix.values()
                  for name, desc in section.items()}
    required = {name for name, desc in donor_hals.items()
                if any(str(hal["optional"]).lower() != "true" for hal in desc)}
    # Static names only: vendor manifests and device fragments may add providers.
    not_in_base = sorted(required - set(coral_hals))
    dirs = {name: directory_entry_names(image, name) for name in INIT_DIRS}
    oplus_init = sorted({entry for names in dirs.values() if names
                         for entry in names if "oplus" in entry.lower() or
                         "coloros" in entry.lower()})
    builds = {part: parse_props(read(image, part + "/build.prop"))
              for part in ("/system", "/system_ext", "/product", "/my_product")}
    link_info = inspect_links(image)
    return {
        "target": "coral", "status": "STATIC_REVIEW_ONLY_NOT_BOOTABLE",
        "build_props": builds, "vintf_matrix_present": matrix_presence,
        "donor_required_hal_names": sorted(required),
        "coral_base_manifest_hal_names": sorted(coral_hals),
        "required_not_in_coral_base_manifest": not_in_base,
        "required_not_in_base_manifest_count": len(not_in_base),
        "warning_vintf": ("This is a name-only *triage* against one coral base manifest. "
                          "Actual generated vendor/odm manifest fragments and versions "
                          "must be checked with checkvintf before compatibility claims."),
        "mount_links": link_info,
        "oplus_init_file_count": len(oplus_init),
        "oplus_init_sample": oplus_init[:40],
        "gating_questions": [
            "Can the donor framework matrix be satisfied by the assembled Pixel vendor and odm manifests?",
            "Do embedded system_ext/product links mount at the donor's intended paths?",
            "Will ColorOS init and Pixel service property contexts co-exist under enforcing SELinux?",
            "Does ColorOS provide working userspace interfaces for Pixel Citadel/IR and CHRE/Oslo?",
            "Are there donor factory ADB authorization artifacts to exclude?"
        ],
        "adb_keys_present": link_info.get("/adb_keys", {}).get("exists", False),
        "security": ("Any donor adb_keys must be removed from the actual port. "
                     "Never authorize arbitrary hosts by default."),
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
