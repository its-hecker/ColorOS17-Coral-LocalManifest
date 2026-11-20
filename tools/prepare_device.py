#!/usr/bin/env python3
"""Apply a narrow first-stage mount change ONLY inside an isolated AOSP checkout.

The original coral fstab is backed up byte-for-byte. This never edits the
GitHub hardware source and never modifies an existing HeckerOS build directory.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = "# ColorOS17 embedded: "


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(aosp, reportdir):
    aosp = aosp.resolve()
    source = aosp / "device/google/coral/init/fstab.hardware"
    script = ROOT / "work/adapters/device/tools/patch_fstab.py"
    if not source.is_file() or not script.is_file():
        raise ValueError("Pinned coral device tree / adapter missing: run bootstrap first")
    reportdir.mkdir(parents=True, exist_ok=True)
    original = reportdir / "fstab.hardware.original"
    proposed = reportdir / "fstab.hardware.coloros17.candidate"
    content = source.read_bytes()
    if MARK.encode() in content:
        if not original.exists() or not proposed.exists():
            raise ValueError("Modified fstab has no matching backup: refusing")
        if digest(content) != digest(proposed.read_bytes()):
            raise ValueError("Source fstab differs from generated candidate")
        return {"original_sha256": digest(original.read_bytes()),
                "patched_sha256": digest(content), "already_applied": True}

    if original.exists() and digest(original.read_bytes()) != digest(content):
        raise ValueError("Source fstab no longer matches initial backup; refusing overwrite")
    if not original.exists():
        original.write_bytes(content)
    cmd = [sys.executable, str(script), "--original", str(original),
           "--embed-product", "--embed-system-ext", "--output", str(proposed)]
    subprocess.run(cmd, check=True)
    changed = proposed.read_bytes()
    if changed == content or MARK.encode() not in changed:
        raise ValueError("No verified embedded-partition change was produced")
    source.write_bytes(changed)
    return {"original_sha256": digest(content), "patched_sha256": digest(changed),
            "already_applied": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rom-root", type=Path, required=True)
    p.add_argument("--reportdir", type=Path, default=ROOT / "work/prebuild")
    args = p.parse_args()
    report = prepare(args.rom_root, args.reportdir.resolve())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print("ERROR:", e, file=sys.stderr)
        raise SystemExit(2)
