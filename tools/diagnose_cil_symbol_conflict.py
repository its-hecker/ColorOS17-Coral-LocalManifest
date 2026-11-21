#!/usr/bin/env python3
"""Pinpoint conflicting SELinux CIL type/typeattribute declarations by origin.

Consumes the exact CIL inputs exported by check_coloros_split_sepolicy.py.
Never modifies files, policies, AVB, or images; does not propose unsafe
removal or re-labeling. Identifies declarations but does not certify a fix.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ERROR_SYMBOL = re.compile(
    r"Re-declaration of type(?:attribute)?\s+([A-Za-z_][A-Za-z0-9_]*)")
DECL = re.compile(
    r"^\s*\((type|typeattribute)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)",
    re.M)


def diagnose(report_path, requested_symbol=None):
    report = json.loads(report_path.read_text())
    if report.get("status") != "HOST_CIL_COMPILATION_FAILED":
        raise ValueError("Expected a failed split-CIL report")
    log_path = Path(report["log"])
    log = log_path.read_text()
    if requested_symbol is None:
        match = ERROR_SYMBOL.search(log)
        if not match:
            raise ValueError("No type or typeattribute collision in compiler log")
        symbol = match.group(1)
    else:
        symbol = requested_symbol
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
            raise ValueError("Invalid CIL symbol")
    entries = []
    for item in report["cil_inputs"]:
        path = Path(item["host"])
        if not path.is_file():
            raise ValueError("Missing exported CIL input: " + str(path))
        body = path.read_text()
        for match in DECL.finditer(body):
            kind, candidate = match.groups()
            if candidate != symbol:
                continue
            line = body.count("\n", 0, match.start()) + 1
            surrounding = body.splitlines()
            excerpt = "\n".join(
                f"{n + 1}: {surrounding[n]}"
                for n in range(max(0, line - 2),
                               min(len(surrounding), line + 2)))
            entries.append({
                "kind": kind, "role": item["role"],
                "image_path": item["path"],
                "host_file": str(path),
                "line": line,
                "context": excerpt,
            })
    kinds = set(x["kind"] for x in entries)
    result = {
        "symbol": symbol,
        "status": ("TYPE_TYPEATTRIBUTE_CONFLICT_FOUND"
                   if kinds == {"type", "typeattribute"}
                   else "DECLARATION_INVENTORY_INCONCLUSIVE"),
        "declarations": entries,
        "compiler_error_excerpt": "\n".join(
            x for x in log.splitlines()
            if symbol in x or "Failed to build AST" in x)[:6000],
        "source_artifacts_modified": False,
        "policy_fixed": False,
        "boot_verified": False,
        "next_action": "Inspect the original vendor/platform .te declarations "
                       "and versioned public policy provenance before changing "
                       "any policy. Never remove a type/attribute just to pass secilc.",
    }
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--symbol", help="default: extract first symbol from secilc log")
    p.add_argument("--output", type=Path, required=True)
    x = p.parse_args()
    r = diagnose(x.report, x.symbol)
    x.output.parent.mkdir(parents=True, exist_ok=True)
    x.output.write_text(json.dumps(r, indent=2) + "\n")
    print(json.dumps(r, indent=2))
    return 0 if r["status"] == "TYPE_TYPEATTRIBUTE_CONFLICT_FOUND" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, UnicodeDecodeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
