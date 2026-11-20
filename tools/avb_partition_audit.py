#!/usr/bin/env python3
"""Read-only comparison of coral's AVB/dynamic/OTA lists with ColorOS GSI mounts.

Never disables AVB or changes an image. The output intentionally remains
BLOCKED until actual descriptor/partition metadata is rebuilt and verified.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDED = {"product", "system_ext"}


def make_tokens(text, var):
    lines = text.splitlines()
    results = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s*" + re.escape(var) + r"\s*(?::=|\+=|=)\s*(.*)$", line)
        if not m:
            continue
        value = m.group(1)
        j = i
        while value.rstrip().endswith("\\") and j + 1 < len(lines):
            value = value.rstrip()[:-1] + " " + lines[j + 1]
            j += 1
        value = value.split("#", 1)[0].replace("\\", "")
        results.extend(value.split())
    return sorted(set(results))


def audit(board_text, fstab_text):
    avb = make_tokens(board_text, "BOARD_AVB_VBMETA_SYSTEM")
    group = make_tokens(board_text, "BOARD_GOOGLE_DYNAMIC_PARTITIONS_PARTITION_LIST")
    ota = make_tokens(board_text, "AB_OTA_PARTITIONS")
    active = []
    commented = []
    for line in fstab_text.splitlines():
        if line.startswith("# ColorOS17 embedded: "):
            commented.append(line.removeprefix("# ColorOS17 embedded: ").split()[0])
        elif line and not line.startswith("#"):
            active.append(line.split()[0])
    if not EMBEDDED.issubset(commented) or EMBEDDED.intersection(active):
        raise ValueError("The verified embedded product/system_ext mount candidate is absent")
    if "system" not in active or "vendor" not in active:
        raise ValueError("Missing essential system/vendor mounts")
    flagged = {
        "vbmeta_system_descriptor_still_references_embedded": sorted(EMBEDDED.intersection(avb)),
        "dynamic_partition_list_still_references_embedded": sorted(EMBEDDED.intersection(group)),
        "ota_partition_list_still_references_embedded": sorted(EMBEDDED.intersection(ota)),
    }
    return {
        "status": "BLOCKED_AVB_AND_SUPER_RECONCILIATION",
        "target": "coral",
        "embedded_mounts": sorted(EMBEDDED),
        "avb_vbmeta_system": avb,
        "dynamic_partition_group": group,
        "ota_partition_list": ota,
        "existing_source_inconsistencies": flagged,
        "required": [
            "Decide whether old logical partitions remain as genuine signed/empty images "
            "or are removed from the new super metadata and OTA declarations.",
            "Build and verify appropriate vbmeta_system descriptors and rollback indexes "
            "with real images. Never disable AVB as a substitute for image consistency.",
            "Verify first-stage fs_mgr resolves the GSI's embedded /product and /system_ext "
            "and the dynamic metadata matches the chosen layout.",
            "Check the resulting actual partition geometry and preserve userdata encryption.",
        ],
        "not_flashable": True
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--board", type=Path, required=True)
    p.add_argument("--fstab-candidate", type=Path, required=True)
    p.add_argument("--output", type=Path, default=ROOT / "work/firstboot/avb-audit.json")
    a = p.parse_args()
    report = audit(a.board.read_text(), a.fstab_candidate.read_text())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
