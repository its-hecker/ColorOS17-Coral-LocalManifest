#!/usr/bin/env python3
"""Inventory Pixel product/system_ext files that GSI embedded mounts would hide.

This reports *candidate* runtime dependencies for review, not a merge script.
Does not copy APKs, sign apps, alter the system image or authorize ADB.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDS = (
    ("product/app/PixelCameraServicesCoral", "camera", "Pixel camera services"),
    ("system_ext/priv-app/ims", "telephony", "Qualcomm/Pixel IMS"),
    ("system_ext/priv-app/grilservice", "telephony", "Google RIL"),
    ("system_ext/priv-app/qcrilmsgtunnel", "telephony", "RIL messaging tunnel"),
    ("system_ext/app/QtiTelephonyService", "telephony", "Qualcomm telephony"),
    ("system_ext/framework/google-ril.jar", "telephony", "Google RIL framework"),
    ("system_ext/framework/qcrilhook.jar", "telephony", "Qualcomm RIL hook framework"),
    ("system_ext/etc/permissions/org_codeaurora_ims.xml", "telephony", "IMS permissions"),
    ("system_ext/etc/permissions/google-ril.xml", "telephony", "Google RIL permissions"),
    ("product/etc/sysconfig/GoogleCamera_6gb_or_more_ram.xml", "camera", "GCam profile"),
    ("system_ext/etc/permissions/com.google.android.camera.extensions.xml",
     "camera", "Google Camera extensions"),
    ("system_ext/priv-app/EuiccGoogle", "esim", "Pixel eSIM"),
    ("product/priv-app/EuiccGoogle", "esim", "Google eSIM"),
)


def inspect_one(root, name, group, why):
    path = root / "proprietary" / name
    present = path.exists()
    if path.is_dir():
        count = sum(1 for x in path.rglob("*") if x.is_file())
    else:
        count = int(path.is_file())
    return {"destination": "/" + name, "source": str(path),
            "present": present, "source_entries": count,
            "group": group, "purpose": why,
            "action": "REVIEW_DONOR_COLLISION_AND_PERMISSIONS" if present else
                      "ABSENT_IN_SOURCE_REVIEW_MANUALLY"}


def audit(root):
    result = [inspect_one(root, *item) for item in NEEDS]
    count = sum(item["present"] for item in result)
    return {
        "status": "PLAN_ONLY_NOT_INSTALLED",
        "target": "coral", "source_vendor_tree": str(root.resolve()),
        "dependencies_present": count, "dependencies_checked": len(NEEDS),
        "candidates": result,
        "blockers": [
            "Pixel product/system_ext image content would be hidden if separate mounts omitted",
            "Donor may contain packages with the same package name or a different signing identity",
            "Actual built vendor SELinux contexts/permissions and linker namespacing not checked",
            "Build a constrained, signed, reviewable overlay rather than copying all Pixel apps"
        ],
        "warning": "Only presence in Git source was checked, not full ROM build or runtime."
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vendor-tree", type=Path, default=ROOT / "work/hardware/vendor")
    p.add_argument("--output", type=Path, default=ROOT / "work/pixel-runtime-deps.json")
    a = p.parse_args()
    if not (a.vendor_tree / "coral-vendor.mk").is_file():
        raise ValueError("Missing pinned Pixel vendor source")
    report = audit(a.vendor_tree)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"], "source": report["source_vendor_tree"],
        "present": report["dependencies_present"],
        "checked": report["dependencies_checked"],
        "missing": [x["destination"] for x in report["candidates"] if not x["present"]],
        "blockers": report["blockers"]
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print("ERROR:", error, file=sys.stderr)
        raise SystemExit(2)
