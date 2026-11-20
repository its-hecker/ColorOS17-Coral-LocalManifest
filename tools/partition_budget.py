#!/usr/bin/env python3
"""Fail-closed coral dynamic partition size assessment. Never flashes an image."""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "sources.lock.json").read_text())
PARTITIONS = ("system", "vendor", "product", "system_ext")
SPARSE_MAGIC = 0xED26FF3A


def image_bytes(path):
    """Use expanded Android sparse size, not compressed disk byte count."""
    with path.open("rb") as src:
        header = src.read(28)
    if len(header) >= 28 and struct.unpack_from("<I", header)[0] == SPARSE_MAGIC:
        (_, major, _minor, file_hdr_sz, _chunk_hdr_sz,
         block_size, total_blocks, _total_chunks, _checksum) = struct.unpack(
            "<IHHHHIIII", header)
        if major != 1 or file_hdr_sz < 28 or block_size not in (4096, 16384):
            raise ValueError("Unsupported Android sparse header: " + str(path))
        return block_size * total_blocks
    return path.stat().st_size


def group_size(board_config):
    text = board_config.read_text()
    m = re.search(r"^BOARD_GOOGLE_DYNAMIC_PARTITIONS_SIZE\s*:=\s*(\d+)",
                  text, re.M)
    if not m:
        raise ValueError("Cannot read actual coral dynamic partition group size")
    return int(m.group(1))


def assess(capacity, sizes, reserve=32*1024*1024):
    if capacity <= reserve or any(v is not None and v < 0 for v in sizes.values()):
        raise ValueError("Invalid group capacity or image byte count")
    missing = [p for p in PARTITIONS if sizes.get(p) is None]
    known = sum(sizes[p] for p in PARTITIONS if sizes.get(p) is not None)
    remaining = capacity - known - reserve
    return {"group_bytes": capacity, "images": dict(sizes),
            "reservation_bytes": reserve, "known_allocated_bytes": known,
            "remaining_after_reservation_bytes": remaining,
            "missing_partition_images": missing,
            "status": ("BLOCKED_OVERSIZE" if remaining < 0 else
                       "BLOCKED_UNMEASURED" if missing else "FITS_BYTES_ONLY"),
            "warning": "No flash until all images, super metadata, AVB and device boot are verified"}


def main():
    p = argparse.ArgumentParser(description="Coral raw/sparse partition fit checker")
    p.add_argument("--board-config", type=Path, required=True)
    p.add_argument("--system-img", type=Path)
    p.add_argument("--vendor-img", type=Path)
    p.add_argument("--product-img", type=Path)
    p.add_argument("--system-ext-img", type=Path)
    p.add_argument("--embed-product", action="store_true", help="ColorOS product is inside system.img")
    p.add_argument("--embed-system-ext", action="store_true", help="ColorOS system_ext is inside system.img")
    p.add_argument("--reserve-mib", type=int, default=32)
    p.add_argument("--output", type=Path, default=ROOT / "work/partition-budget.json")
    args = p.parse_args()
    size_map = {"system": image_bytes(args.system_img) if args.system_img else
                LOCK["donor"]["inspected"]["system_img_bytes"]}
    for name in ("vendor", "product", "system_ext"):
        path = getattr(args, name + "_img", None)
        embedded = (name == "product" and args.embed_product or
                    name == "system_ext" and args.embed_system_ext)
        if embedded and path:
            raise ValueError("An embedded partition cannot also have a separate image: " + name)
        size_map[name] = 0 if embedded else image_bytes(path) if path else None
    report = assess(group_size(args.board_config), size_map,
                    args.reserve_mib * 1024 * 1024)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["status"] != "FITS_BYTES_ONLY":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as e:
        print("ERROR:", e, file=sys.stderr)
        raise SystemExit(2)
