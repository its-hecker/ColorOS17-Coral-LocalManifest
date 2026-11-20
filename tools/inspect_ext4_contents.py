#!/usr/bin/env python3
"""Read-only donor ext4 interior inspection. No mounted filesystem or binary upload.

Requires: e2fsprogs (debugfs, dumpe2fs, resize2fs). Downloads/extracts a
local ZIP's system.img to an ignored workdir; reports high-level metadata only.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "sources.lock.json").read_text())
BASE = ROOT / "work" / "donor"


def run(args, timeout=180):
    result = subprocess.run(args, capture_output=True, text=True, errors="replace",
                            check=False, timeout=timeout)
    return {"code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def inspect_image(path):
    header = path.open("rb").read(4096)
    if header[1080:1082] != b"\x53\xef":
        raise ValueError("Refusing non-raw-ext4 donor image: inspect the format first")
    summary = run(["dumpe2fs", "-h", str(path)], timeout=120)
    if summary["code"] != 0:
        raise RuntimeError("dumpe2fs failed: " + summary["stderr"][:400])
    geometry = {}
    for label in ("Block count", "Free blocks", "Block size", "Inode count",
                  "Filesystem features", "Filesystem state"):
        m = re.search(r"^" + re.escape(label) + r":\s*(.+)$", summary["stdout"], re.M)
        geometry[label.lower().replace(" ", "_")] = m.group(1).strip() if m else None
    minimum = run(["resize2fs", "-P", str(path)], timeout=120)
    estimate = re.search(r"(\d+)\s*$", minimum["stdout"].strip())
    geometry["estimated_minimum_blocks"] = int(estimate.group(1)) if estimate else None
    # List only known paths, not proprietary file bytes. Missing paths are normal.
    probes = ["/", "/system", "/system/system_ext", "/system/product",
              "/system/my_stock", "/system/my_product", "/system/system",
              "/system_ext", "/product", "/my_stock", "/my_product", "/system/etc",
              "/system/etc/selinux", "/system/system/etc", "/system/system_ext/etc"]
    listing = {}
    for p in probes:
        r = run(["debugfs", "-R", "ls -p " + p, str(path)], timeout=45)
        raw = r["stdout"][:5500]
        missing = ("File not found" in r["stderr"] or "not found" in r["stderr"].lower() or
                   "File not found" in raw)
        listing[p] = {"exists": not missing and r["code"] == 0,
                      "entry_names": sorted(set(re.findall(
                          r"/\d+/\d+/\d+/\d+/([^/\n]+)/", raw)))[:150],
                      "read_error": r["stderr"][-160:] if missing else None}
    return {"image_size_bytes": path.stat().st_size, "filesystem": "ext4",
            "geometry": geometry, "paths": listing, "source": "read-only debugfs inspection",
            "note": "Only high-level directory and inode metadata; no ROM image created"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--zip", type=Path, default=BASE / LOCK["donor"]["filename"])
    p.add_argument("--output", type=Path, default=ROOT / "work/donor-ext4-layout.json")
    p.add_argument("--keep-image", action="store_true", help="Retain temporary raw image")
    a = p.parse_args()
    if not all(shutil.which(x) for x in ("debugfs", "dumpe2fs", "resize2fs")):
        raise RuntimeError("Install e2fsprogs; debugfs/dumpe2fs/resize2fs are required")
    zip_path = a.zip.expanduser().resolve()
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Missing/invalid donor ZIP: " + str(zip_path))
    digest = hashlib.sha256()
    with zip_path.open("rb") as stream:
        for data in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(data)
    if digest.hexdigest() != LOCK["donor"]["sha256"]:
        raise ValueError("Donor SHA-256 mismatch; rejecting unpinned input")
    image = zip_path.parent / "system-for-inspection.img"
    if image.exists():
        raise RuntimeError("Temporary image already exists: " + str(image))
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != "system.img":
                raise ValueError("Expected the verified PLK110 single-system-image ZIP")
            with archive.open(members[0]) as source, image.open("xb") as sink:
                while True:
                    buf = source.read(8 * 1024 * 1024)
                    if not buf:
                        break
                    sink.write(buf)
        result = inspect_image(image)
        result["donor_sha256"] = digest.hexdigest()
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        print("Report:", a.output)
    finally:
        if not a.keep_image:
            image.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
