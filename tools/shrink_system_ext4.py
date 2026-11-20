#!/usr/bin/env python3
"""Create a *separate* compact raw ext4 donor image; never mutate the original.

Offline preparation helper, not a flasher or ROM builder. It does not change
Android properties, package signatures, SELinux labels or AVB descriptors.
No generated image is safe to flash without subsequent source/partition checks.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def cmd(*args):
    process = subprocess.run(list(map(str, args)), text=True, capture_output=True,
                             check=False)
    if process.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str, args)) +
                           "\n" + process.stdout[-500:] + "\n" + process.stderr[-500:])
    return process.stdout


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_raw_ext4(path):
    with path.open("rb") as stream:
        stream.seek(1080)
        return stream.read(2) == b"\x53\xef"


def prepare(src, out, limit=None):
    src, out = src.resolve(), out.resolve()
    if src == out or out.exists():
        raise ValueError("Output must be a different, nonexistent file")
    if not is_raw_ext4(src):
        raise ValueError("Input is not a verified raw ext4 filesystem")
    if not shutil.which("resize2fs") or not shutil.which("e2fsck"):
        raise RuntimeError("Missing e2fsprogs utilities")
    # e2fsck -n makes no changes; a source filesystem failure is a blocker.
    cmd("e2fsck", "-fn", src)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Preserve full ext4 metadata by copying the filesystem image itself.
        # No file-level extraction/repacking occurs here.
        with src.open("rb") as inp, out.open("xb") as dest:
            shutil.copyfileobj(inp, dest, length=8 * 1024 * 1024)
        cmd("resize2fs", "-M", out)
        cmd("e2fsck", "-fn", out)
        if not is_raw_ext4(out):
            raise RuntimeError("Compact image is not a raw ext4 filesystem")
        result = {"source_bytes": src.stat().st_size,
                  "output_bytes": out.stat().st_size,
                  "sha256": sha256(out), "source_sha256": sha256(src),
                  "not_flashable": True}
        result["saved_bytes"] = result["source_bytes"] - result["output_bytes"]
        if result["saved_bytes"] < 0:
            raise RuntimeError("Resize unexpectedly expanded system image")
        if limit is not None and result["output_bytes"] > limit:
            raise ValueError("Compact image still exceeds requested byte budget")
        return result
    except Exception:
        out.unlink(missing_ok=True)
        raise


def main():
    p = argparse.ArgumentParser(description="Make a compact ext4 candidate on separate path")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit-bytes", type=int)
    p.add_argument("--execute", action="store_true",
                   help="Required: perform offline resize on a new staging copy")
    a = p.parse_args()
    if not a.execute:
        p.error("No action taken: use --execute for a separate, local staging image")
    report = prepare(a.input, a.output, a.limit_bytes)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
