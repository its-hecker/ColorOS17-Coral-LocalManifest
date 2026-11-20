#!/usr/bin/env python3
"""Stage-0: reproduce source inputs without modifying their upstream repositories."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "sources.lock.json"


def run(*args, env=None):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, env=env)


def validate(items):
    seen = set()
    for item in items:
        if not re.fullmatch(r"[0-9a-f]{40}", item["commit"]):
            raise ValueError("Invalid immutable commit for " + item["id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", item["repository"]):
            raise ValueError("Invalid GitHub repository for " + item["id"])
        p = PurePosixPath(item["path"])
        if p.is_absolute() or ".." in p.parts or "." == str(p) or str(p) in seen:
            raise ValueError("Unsafe or duplicate checkout path: " + str(p))
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", item["branch"]) or ".." in item["branch"]:
            raise ValueError("Unsafe branch name")
        seen.add(str(p))


def ensure_checkout(item, workspace):
    dest = workspace / item["path"]
    rev = item["commit"]
    if dest.exists():
        if not (dest / ".git").exists():
            raise RuntimeError("Path exists but is not a clone: " + str(dest))
        found = subprocess.check_output(
            ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
        ).strip()
        if found != rev:
            raise RuntimeError(f"{item['id']} is at {found}, expected {rev}; refusing reset")
        print("Pinned source already present:", item["id"])
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    url = "https://github.com/" + item["repository"] + ".git"
    run("git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, dest, env=env)
    run("git", "-C", dest, "fetch", "--quiet", "--depth=1", "origin",
        "refs/heads/" + item["branch"], env=env)
    run("git", "-C", dest, "checkout", "--quiet", "--detach", rev, env=env)
    found = subprocess.check_output(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
    ).strip()
    if found != rev:
        raise RuntimeError(f"Checkout pin mismatch: {item['id']} {found} != {rev}")


def audit(workspace):
    validations = [
        ("device", "adapters/device/tools/audit_device.py", "hardware/device"),
        ("vendor", "adapters/vendor/tools/audit_vendor.py", "hardware/vendor"),
        ("kernel", "adapters/kernel/tools/audit_kernel.py", "hardware/kernel"),
    ]
    results = {}
    for name, script, source in validations:
        script_path, source_path = workspace / script, workspace / source
        print("\nAudit:", name, flush=True)
        completed = subprocess.run([sys.executable, str(script_path), str(source_path)],
                                   check=False)
        results[name] = completed.returncode == 0
    return results


def main():
    p = argparse.ArgumentParser(description="Pinned ColorOS17 coral source preparation")
    p.add_argument("--workdir", type=Path, default=ROOT / "work")
    p.add_argument("--audit", action="store_true", help="Run device/vendor/kernel checks")
    p.add_argument("--with-reference", action="store_true",
                   help="Also clone community OnePlus 7 port source; never its images")
    args = p.parse_args()
    lock = json.loads(LOCK.read_text())
    validate(lock["sources"])
    workspace = args.workdir.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    installed = []
    for item in lock["sources"]:
        if item.get("optional") and not args.with_reference:
            continue
        ensure_checkout(item, workspace)
        installed.append({"id": item["id"], "path": item["path"],
                          "commit": item["commit"]})
    findings = audit(workspace) if args.audit else {}
    report = {"status": "input-only; NOT BOOTABLE", "target": "coral",
              "checkouts": installed, "audits": findings}
    report_path = workspace / "bootstrap-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print("\nReport:", report_path)
    if args.audit and not all(findings.values()):
        raise RuntimeError("Source audits failed; review missing inputs before porting")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
