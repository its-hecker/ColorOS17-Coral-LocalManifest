#!/usr/bin/env python3
"""Assemble a SECOND ColorOS 17 coral engineering image with reviewed VINTF FCM.

Starts from the untouched donor ext4 image, never from the existing signed
system.img. Adds a narrowly reviewed device-specific framework compatibility
matrix with debugfs (preserving the adjacent matrix's SELinux xattr), repeats
the property-context audit and AVB signing, then rebuilds super and the
engineering ZIP. Requires APEX-independent base VINTF candidate compatibility.
No device flashing, no AVB disable, no source-tree changes.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from build_firstboot_images import (
    WORK, avb_preflight, check_raw_ext4, create_super, disk_image,
    executable, image_size_budget, package, rootless_reconcile_pixel_property_contexts,
    run, sha256, sign_system,
)
from check_coloros_vintf_base import make_command
from prepare_coloros_device_fcm import read_vendor_hal_instances
from rootless_ext4 import Ext4, check_image

DESTINATION = "/system/etc/vintf/compatibility_matrix.device.xml"
REFERENCE = "/system/etc/vintf/compatibility_matrix.7.xml"


def candidate_entries(matrix):
    """Ensure the candidate contains only optional, exact HAL declarations."""
    xml = ET.parse(matrix).getroot()
    if (xml.tag != "compatibility-matrix" or
            xml.get("type") != "framework" or xml.get("level") is not None):
        raise ValueError("VINTF candidate is not a device-specific framework matrix")
    actual = set()
    for hal in xml.findall("hal"):
        if hal.get("optional") != "true" or hal.get("format") not in ("aidl", "hidl"):
            raise ValueError("Unexpected mandatory or unknown HAL in matrix")
        name = hal.findtext("name")
        version = hal.findtext("version")
        if not name or not version:
            raise ValueError("Candidate HAL missing name/version")
        interfaces = hal.findall("interface")
        if not interfaces:
            raise ValueError("Candidate HAL missing interface instance")
        for interface in interfaces:
            iface = interface.findtext("name")
            instances = [x.text for x in interface.findall("instance")]
            if not iface or not instances or any(not x for x in instances):
                raise ValueError("Incomplete VINTF interface declarations")
            for instance in instances:
                entry = (hal.get("format"), name, version, iface, instance)
                if entry in actual:
                    raise ValueError("Duplicate VINTF declaration " + repr(entry))
                actual.add(entry)
    return actual


def verify_candidate(candidate, aosp):
    reportpath = candidate / "candidate-report.json"
    matrix = candidate / "vintf/coloros_system/system/etc/vintf/compatibility_matrix.device.xml"
    if not reportpath.is_file() or not matrix.is_file():
        raise ValueError("Missing reviewed candidate report or matrix")
    report = json.loads(reportpath.read_text())
    if (report.get("status") != "CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED" or
            report.get("checker_exit_code") != 0 or
            report.get("installed_into_image") is not False):
        raise ValueError("VINTF candidate did not pass its isolated host checker")
    expected = {
        (item["format"], item["package"], item["version"],
         item["interface"], item["instance"])
        for item in report.get("matched_vendor_manifest_instances", [])
    }
    entries = candidate_entries(matrix)
    if not expected or len(expected) != report.get("hal_entries_added"):
        raise ValueError("Candidate report lists inconsistent HAL instances")
    if entries != expected:
        raise ValueError("Candidate XML does not match the reviewed HAL list")
    vendor_root = candidate / "vintf/pixel_vendor"
    if not entries.issubset(read_vendor_hal_instances(vendor_root)):
        raise ValueError("Candidate HALs do not match exported Pixel vendor VINTF")
    checker = aosp / "out/host/linux-x86/bin/checkvintf"
    if not checker.is_file():
        raise ValueError("Missing host checkvintf binary")
    check = subprocess.run(make_command(checker, candidate / "vintf"),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, check=False)
    (candidate / "vintf-verify-for-image.txt").write_text(check.stdout)
    if check.returncode or not check.stdout.strip().endswith("COMPATIBLE"):
        raise ValueError("Latest partial base VINTF check no longer COMPATIBLE; "
                         "see vintf-verify-for-image.txt")
    return matrix, report, entries


def validate_baseline(baseline, aosp, candidate):
    """Ensure this rebuild uses the same Pixel hardware images as first package."""
    report = json.loads((baseline / "engineering-report.json").read_text())
    if (report.get("status") != "ENGINEERING_IMAGES_BUILT_UNTESTED" or
            report.get("profile") != "minimal-boot"):
        raise ValueError("Expected a completed minimal baseline report")
    built = aosp / "out/target/product/coral"
    for name in ("boot.img", "dtbo.img", "vbmeta.img"):
        expect = report.get("images", {}).get(name, {}).get("sha256")
        if not expect or sha256(built / name) != expect:
            raise ValueError("Pixel " + name + " changed since minimal baseline")
    # Extracted VINTF candidate must match *the same vendor image* used for
    # the successful baseline audit, not a similarly named ROM vendor checkout.
    export = candidate / "vintf/pixel_vendor/etc/vintf/manifest.xml"
    if not export.is_file():
        raise ValueError("Missing candidate's Pixel vendor manifest export")
    with tempfile.TemporaryDirectory(prefix="coloros17-vendor-check-") as tmp:
        path = Path(tmp) / "manifest.xml"
        fs = Ext4(baseline / "vendor-raw.img")
        fs.export_file("/etc/vintf/manifest.xml", path)
        if sha256(path) != sha256(export):
            raise ValueError("Candidate vendor VINTF differs from baseline image")
    return built


def install_matrix(system, matrix):
    """Install XML only when target absent, using peer XML inode metadata."""
    fs = Ext4(system)
    if fs.exists(DESTINATION):
        raise ValueError("Refusing to overwrite donor VINTF matrix " + DESTINATION)
    meta = fs.info(REFERENCE)
    if meta["type"] != "regular" or meta["links"] != 1:
        raise ValueError("Donor reference VINTF matrix is not a regular file")
    xattrs = {name: fs.xattr(REFERENCE, name) for name in fs.attrs(REFERENCE)}
    if "security.selinux" not in xattrs:
        raise ValueError("No SELinux label on donor framework VINTF reference")
    fs.create(DESTINATION, "regular", matrix)
    fs.restore(DESTINATION, meta, xattrs)
    with tempfile.TemporaryDirectory(prefix="coloros17-fcm-readback-") as tmp:
        copy = Path(tmp) / "readback.xml"
        fs.export_file(DESTINATION, copy)
        if sha256(copy) != sha256(matrix):
            raise ValueError("Written VINTF matrix differs from candidate")
    check_image(system)
    return {"path": DESTINATION, "sha256": sha256(matrix),
            "peer_label_path": REFERENCE,
            "selinux_xattr_preserved": True, "device_hal_matrix_entries": True}


def run_build(aosp, candidate, baseline, out):
    if out.exists():
        raise ValueError("Output already exists; choose a new path: " + str(out))
    matrix, candidate_report, entries = verify_candidate(candidate, aosp)
    built = validate_baseline(baseline, aosp, candidate)
    donor = WORK / "donor/system-for-inspection.img"
    check_raw_ext4(donor)
    avb_preflight(aosp)
    # Verify complete authoritative super geometry before copying >6 GiB.
    from build_firstboot_images import load_base_misc
    load_base_misc(aosp)
    out.mkdir(parents=True)
    system = out / "system.img"
    shutil.copyfile(donor, system)
    raw_vendor = out / "vendor-raw.img"
    disk_image(built / "vendor.img", raw_vendor, executable(aosp, "simg2img"))
    if sha256(raw_vendor) != sha256(baseline / "vendor-raw.img"):
        raise ValueError("Compiled vendor image no longer matches baseline")
    matrix_info = install_matrix(system, matrix)
    propctx = rootless_reconcile_pixel_property_contexts(system, raw_vendor, out)
    changes = [item for item in propctx.get("unmodified", [])
               if item.get("status") not in ("no changes", "no change", "unchanged")]
    if changes:
        raise ValueError("Unexpected additional property-context edits: " + repr(changes))
    vbmeta_system = out / "vbmeta_system.img"
    avb = sign_system(aosp, system, vbmeta_system, out)
    budget = image_size_budget(aosp, system, raw_vendor)
    super_image = out / "super.img"
    super_info = create_super(aosp, system, built / "vendor.img", super_image)
    images = [super_image, vbmeta_system]
    for name in ("boot.img", "dtbo.img", "vbmeta.img"):
        target = out / name
        shutil.copyfile(built / name, target)
        images.append(target)
    report = {
        "status": "ENGINEERING_IMAGES_BUILT_UNTESTED",
        "profile": "minimal-boot-pixel-vintf-candidate",
        "target": "coral",
        "donor": "ColorOS17 PLK110",
        "source_baseline": str(baseline),
        "vintf_candidate": {"status": candidate_report["status"],
                            "entries": len(entries), "matrix": matrix_info,
                            "apex_verified": False,
                            "runtime_verified": False},
        "property_contexts": propctx, "avb": avb,
        "partition_budget": budget, "super": super_info,
        "boot_verified": False, "runtime_hal_verified": False,
        "enforcing_selinux_verified": False,
        "ota_installable": False,
        "images": {item.name: {"size": item.stat().st_size,
                               "sha256": sha256(item)} for item in images},
    }
    (out / "engineering-report.json").write_text(json.dumps(report, indent=2) + "\n")
    archive = package(out, images, report)
    print(json.dumps({"status": report["status"],
                      "archive": archive,
                      "vintf_candidate_entries_installed": len(entries),
                      "warning": "APEX, SELinux, runtime and first boot NOT VERIFIED; "
                                 "engineering ZIP is not an installer"}, indent=2))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rom-root", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    run_build(args.rom_root.resolve(), args.candidate.resolve(),
              args.baseline.resolve(), args.output.resolve())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, ET.ParseError,
            subprocess.CalledProcessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
