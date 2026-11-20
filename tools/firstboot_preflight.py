#!/usr/bin/env python3
"""Create a first-boot compatibility *candidate*, not a bootable ROM.

Uses the pinned Pixel hardware checkout and verified donor geometry to produce
a reviewable first-stage fstab and fail-closed partition budget report.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "sources.lock.json").read_text())


def validate_donor(donor):
    if donor.get("sha256") != (
        "2842e697e30a04513050eefbf295e1f7911733ef9d7e964a028ec91e75efef64"
    ):
        raise ValueError("Donor does not match inspected PLK110 archive")
    if donor["inspected"].get("system_img_filesystem") != "ext4":
        raise ValueError("First-boot candidate only supports verified ext4 GSI")
    if donor["inspected"].get("zip_members") != 1:
        raise ValueError("Expected one GSI system.img; more partitions require review")
    required = {"system", "product", "system_ext", "my_product", "my_stock"}
    got = set(donor.get("internal_layout", {}).get("fs_root_dirs", []))
    if not required.issubset(got):
        raise ValueError("GSI embedded partition layout is not verified")
    return donor["inspected"]["system_img_bytes"]


def sha256_text(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Generate ColorOS17 coral candidate")
    ap.add_argument("--workspace", type=Path, default=ROOT / "work")
    ap.add_argument("--output", type=Path, default=ROOT / "work/firstboot")
    args = ap.parse_args()
    workspace, out = args.workspace.resolve(), args.output.resolve()
    size = validate_donor(LOCK["donor"])
    tree = workspace / "hardware/device"
    script = workspace / "adapters/device/tools/patch_fstab.py"
    original = tree / "init/fstab.hardware"
    board = tree / "BoardConfig-common.mk"
    if not (script.is_file() and original.is_file() and board.is_file()):
        raise RuntimeError("Run pinned tools/bootstrap.py --audit first")
    out.mkdir(parents=True, exist_ok=True)
    fstab = out / "fstab.hardware.coloros17.candidate"
    if fstab.exists():
        fstab.unlink()
    run = subprocess.run(
        [sys.executable, str(script), "--original", str(original),
         "--embed-product", "--embed-system-ext", "--output", str(fstab)],
        capture_output=True, text=True, check=False
    )
    if run.returncode:
        raise RuntimeError("fstab generation failed: " + run.stderr[-1000:])
    # Verify the critical first-stage invariants on real source.
    result = fstab.read_text()
    baseline = original.read_text()
    required_lines = [line for line in baseline.splitlines()
                      if line.startswith("vendor ") or
                      ("/data " in line and "fileencryption=" in line)]
    if any(line not in result.splitlines() for line in required_lines):
        raise AssertionError("Vendor or encrypted userdata mount was changed")
    if not all(("# ColorOS17 embedded: " + line) in result
               for line in baseline.splitlines()
               if line.startswith(("product ", "system_ext "))):
        raise AssertionError("Embedded product/system_ext mount not correctly omitted")
    # BoardConfig capacity is source truth, not the size of super alone.
    sys.path.insert(0, str(ROOT / "tools"))
    from partition_budget import assess, group_size
    budget = assess(group_size(board), {
        "system": size, "vendor": None, "product": 0, "system_ext": 0
    })
    report = {
        "target": "coral",
        "donor_sha256": LOCK["donor"]["sha256"],
        "image_format": "raw ext4",
        "source_fstab_sha256": sha256_text(original),
        "candidate_fstab_sha256": sha256_text(fstab),
        "candidate": str(fstab),
        "mount_action": "Omit separate product/system_ext mounts to expose donor embedded dirs",
        "first_stage_vendor_and_encryption_preserved": True,
        "partition_budget": budget,
        "status": "CANDIDATE_ONLY_NOT_FLASHABLE",
        "blockers": [
            "Real assembled Pixel vendor partition size not measured",
            "AVB/vbmeta_system descriptors not adapted",
            "ColorOS init/SELinux and VINTF not yet evaluated against Pixel vendor image",
            "System GSI factory ADB key and root-link semantics require inspection",
            "No rebuilt or device-boot-tested image exists"
        ]
    }
    (out / "firstboot-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "fstab-diff.txt").write_text(run.stdout)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
