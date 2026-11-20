#!/usr/bin/env python3
"""Apply only reviewed donor system_ext/product property-context fixes in place.

Preserves inode/xattrs by truncating existing files rather than replacing them.
Requires already-mounted source paths; refuses platform or ambiguous collisions.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ensure_safe(root, path):
    root = root.resolve()
    candidate = (root / path).resolve()
    if root not in candidate.parents:
        raise ValueError("Path escapes mounted donor: " + path)
    if not (path.startswith("system_ext/etc/selinux/") or
            path.startswith("product/etc/selinux/")):
        raise ValueError("Refusing to modify platform or vendor contexts")
    if not candidate.is_file():
        raise ValueError("Missing existing SELinux context file " + str(candidate))
    return candidate


def apply(donor, vendor, output, sudo=()):
    donor, vendor, output = donor.resolve(), vendor.resolve(), output.resolve()
    scanner = ROOT / "work/adapters/vendor/tools/resolve_property_contexts.py"
    if not scanner.is_file():
        raise ValueError("Missing pinned collision resolver")
    result_dir = output / "propctx"
    result_dir.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, str(scanner), "--donor-root", str(donor),
                        "--vendor-root", str(vendor), "--output", str(result_dir)],
                       capture_output=True, text=True, check=False)
    if p.returncode:
        raise RuntimeError("Property context scanner failed: " + p.stderr[-1000:])
    report = json.loads((result_dir / "report.json").read_text())
    if report.get("blocked"):
        raise ValueError("Unresolved property-context collision(s), see " +
                         str(result_dir / "report.json"))
    updated = []
    # Only use output files explicitly identified by the pinned scanner.
    for row in report["unmodified"]:
        if row["status"] != "candidate generated":
            continue
        rel = row["file"]
        target = ensure_safe(donor, rel)
        content = (result_dir / rel).read_bytes()
        if len(content) == 0:
            raise ValueError("Refusing to replace contexts with an empty file")
        # Path.write_bytes reuses the inode, retains the original SELinux label.
        code = ("from pathlib import Path; import sys; "
                "p=Path(sys.argv[1]); p.write_bytes(Path(sys.argv[2]).read_bytes())")
        subprocess.run([*sudo, sys.executable, "-c", code, str(target),
                        str(result_dir / rel)], check=True)
        if target.read_bytes() != content:
            raise RuntimeError("Property-context write verification failed")
        updated.append(rel)
    return {"updated": updated, "blocked": [], "report": str(result_dir / "report.json")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--donor-root", type=Path, required=True)
    p.add_argument("--vendor-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(apply(args.donor_root, args.vendor_root, args.output),
                     indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
        print("ERROR:", e, file=sys.stderr)
        raise SystemExit(2)
