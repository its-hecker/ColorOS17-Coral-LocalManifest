#!/usr/bin/env python3
"""Assemble an UNTESTED Pixel 4 XL / ColorOS 17 first-boot engineering package.

Real image assembly (not a ROM release): uses the pinned donor, an isolated
Android 17 coral build, modified first-stage fstab, Pixel vendor and boot,
signed system hashtree, chained vbmeta_system, and sparse A/B super geometry.
NEVER flashes devices; never disables verity/AVB; never signs with unknown keys.
Requires admin loop-mount permissions for selective Pixel package transplantation.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
PARTITIONS = ("product", "system_ext")
# Selected Pixel services from the *compiled* working Android 17 baseline.
# No ColorOS stock packages or signed APKs may be overwritten.
PIXEL_COPY = {
    "product": (
        "app/PixelCameraServicesCoral",
        "app/GoogleCameraCoral",
        "app/FloralMotionSenseBridge",
        "etc/default-permissions/default-permissions-google-camera-coral.xml",
        "etc/sysconfig/google-camera-coral.xml",
    ),
    "system_ext": (
        "app/QtiTelephonyService",
        "priv-app/ims",
        "priv-app/grilservice",
        "priv-app/qcrilmsgtunnel",
        "framework/google-ril.jar",
        "framework/qcrilhook.jar",
        "priv-app/FloralMotionSenseSettings",
        "priv-app/FloralOsloFeedback",
        "etc/permissions/privapp-permissions-floral-motionsense.xml",
    ),
}
PIXEL_REQUIRED = {
    "GoogleCameraCoral",
    "FloralMotionSenseBridge",
    "FloralMotionSenseSettings",
    "FloralOsloFeedback",
    "ims",
}


def run(*args, allowed=(0,), capture=False):
    cmd = [str(x) for x in args]
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=capture, text=True, check=False)
    if r.returncode not in allowed:
        raise RuntimeError("Command failed (exit %d): %s\n%s" %
                           (r.returncode, " ".join(cmd),
                            (r.stderr or "")[-2000:]))
    return r.stdout if capture else ""


def executable(root, name):
    p = root / "out/host/linux-x86/bin" / name
    if p.is_file():
        return str(p)
    q = shutil.which(name)
    if q:
        return q
    raise ValueError("Missing host build tool: " + name)


def avb_args(aosp):
    binary = aosp / "out/host/linux-x86/bin/avbtool"
    if binary.is_file():
        return [str(binary)]
    source = aosp / "external/avb/avbtool.py"
    if source.is_file():
        return [sys.executable, str(source)]
    raise ValueError("avbtool missing after base build")


def avb_info(avb, image):
    return run(*avb, "info_image", "--image", image, capture=True)


def parse_avb_value(details, key):
    match = re.search(r"^\s*" + re.escape(key) + r":\s*(\d+)\s*$",
                      details, re.M)
    if not match:
        raise ValueError("Could not read " + key + " from built AVB metadata")
    return int(match.group(1))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_raw_ext4(path):
    with Path(path).open("rb") as f:
        f.seek(1080)
        if f.read(2) != b"\x53\xef":
            raise ValueError("Not a raw ext4 image: " + str(path))


def disk_image(src, dst, simg2img):
    with src.open("rb") as f:
        sparse = f.read(4) == b"\x3a\xff\x26\xed"
    if dst.exists():
        raise ValueError("Working image already exists: " + str(dst))
    if sparse:
        run(simg2img, src, dst)
    else:
        shutil.copyfile(src, dst)
    check_raw_ext4(dst)
    return dst


def sudo_prefix():
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo") is None:
        raise ValueError("Loop mounting image data requires root or passwordless sudo")
    run("sudo", "-n", "true")
    return ["sudo", "-n"]


@contextlib.contextmanager
def mounted(path, mountpoint, read_only, prefix):
    mountpoint.mkdir(parents=True, exist_ok=True)
    flags = "loop,ro" if read_only else "loop,rw"
    run(*prefix, "mount", "-t", "ext4", "-o", flags, path, mountpoint)
    try:
        yield mountpoint
    finally:
        run(*prefix, "umount", mountpoint)


def size_of(root):
    if root.is_file():
        return root.stat().st_size
    if root.is_dir():
        return sum(x.stat().st_size for x in root.rglob("*") if x.is_file())
    return 0


def transplant_pixel(base_images, system, outdir, simg2img, prefix, reserve_bytes):
    """Transplant only reviewed names; fail closed on any package-name collision.

    Copy from the built Pixel product/system_ext ext4 images so file labels
    are retained rather than guessed from a Git checkout.
    """
    staging_images = {}
    for name in PARTITIONS:
        img = base_images / (name + ".img")
        if not img.is_file():
            raise ValueError("Built Pixel %s.img missing" % name)
        staging_images[name] = disk_image(
            img, outdir / ("pixel-" + name + "-raw.img"), simg2img)

    mounts = {}
    with contextlib.ExitStack() as stack:
        for name in PARTITIONS:
            mounts[name] = stack.enter_context(
                mounted(staging_images[name], outdir / ("mnt-" + name),
                        True, prefix))
        required = []
        for partition, paths in PIXEL_COPY.items():
            for rel in paths:
                source = mounts[partition] / rel
                if source.exists():
                    required.append((partition, rel, source, size_of(source)))
        found = {source.name for _, _, source, _ in required}
        missing = sorted(PIXEL_REQUIRED - found)
        if missing:
            raise ValueError("Missing required compiled Pixel apps: " + ", ".join(missing))
        total = sum(x[3] for x in required)
        # Preserve 64 MiB filesystem slack after copying selected apps.
        # Do not grow unnecessarily; donor originally has ~163 MiB free.
        free = 39791 * 4096
        grow = max(0, total + 64*1024*1024 - free)
        grow = ((grow + 4095) // 4096) * 4096
        if grow > reserve_bytes:
            raise ValueError("Insufficient dynamic partition budget for Pixel services")
        if grow:
            run("truncate", "-s", "+" + str(grow), system)
            run("e2fsck", "-fy", system, allowed=(0, 1))
            run("resize2fs", system)
        added = []
        with mounted(system, outdir / "mnt-system", False, prefix) as target:
            for partition, rel, source, n in required:
                dest = target / partition / rel
                if dest.exists() or dest.is_symlink():
                    raise ValueError("Refusing to replace donor package: " + str(dest))
                run(*prefix, "mkdir", "-p", dest.parent)
                run(*prefix, "cp", "-a", source, dest)
                added.append({"destination": "/" + partition + "/" + rel,
                              "source_partition": partition, "bytes": n})
            run(*prefix, "sync")
    run("e2fsck", "-fn", system)
    return {"new_files": added, "grown_by_bytes": grow, "copied_bytes": total}


def reconcile_pixel_property_contexts(system, vendor_raw, outdir, prefix):
    """Apply only collision-safe property_contexts edits to a staging image."""
    import importlib.util
    script = ROOT / "tools/apply_property_contexts.py"
    spec = importlib.util.spec_from_file_location("propctx_apply", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with contextlib.ExitStack() as stack:
        donor = stack.enter_context(mounted(
            system, outdir / "mnt-prop-system", False, prefix))
        vendor = stack.enter_context(mounted(
            vendor_raw, outdir / "mnt-prop-vendor", True, prefix))
        result = module.apply(donor, vendor, outdir, prefix)
        run(*prefix, "sync")
    run("e2fsck", "-fn", system)
    return result



def rootless_transplant_pixel(base_images, system, outdir, simg2img, reserve_bytes):
    """Copy reviewed Pixel packages with debugfs, checking uid/gid/mode/xattrs."""
    from rootless_ext4 import Ext4, copy_node, file_bytes, check_image
    sources = {}
    for name in PARTITIONS:
        img = base_images / (name + ".img")
        if not img.is_file():
            raise ValueError("Missing compiled " + str(img))
        raw = disk_image(img, outdir / ("pixel-" + name + "-raw.img"), simg2img)
        sources[name] = Ext4(raw)
    selected = []
    for partition, paths in PIXEL_COPY.items():
        for rel in paths:
            source_path = "/" + rel
            if sources[partition].exists(source_path):
                selected.append((partition, rel, file_bytes(sources[partition],
                                                             source_path)))
    found = {Path(rel).name for _, rel, _ in selected}
    missing = sorted(PIXEL_REQUIRED - found)
    if missing:
        details = []
        for part, rels in PIXEL_COPY.items():
            items = []
            fs = sources[part]
            for folder in ("app", "priv-app"):
                if fs.exists("/" + folder):
                    items.extend(fs.children("/" + folder))
            details.append(part + " detected relevant folders: " +
                           ", ".join(sorted(x for x in items if
                                            any(y in x.lower() for y in
                                                ("camera", "motion", "oslo", "pixel")))))
        raise ValueError("Missing required compiled Pixel apps: " +
                         ", ".join(missing) + "\n" + "\n".join(details))
    total = sum(size for _, _, size in selected)
    free = 39791 * 4096
    grow = max(0, total + 64 * 1024 * 1024 - free)
    grow = ((grow + 4095) // 4096) * 4096
    if grow > reserve_bytes:
        raise ValueError("Insufficient partition budget for rootless transplants")
    if grow:
        run("truncate", "-s", "+" + str(grow), system)
        run("e2fsck", "-fy", system, allowed=(0, 1))
        run("resize2fs", system)
    donor = Ext4(system)
    added = []
    for partition, rel, size in selected:
        destination = "/" + partition + "/" + rel
        parent = str(Path(destination).parent)
        if not donor.exists(parent):
            raise ValueError("Donor parent folder not present: " + parent)
        copy_node(sources[partition], donor, "/" + rel, destination)
        added.append({"destination": destination, "source_partition": partition,
                      "bytes": size})
    check_image(system)
    return {"new_files": added, "grown_by_bytes": grow,
            "copied_bytes": total, "method": "debugfs-rootless-verified"}


def rootless_reconcile_pixel_property_contexts(system, vendor_raw, outdir):
    """Run the pinned collision resolver using rootlessly extracted files."""
    from rootless_ext4 import Ext4, replace_file, check_image
    donor, vendor = Ext4(system), Ext4(vendor_raw)
    required = ("system/etc/selinux/plat_property_contexts",
                "system_ext/etc/selinux/system_ext_property_contexts",
                "product/etc/selinux/product_property_contexts")
    vendor_paths = ("etc/selinux/vendor_property_contexts",
                    "odm/etc/selinux/odm_property_contexts")
    scanner = ROOT / "work/adapters/vendor/tools/resolve_property_contexts.py"
    if not scanner.is_file():
        raise ValueError("Pinned property-context scanner missing")
    resultdir = outdir / "propctx"
    resultdir.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=outdir) as tmp:
        donor_root = Path(tmp) / "donor"
        vendor_root = Path(tmp) / "vendor"
        present = 0
        for ext4, root, names in ((donor, donor_root, required),
                                  (vendor, vendor_root, vendor_paths)):
            for name in names:
                if ext4.exists("/" + name):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    ext4.export_file("/" + name, target)
                    if ext4 is vendor:
                        present += 1
                elif ext4 is donor:
                    raise ValueError("Missing donor property-context file: " + name)
        if not present:
            raise ValueError("Missing vendor property contexts")
        run(sys.executable, scanner, "--donor-root", donor_root,
            "--vendor-root", vendor_root, "--output", resultdir, "--strict")
        report = json.loads((resultdir / "report.json").read_text())
        if report.get("blocked"):
            raise ValueError("Unresolved property-context collisions")
        updated = []
        for row in report["unmodified"]:
            if row["status"] == "candidate generated":
                name = row["file"]
                newfile = resultdir / name
                if not newfile.is_file() or not newfile.stat().st_size:
                    raise ValueError("Empty generated property-context file")
                replace_file(donor, "/" + name, newfile)
                updated.append(name)
    check_image(system)
    return {"updated": updated, "blocked": [],
            "report": str(resultdir / "report.json"),
            "method": "debugfs-rootless-verified"}


def image_size_budget(aosp, sysimg, vendor):
    sys.path.insert(0, str(ROOT / "tools"))
    from partition_budget import assess, group_size, image_bytes
    board = WORK / "hardware/device/BoardConfig-common.mk"
    total = group_size(board)
    values = {"system": image_bytes(sysimg), "vendor": image_bytes(vendor),
              "product": 0, "system_ext": 0}
    result = assess(total, values)
    if result["status"] != "FITS_BYTES_ONLY":
        raise ValueError("Signed ColorOS system + Pixel vendor exceeds coral group")
    return result


def validate_root_vbmeta_chain(avb, root_info, key, out):
    """Check the root vbmeta trusts the key used for the system chain."""
    public = out / "vbmeta_system.avbpubkey"
    run(*avb, "extract_public_key", "--key", key, "--output", public)
    expected = hashlib.sha1(public.read_bytes()).hexdigest().lower()
    chunks = root_info.split("Chain Partition descriptor:")
    matching = [c for c in chunks[1:]
                if re.search(r"^\s*Partition Name:\s*vbmeta_system\s*$",
                             c, re.M)]
    if len(matching) != 1:
        raise ValueError("Root vbmeta lacks a unique vbmeta_system chain")
    chunk = matching[0].split("Chain Partition descriptor:", 1)[0]
    actual = re.search(r"^\s*Public key \(sha1\):\s*([0-9a-f]+)", chunk, re.M | re.I)
    if not actual or actual.group(1).lower() != expected:
        raise ValueError("Root vbmeta trusts a DIFFERENT vbmeta_system signing key")
    loc = re.search(r"^\s*Rollback Index Location:\s*(\d+)", chunk, re.M)
    if not loc or int(loc.group(1)) != 1:
        raise ValueError("Unexpected root chain rollback location")
    return expected


def sign_system(aosp, system, vbmeta, out):
    avb = avb_args(aosp)
    key = aosp / "external/avb/test/data/testkey_rsa2048.pem"
    if not key.is_file():
        raise ValueError("Pinned local Android signing key not found: " + str(key))
    original_root = aosp / "out/target/product/coral/vbmeta.img"
    root_info = avb_info(avb, original_root)
    if parse_avb_value(root_info, "Flags") != 0:
        raise ValueError("Refusing build with AVB verification disabled")
    root_chain_public_sha1 = validate_root_vbmeta_chain(
        avb, root_info, key, out)
    base_system_meta = aosp / "out/target/product/coral/vbmeta_system.img"
    base_info = avb_info(avb, base_system_meta)
    rollback = parse_avb_value(base_info, "Rollback Index")
    location = parse_avb_value(base_info, "Rollback Index Location")
    # AVB chained vbmeta headers use rollback index location 0. The slot 1
    # association lives in the *parent* vbmeta chain descriptor, validated
    # separately above. Requiring location 1 in both places is incorrect.
    if location != 0:
        raise ValueError(
            "Unexpected chained vbmeta_system header rollback location "
            + str(location) + " (expected 0; parent chain uses location 1)")

    # Ensure 128 MiB minimum free for the hashtree and AVB footer. No FEC
    # generated in this experimental port; cryptographic verification stays on.
    span = system.stat().st_size + 128*1024*1024
    partition_size = ((span + 4095) // 4096) * 4096
    run(*avb, "add_hashtree_footer",
        "--image", system,
        "--partition_name", "system",
        "--partition_size", str(partition_size),
        "--algorithm", "SHA256_RSA2048",
        "--key", key,
        "--do_not_generate_fec")
    run(*avb, "make_vbmeta_image", "--output", vbmeta,
        "--algorithm", "SHA256_RSA2048", "--key", key,
        "--rollback_index", str(rollback),
        "--rollback_index_location", str(location),
        "--include_descriptors_from_image", system)
    run(*avb, "verify_image", "--image", vbmeta, "--key", key)
    if "Hashtree descriptor" not in avb_info(avb, vbmeta):
        raise ValueError("ColorOS system hash-tree descriptor not found")
    return {"rollback_index": rollback, "rollback_location": location,
            "vbmeta_system": str(vbmeta),
            "verified_root_flags": parse_avb_value(root_info, "Flags"),
            "root_trusted_vbmeta_system_key_sha1": root_chain_public_sha1}


def load_base_misc(rom_root):
    import glob
    import zipfile as z
    folder = rom_root / "out/target/product/coral/obj/PACKAGING/target_files_intermediates"
    zips = [Path(f) for f in glob.glob(str(folder / "*target_files*.zip"))]
    if not zips:
        raise ValueError("No AOSP target-files archive after coral build")
    path = max(zips, key=lambda p: p.stat().st_mtime)
    with z.ZipFile(path) as archive:
        raw = archive.read("META/misc_info.txt").decode("utf-8")
    info = {}
    for line in raw.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info, path


def create_super(aosp, sysimg, vendor, out):
    info, source = load_base_misc(aosp)
    required = ("super_metadata_device", "super_block_devices",
                "super_partition_groups")
    if any(not info.get(k) for k in required):
        raise ValueError("Cannot determine actual coral super metadata from target-files")
    groups = info["super_partition_groups"].split()
    if len(groups) != 1:
        raise ValueError("Unexpected coral partition groups: " + str(groups))
    group = groups[0]
    info["dynamic_partition_list"] = "system vendor"
    info["super_" + group + "_partition_list"] = "system vendor"
    info["lpmake"] = executable(aosp, "lpmake")
    info["system_image"] = str(sysimg)
    info["vendor_image"] = str(vendor)
    for key in ("product_image", "system_ext_image", "odm_image",
                "system_other_image"):
        info.pop(key, None)
    if info.get("dynamic_partition_retrofit") == "true":
        raise ValueError("Retrofit super format requires separate mapping; refusing")
    definition = out.parent / "super-layout.input"
    definition.write_text("\n".join(k + "=" + str(v) for k, v in
                                    sorted(info.items())) + "\n")
    script = aosp / "build/make/tools/releasetools/build_super_image.py"
    if not script.is_file():
        raise ValueError("AOSP build_super_image.py missing")
    run(sys.executable, script, definition, out)
    if not out.is_file() or not out.stat().st_size:
        raise ValueError("No super.img generated")
    return {"input": str(source), "layout": str(definition),
            "super_image": str(out), "bytes": out.stat().st_size}


def package(out, images, manifest):
    name = out / "ColorOS17-coral-FIRSTBOOT-UNTESTED-images.zip"
    if name.exists():
        raise ValueError("Previous engineering package exists; choose a fresh output directory")
    with zipfile.ZipFile(name, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True) as z:
        for image in images:
            z.write(image, arcname=image.name)
        z.writestr("EXPERIMENTAL-NOTICE.txt",
                   "ColorOS17 Pixel 4 XL experimental first-boot images.\n"
                   "NOT BOOT-VERIFIED, NOT AN INSTALLER OR OTA.\n"
                   "Do not flash without confirmed AVB, VINTF, and rescue plan.\n")
        z.writestr("build-report.json", json.dumps(manifest, indent=2) + "\n")
    return str(name)



def preflight_rootless_settings(aosp, built):
    """Check essential compiled APK before making any multi-GB working copies.

    Source APK presence alone is not enough: also inspect system_ext.img itself
    so we can catch a stale image even if the staged directory contains the APK.
    """
    apk = built / "system_ext/priv-app/FloralMotionSenseSettings/FloralMotionSenseSettings.apk"
    if not apk.is_file() or not apk.stat().st_size:
        raise ValueError(
            "FloralMotionSenseSettings is missing from installed output: " +
            str(apk) + "\nBuild and install that module, then rebuild systemextimage "
            "before running ColorOS assembly.")
    image = built / "system_ext.img"
    if not image.is_file():
        raise ValueError("Compiled system_ext.img missing: " + str(image))
    with tempfile.TemporaryDirectory(prefix="coloros17-systemext-check-") as directory:
        raw = Path(directory) / "system_ext.raw.img"
        disk_image(image, raw, executable(aosp, "simg2img"))
        from rootless_ext4 import Ext4
        fs = Ext4(raw)
        candidate = "/priv-app/FloralMotionSenseSettings/FloralMotionSenseSettings.apk"
        if not fs.exists(candidate):
            raise ValueError(
                "Staged FloralMotionSenseSettings APK exists, but system_ext.img "
                "does not contain " + candidate +
                "\nRebuild systemextimage from the selected coral product.")
    return {"status": "MOTION_SETTINGS_IN_IMAGE", "apk": str(apk), "image": str(image)}



def avb_preflight(aosp):
    """Validate compiled root/chained AVB layout without staging large images."""
    avb = avb_args(aosp)
    key = aosp / "external/avb/test/data/testkey_rsa2048.pem"
    if not key.is_file():
        raise ValueError("Pinned Android signing key missing: " + str(key))
    built = aosp / "out/target/product/coral"
    root_info = avb_info(avb, built / "vbmeta.img")
    if parse_avb_value(root_info, "Flags") != 0:
        raise ValueError("Refusing root vbmeta with verification disabled")
    with tempfile.TemporaryDirectory(prefix="coloros17-avb-check-") as directory:
        key_hash = validate_root_vbmeta_chain(avb, root_info, key, Path(directory))
    base = avb_info(avb, built / "vbmeta_system.img")
    header_location = parse_avb_value(base, "Rollback Index Location")
    if header_location != 0:
        raise ValueError("Chained vbmeta_system must have header rollback location 0; "
                         "got " + str(header_location))
    return {"root_chain_location": 1, "chained_header_location": header_location,
            "base_rollback_index": parse_avb_value(base, "Rollback Index"),
            "root_trusted_vbmeta_system_key_sha1": key_hash,
            "verified_root_flags": 0}


def checked_resume_minimal_staging(out, donor):
    """Reuse an already-staged donor only if unmodified and unsigned.

    Stops if previous run had applied context patches, AVB signing, or image
    generation. In those cases choose a new output folder instead.
    """
    from rootless_ext4 import check_image
    if not out.is_dir():
        raise ValueError("Staged output directory not found: " + str(out))
    for path in ("vbmeta_system.img", "super.img",
                 "ColorOS17-coral-FIRSTBOOT-UNTESTED-images.zip",
                 "engineering-report.json"):
        if (out / path).exists():
            raise ValueError("Refusing to resume from a signed or finished directory: " +
                             str(out / path))
    system, vendor = out / "system.img", out / "vendor-raw.img"
    check_raw_ext4(system)
    check_raw_ext4(vendor)
    # Reusing a previously edited / signed system could append a second AVB
    # footer, so accept *only* an exact copy of the immutable donor.
    if system.stat().st_size != donor.stat().st_size or sha256(system) != sha256(donor):
        raise ValueError("Staged system differs from original donor; use a new output "
                         "directory instead of resuming")
    report = out / "propctx/report.json"
    if not report.is_file():
        raise ValueError("Missing previous property-context audit; use new output")
    previous = json.loads(report.read_text())
    if previous.get("blocked") or any(x.get("status") == "candidate generated"
                                     for x in previous.get("unmodified", [])):
        raise ValueError("Previous context edits or unresolved collisions detected; "
                         "use a fresh output directory")
    check_image(system)
    check_image(vendor)
    return system, vendor


def main():
    p = argparse.ArgumentParser(description="Generate signed but UNTESTED firstboot images")
    p.add_argument("--rom-root", type=Path, required=True)
    p.add_argument("--output", type=Path, default=WORK / "engineering")
    p.add_argument("--rootless", action="store_true",
                   help="use debugfs rather than privileged loop mounts")
    p.add_argument("--resume-staged", action="store_true",
                   help="reuse an unchanged minimal staging directory after AVB preflight failure")
    p.add_argument("--minimal-boot", action="store_true",
                   help="first-boot profile: omit optional Pixel app transplants, including "
                        "camera, IMS, Face ID and Motion Sense userland; retain hardware firmware")
    p.add_argument("--check-inputs-only", action="store_true",
                   help="verify rootless image inputs, without staging or copying ColorOS")
    args = p.parse_args()
    aosp, out = args.rom_root.resolve(), args.output.resolve()
    built = aosp / "out/target/product/coral"
    donor = WORK / "donor/system-for-inspection.img"
    if not donor.is_file():
        raise ValueError("Download and inspect the SHA-pinned donor first")
    check_raw_ext4(donor)
    if not (built / "vendor.img").is_file():
        raise ValueError("Build Pixel 4 XL vendor.img first")
    if args.check_inputs_only and not args.rootless:
        raise ValueError("--check-inputs-only requires --rootless")
    if args.minimal_boot and not args.rootless:
        raise ValueError("--minimal-boot requires --rootless")
    if args.resume_staged and not (args.rootless and args.minimal_boot):
        raise ValueError("--resume-staged requires --rootless --minimal-boot")
    if args.resume_staged and args.check_inputs_only:
        raise ValueError("--resume-staged cannot be combined with --check-inputs-only")
    if args.minimal_boot:
        print("AVB compiled baseline preflight:", json.dumps(avb_preflight(aosp), indent=2))
    if args.rootless and not args.minimal_boot:
        result = preflight_rootless_settings(aosp, built)
        print(json.dumps(result, indent=2))
    if args.check_inputs_only:
        if args.minimal_boot:
            print(json.dumps({"status": "MINIMAL_INPUTS_READY",
                              "optional_apk_checks": "SKIPPED_BY_DESIGN",
                              "donor": str(donor), "baseline": str(built)}, indent=2))
        return
    if args.resume_staged:
        system, raw_vendor = checked_resume_minimal_staging(out, donor)
        print("Reusing verified unsigned minimal staging:", out)
    else:
        if out.exists() and any(out.iterdir()):
            raise ValueError("Output directory already contains files: " + str(out))
        out.mkdir(parents=True, exist_ok=True)
        system = out / "system.img"
        shutil.copyfile(donor, system)
        raw_vendor = out / "vendor-raw.img"
        disk_image(built / "vendor.img", raw_vendor,
                   executable(aosp, "simg2img"))
    simg = executable(aosp, "simg2img")
    budget = image_size_budget(aosp, system, raw_vendor)
    reserve = budget["remaining_after_reservation_bytes"]
    if args.minimal_boot:
        # First-boot isolation: do not merge app packages built for HeckerOS into
        # a precompiled ColorOS system. Retain the Pixel kernel and vendor HALs.
        transplant = {"profile": "minimal-boot", "new_files": [],
                      "grown_by_bytes": 0, "copied_bytes": 0,
                      "optional_userland_components": "omitted"}
        propctx = rootless_reconcile_pixel_property_contexts(system, raw_vendor, out)
    elif args.rootless:
        transplant = rootless_transplant_pixel(built, system, out, simg, reserve)
        propctx = rootless_reconcile_pixel_property_contexts(system, raw_vendor, out)
    else:
        prefix = sudo_prefix()
        transplant = transplant_pixel(built, system, out, simg, prefix, reserve)
        propctx = reconcile_pixel_property_contexts(system, raw_vendor, out, prefix)
    vbmeta_sys = out / "vbmeta_system.img"
    avb = sign_system(aosp, system, vbmeta_sys, out)
    budget = image_size_budget(aosp, system, raw_vendor)
    sup = out / "super.img"
    sup_report = create_super(aosp, system, built / "vendor.img", sup)
    images = [sup, vbmeta_sys]
    for name in ("boot.img", "dtbo.img", "vbmeta.img"):
        src = built / name
        if not src.is_file():
            raise ValueError("Missing generated boot/AVB image: " + str(src))
        target = out / name
        shutil.copyfile(src, target)
        images.append(target)
    manifest = {"status": "ENGINEERING_IMAGES_BUILT_UNTESTED",
                "profile": "minimal-boot" if args.minimal_boot else "feature-staging",
                "optional_userland_merged": not args.minimal_boot,
                "baseline_vendor_kernel_retained": True,
                "target": "coral", "donor": "ColorOS17 PLK110",
                "kernel": "pinned floral Android17 base",
                "pixel_transplant": transplant, "property_contexts": propctx, "avb": avb,
                "partition_budget": budget, "super": sup_report,
                "boot_verified": False, "runtime_hal_verified": False,
                "faceid_and_soli_verified": False, "OTA_installable": False,
                "images": {i.name: {"size": i.stat().st_size,
                                     "sha256": sha256(i)} for i in images}}
    (out / "engineering-report.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = package(out, images, manifest)
    print(json.dumps({"archive": archive,
                      "status": manifest["status"],
                      "warning": "This is NOT a boot-proven or recovery-flashable ROM."},
                     indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("ERROR:", error, file=sys.stderr)
        raise SystemExit(2)
