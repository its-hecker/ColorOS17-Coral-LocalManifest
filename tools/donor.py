#!/usr/bin/env python3
"""Download and inspect a ColorOS donor ZIP; NEVER produce a flashable image."""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "sources.lock.json").read_text())
DONOR = LOCK["donor"]
DEFAULT_PATH = ROOT / "work" / "donor" / DONOR["filename"]


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def kind_from_prefix(prefix):
    if prefix[:4] == b"\x3a\xff\x26\xed":
        return "android-sparse"
    if prefix[1024:1028] == b"\xe2\xe1\xf5\xe0":
        return "erofs"
    if prefix[1080:1082] == b"\x53\xef":
        return "ext4"
    if prefix[:4] == b"AVB0":
        return "avb"
    return "unknown-or-compressed"


def inspect_zip(path, full_crc=False):
    if not zipfile.is_zipfile(path):
        raise ValueError("Not a valid ZIP archive: " + str(path))
    images = []
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("Unsafe path in ZIP. Refusing this donor.")
        for info in archive.infolist():
            if info.is_dir() or not (
                info.filename.lower().endswith((".img", ".img.gz", ".img.zst", ".img.xz"))
                or "super" in info.filename.lower() and "img" in info.filename.lower()
            ):
                continue
            with archive.open(info, "r") as entry:
                prefix = entry.read(4096)
            images.append({"name": info.filename, "size": info.file_size,
                           "image_format": kind_from_prefix(prefix)})
        corrupt = archive.testzip() if full_crc else None
    return {"target": "coral", "donor": DONOR["name"], "archive": str(path.resolve()),
            "archive_bytes": path.stat().st_size, "sha256": hash_file(path),
            "zip_entries": len(names), "images": images,
            "full_crc_checked": full_crc, "first_corrupt_member": corrupt,
            "stage": "inspection only; NO port or flashable image built"}


def download(path):
    if path.exists():
        print("Reusing existing donor ZIP:", path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    if partial.exists():
        raise RuntimeError("Incomplete download exists: " + str(partial) +
                           "; inspect/remove it before retrying")
    req = urllib.request.Request(DONOR["url"],
                                 headers={"User-Agent": "ColorOS17-coral-source-audit/0.1"})
    print("Downloading community donor to", path, "(several GB)", flush=True)
    with urllib.request.urlopen(req, timeout=120) as response:
        with partial.open("xb") as out:
            while True:
                data = response.read(4 * 1024 * 1024)
                if not data:
                    break
                out.write(data)
    if not zipfile.is_zipfile(partial):
        raise ValueError("Downloaded payload is not ZIP (mirror or network failure)")
    expected = DONOR.get("sha256")
    digest = hash_file(partial)
    if expected and digest.lower() != expected.lower():
        raise ValueError("Donor SHA-256 mismatch; refusing promotion")
    os.replace(partial, path)
    print("Downloaded:", path, "\nSHA-256:", digest)


def main():
    p = argparse.ArgumentParser(description="Download/inspect ColorOS17 PLK110 GSI")
    p.add_argument("--file", type=Path, default=DEFAULT_PATH,
                   help="Override donor archive path")
    p.add_argument("--download", action="store_true", help="Fetch from pinned community URL")
    p.add_argument("--inspect", action="store_true", help="Inspect ZIP and image headers")
    p.add_argument("--full-crc", action="store_true",
                   help="Read all ZIP members to check their CRCs")
    a = p.parse_args()
    if not (a.download or a.inspect):
        p.error("Specify --download and/or --inspect")
    archive = a.file.expanduser().resolve()
    if a.download:
        download(archive)
    if a.inspect:
        result = inspect_zip(archive, full_crc=a.full_crc)
        report = ROOT / "work" / "donor-inspection.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        print("\nSaved:", report)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
