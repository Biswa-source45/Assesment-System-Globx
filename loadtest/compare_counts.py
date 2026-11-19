"""Compares two outputs of snapshot_counts.py (before a test, after the cleanup) and says whether the cleanup left the data as it was.

  python compare_counts.py before.json after.json [--allow audit_logs,refresh_tokens] [--out compare.json]

Rows that the test's own administrator sign-in adds (audit entries and sign-in tokens of the Super Admin) are listed as expected differences; anything else that
differs is a failure. The database and storage sizes may differ a little (the database keeps free pages); they are reported, not judged beyond a generous limit."""
import argparse
import json
import sys


def load(path):
    text = open(path, encoding="utf-8").read().strip().splitlines()
    return json.loads(next(line for line in reversed(text) if line.startswith("{")))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--allow", default="audit_logs,refresh_tokens")
    p.add_argument("--out", default="")
    a = p.parse_args()
    b, c = load(a.before), load(a.after)
    allowed = set(x for x in a.allow.split(",") if x)
    rows, bad = [], []
    for t in sorted(set(b["tables"]) | set(c["tables"])):
        x, y = b["tables"].get(t, 0), c["tables"].get(t, 0)
        status = "same" if x == y else ("expected" if t in allowed and y >= x else "DIFFERENT")
        rows.append({"table": t, "before": x, "after": y, "status": status})
        if status == "DIFFERENT":
            bad.append(t)
    size_ok = c["database_mb"] <= max(b["database_mb"] * 1.5, b["database_mb"] + 30) and c["storage_mb"] <= b["storage_mb"] + 5 and c["storage_files"] <= b["storage_files"] + 5
    out = {"ok": not bad and size_ok, "different_tables": bad, "tables": rows, "database_mb": [b["database_mb"], c["database_mb"]], "storage_mb": [b["storage_mb"], c["storage_mb"]],
           "storage_files": [b["storage_files"], c["storage_files"]], "before_at": b["at"], "after_at": c["at"]}
    if a.out:
        open(a.out, "w", encoding="utf-8").write(json.dumps(out, indent=2))
    for r in rows:
        if r["status"] != "same":
            print(f"  {r['table']}: {r['before']} -> {r['after']} ({r['status']})")
    print(f"database {out['database_mb'][0]} -> {out['database_mb'][1]} MB; storage {out['storage_mb'][0]} -> {out['storage_mb'][1]} MB, files {out['storage_files'][0]} -> {out['storage_files'][1]}")
    print("CLEAN: every table is as it was" if out["ok"] else f"NOT CLEAN: {bad or 'sizes'}")
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
