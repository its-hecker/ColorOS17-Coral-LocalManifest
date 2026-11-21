#!/usr/bin/env python3
"""Read-only genfscon rule provenance audit of exported ColorOS/Pixel CIL.

Uses the exact CIL input list from an existing split-policy compilation report.
The imsrtp rename probe does not alter genfscon rules, so its prior exported
CIL inputs are valid for identifying filesystem/path duplicates. This does
not automatically prove which duplicate caused secilc's post-DB failure.
Never removes, rewrites, or suppresses a rule.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

# Most compiled Android CIL renders each genfscon rule as one line:
# (genfscon proc /net (u object_r proc_net ((s0) (s0))))
# Other syntax is reported as unparsed instead of guessing.
GENFS = re.compile(r"^\s*\(genfscon\s+(\S+)\s+(\S+)\s+(.+?)\s*\)\s*$")


def scan(report_path, limit=80):
    report_path = report_path.resolve()
    original = json.loads(report_path.read_text())
    if original.get("status") != "HOST_CIL_COMPILATION_FAILED":
        raise ValueError("Expected original failed policy compilation report")
    inputs = original.get("cil_inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("No original CIL input provenance")
    by_key = collections.defaultdict(list)
    unparsed = []
    per_file = []
    count = 0
    for item in inputs:
        path = Path(item["host"])
        if not path.is_file():
            raise ValueError("CIL export missing: " + str(path))
        file_count = 0
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "(genfscon " not in line:
                continue
            match = GENFS.match(line)
            if not match:
                unparsed.append({"role": item["role"], "source": item["path"],
                                 "line": number, "text": line[:240]})
                continue
            fs, genpath, remainder = match.groups()
            record = {"role": item["role"], "source": item["path"],
                      "line": number, "filesystem": fs, "path": genpath,
                      "declaration": line.strip()[:500],
                      "context_repr": remainder.strip()}
            by_key[(fs, genpath)].append(record)
            count += 1
            file_count += 1
        per_file.append({"role": item["role"], "image_path": item["path"],
                         "genfscon_count": file_count})
    duplicated = {
        key: entries for key, entries in by_key.items() if len(entries) > 1
    }
    ordered = sorted(duplicated.items(),
                     key=lambda p: (len(set(e["context_repr"] for e in p[1])) <= 1,
                                    p[0][0], p[0][1]))
    conflicts = []
    ident = []
    for (fs, path), entries in ordered:
        labels = len(set(e["context_repr"] for e in entries))
        record = {"filesystem": fs, "path": path,
                  "distinct_declaration_count": labels,
                  "declarations": entries}
        (conflicts if labels > 1 else ident).append(record)
    return {
        "status": "GENFSCON_DUPLICATE_INPUT_AUDIT_ONLY",
        "from_original_split_policy_report": str(report_path),
        "rules_scanned": count,
        "unique_fs_path_pairs": len(by_key),
        "duplicate_path_count": len(duplicated),
        "different_context_path_count": len(conflicts),
        "identical_context_path_count": len(ident),
        "different_context_examples": conflicts[:limit],
        "identical_context_examples": ident[:min(limit, 20)],
        "unparsed_rule_count": len(unparsed),
        "unparsed_examples": unparsed[:limit],
        "inputs": per_file,
        "images_modified": False,
        "cil_modified": False,
        "policy_compilation_verified": False,
        "boot_verified": False,
        "warning": "Repeated fs/path rules are suspects, not a proven root cause. "
                   "Compare source policy and preserve legitimate labels. Do not "
                   "delete a genfscon rule or disable SELinux without review.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit", type=int, default=80)
    a = p.parse_args()
    if not 1 <= a.limit <= 500:
        raise ValueError("Limit must be 1..500")
    result = scan(a.report, a.limit)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "status": result["status"],
        "rules_scanned": result["rules_scanned"],
        "duplicate_path_count": result["duplicate_path_count"],
        "different_context_path_count": result["different_context_path_count"],
        "unparsed_rule_count": result["unparsed_rule_count"],
        "report": str(a.output)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
