#!/usr/bin/env python3
"""Build an auditable ColorOS17 input staging directory (NOT a bootable ROM).

Requires a fully compiled Android 17 coral baseline. Refuses oversized images.
Never modifies actual ROM sources, AVB flags, device partitions, or userdata.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUT = WORK / "stage"
REQUIRED = ("vendor.img", "boot.img", "dtbo.img")
BLOCKERS = [
    "Full checkvintf against assembled Pixel vendor/odm is not verified",
    "Pixel product/system_ext APKs, permissions and frameworks are not merged into ColorOS",
    "No enforcing SELinux property-context or policy compatibility guarantee",
    "super.img and signed vbmeta_system are not reconstructed and validated",
    "No Pixel 4 XL on-device first boot and no biometric/Soli functionality test",
]


def run(*cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_info(path):
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("Missing or empty image: " + str(path))
    sys.path.insert(0, str(ROOT / "tools"))
    from partition_budget import image_bytes
    return {"path": str(path.resolve()), "file_bytes": path.stat().st_size,
            "expanded_bytes": image_bytes(path), "sha256": sha256(path)}


def stage(rom_root, output=OUT):
    rom_root, output = rom_root.resolve(), output.resolve()
    if not (rom_root / ".repo").is_dir() or not (rom_root / "build/envsetup.sh").is_file():
        raise ValueError("Expected a completed Android 17 ROM source tree")
    built = rom_root / "out/target/product/coral"
    images = {name: image_info(built / name) for name in REQUIRED}
    output.mkdir(parents=True, exist_ok=True)

    run(sys.executable, ROOT / "tools/bootstrap.py", "--audit")
    run(sys.executable, ROOT / "tools/donor.py", "--download", "--inspect")
    # Never overwrite an existing extracted image; our inspector prevents this.
    donor_image = WORK / "donor/system-for-inspection.img"
    if not donor_image.exists():
        run(sys.executable, ROOT / "tools/inspect_ext4_contents.py", "--keep-image")
    else:
        with donor_image.open("rb") as s:
            s.seek(1080)
            if s.read(2) != b"\x53\xef":
                raise ValueError("Staged donor system image is not ext4")

    board = WORK / "hardware/device/BoardConfig-common.mk"
    run(sys.executable, ROOT / "tools/firstboot_preflight.py")
    fs_candidate = WORK / "firstboot/fstab.hardware.coloros17.candidate"
    bc_candidate = output / "BoardConfig-common.coloros17.candidate.mk"
    run(sys.executable, WORK / "adapters/device/tools/patch_boardconfig.py",
        "--original", board, "--output", bc_candidate)

    budget_path = output / "partition-budget.json"
    run(sys.executable, ROOT / "tools/partition_budget.py",
        "--board-config", board, "--system-img", donor_image,
        "--vendor-img", built / "vendor.img",
        "--embed-product", "--embed-system-ext",
        "--output", budget_path)
    budget = json.loads(budget_path.read_text())
    if budget["status"] != "FITS_BYTES_ONLY":
        raise ValueError("Partition sizes do not fit")

    report = {
        "target": "coral",
        "status": "SOURCE_IMAGES_STAGED_NOT_A_ROM",
        "bootable": False,
        "flashable": False,
        "base_rom_root": str(rom_root),
        "images": {"donor-system.img": image_info(donor_image), **images},
        "candidate_fstab": str(fs_candidate),
        "candidate_boardconfig": str(bc_candidate),
        "partition_budget": budget,
        "blockers": BLOCKERS,
        "warning": "No OTA, vbmeta, super or verified ColorOS boot image is produced.",
    }
    path = output / "build-report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(path), "status": report["status"],
                      "remaining_bytes": budget["remaining_after_reservation_bytes"]},
                     indent=2))
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rom-root", type=Path, required=True)
    p.add_argument("--output", type=Path, default=OUT)
    a = p.parse_args()
    stage(a.rom_root, a.output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
