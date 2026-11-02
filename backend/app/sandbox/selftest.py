"""Sandbox self-test: compiles and runs a tiny program in every language + SQL engine."""
from __future__ import annotations

import json
import time
from typing import Dict, List

from app.sandbox.judge import judge_code, judge_sql, sql_expected_for
from app.sandbox.languages import REGISTRY
from app.sandbox.sql import SQL_ENGINES

PROGRAMS = {
    "python": "a, b = map(int, input().split())\nprint(a + b)\n",
    "c": "#include <stdio.h>\nint main(void){long a,b; if(scanf(\"%ld %ld\",&a,&b)!=2) return 1; printf(\"%ld\\n\",a+b); return 0;}\n",
    "cpp": "#include <iostream>\nint main(){long long a,b; std::cin>>a>>b; std::cout<<a+b<<\"\\n\"; return 0;}\n",
    "java": "import java.util.*;\npublic class Main { public static void main(String[] x){ Scanner s=new Scanner(System.in); long a=s.nextLong(), b=s.nextLong(); System.out.println(a+b);} }\n",
    "javascript": "const [a,b]=require('fs').readFileSync(0,'utf8').trim().split(/\\s+/).map(Number);\nconsole.log(a+b);\n",
}
CASES = [{"ordinal": 1, "visibility": "open", "input": "2 3\n", "expected": "5", "weight": 1},
         {"ordinal": 2, "visibility": "hidden", "input": "40 2\n", "expected": "42", "weight": 1}]


def run_selftest() -> Dict:
    out: List[Dict] = []
    for key, sb in REGISTRY.items():
        info = sb.info(refresh=True)
        row = {"key": key, "name": sb.name, "available": info["available"], "version": info["version"],
               "missing": info["missing"], "ok": False, "detail": ""}
        if info["available"]:
            t = time.time()
            r = judge_code({"time_limit_ms": 3000, "memory_mb": 256}, CASES, key, PROGRAMS[key], "validate")
            row["ok"] = r.get("status") == "done" and r.get("passed") == 2
            row["detail"] = (r.get("error") or (r.get("compile") or {}).get("message") or
                             ", ".join(c["verdict"] for c in r.get("cases", [])))
            row["seconds"] = round(time.time() - t, 2)
        out.append(row)
    cfg = {"schema": "CREATE TABLE t(id INTEGER, v INTEGER);", "seed": "", "engines": list(SQL_ENGINES),
           "reference_sql": "SELECT SUM(v) AS total FROM t", "ordered": True}
    for key, eng in SQL_ENGINES.items():
        row = {"key": f"sql:{key}", "name": eng.name, "available": eng.available(), "ok": False, "detail": ""}
        if eng.available():
            try:
                ds = "INSERT INTO t VALUES (1, 20); INSERT INTO t VALUES (2, 22);"
                exp = sql_expected_for(cfg, ds, key)
                r = judge_sql(cfg, [{"ordinal": 1, "visibility": "open", "input": ds, "expected": json.dumps(exp), "weight": 1}],
                              key, "SELECT SUM(v) AS total FROM t", "validate")
                row["ok"] = r.get("passed") == 1
                row["detail"] = ", ".join(c["verdict"] for c in r.get("cases", [])) or r.get("error", "")
            except Exception as e:
                row["detail"] = str(e)
        out.append(row)
    return {"results": out, "all_ok": all(r["ok"] for r in out if r["available"])}
