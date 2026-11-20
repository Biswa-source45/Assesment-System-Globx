"""One SQL-script case, run in its own throw-away process (see sql.run_script). This file stands alone (stdlib only): the judge starts it with
`python -I -S -B`, as a separate user, with the usual memory and time limits, so a hostile script can only hurt itself.

stdin : {"schema", "seed", "dataset", "script", "checks"}
stdout: {"ok": true, "columns": ["check", "result"], "rows": [[check, outcome], ...]}  or  {"ok": false, "verdict": "RE|TLE", "error": "..."}

The trusted scripts (schema, seed, dataset) run first. Then the candidate's script runs with ATTACH, DETACH and PRAGMA denied and a time limit. Then the
author's checks run on the same database: a SELECT records its rows, any other statement records "ok" or "error: <kind>" (the message up to its first
colon, so "FOREIGN KEY constraint failed" matches whatever the constraint is called)."""
import decimal
import json
import sqlite3
import sys
import time

SECONDS = 3.0
DENIED = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}
SHOWN = 200  # rows kept from one SELECT check


def norm(v):
    """The same normal form as sql.result_payload, so floats and bytes compare the way they do everywhere else."""
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 6) if v != int(v) else (int(v) if abs(v) < 1e15 else v)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


def deadline(con):
    end = time.monotonic() + SECONDS
    con.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, 10000)


def fail(verdict, error):
    print(json.dumps({"ok": False, "verdict": verdict, "error": error}))


def main():
    req = json.load(sys.stdin)
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")       # a primary or foreign key that is not enforced would make the key tests meaningless
    con.execute("PRAGMA max_page_count=2000")   # about 8 MB: a script cannot fill the memory
    con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
    try:
        con.executescript(f"{req.get('schema') or ''}\n{req.get('seed') or ''}\n{req.get('dataset') or ''}")
    except sqlite3.Error as e:
        return fail("IE", f"The question's own set-up does not run: {e}")
    deadline(con)
    con.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in DENIED else sqlite3.SQLITE_OK)
    try:
        con.executescript(req.get("script") or "")
    except sqlite3.Error as e:
        msg = str(e)
        return fail("TLE" if "interrupt" in msg.lower() else "RE", msg)
    con.set_authorizer(None)  # the checks are the author's
    deadline(con)
    rows = []
    for check in req.get("checks") or []:
        try:
            cur = con.execute(check)
            if cur.description:
                data = [[norm(v) for v in r] for r in cur.fetchmany(SHOWN + 1)]
                outcome = json.dumps(data[:SHOWN], separators=(",", ":")) + (" ..." if len(data) > SHOWN else "")
            else:
                outcome = "ok"
        except sqlite3.Error as e:
            outcome = "error: " + str(e).split(":")[0].strip()[:80]
        rows.append([check, outcome])
    print(json.dumps({"ok": True, "columns": ["check", "result"], "rows": rows}))


if __name__ == "__main__":
    main()
