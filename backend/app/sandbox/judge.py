"""Judge: runs a submission against a question's test cases and produces verdicts and a weighted score."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from app.domain.scoring import compare_output, cross_verification_flags, r2
from app.sandbox import remote
from app.sandbox.languages import get_language
from app.sandbox.process import new_workdir, remove_workdir
from app.sandbox.sql import SQL_ENGINES, compare_results

OPEN_LIMIT = 4096


def _verdict_from_proc(p, expected: Optional[str], comparator: str) -> str:
    if p.error:
        return "IE"
    if p.timed_out:
        return "TLE"
    if p.mem_exceeded:
        return "MLE"
    if p.output_exceeded:
        return "OLE"
    if p.exit_code not in (0, None):
        low = (p.stderr or "").lower()
        if "outofmemoryerror" in low or "memoryerror" in low or "bad_alloc" in low or "heap out of memory" in low:
            return "MLE"
        return "RE"
    if expected is None:
        return "OK"
    return "AC" if compare_output(p.stdout, expected, comparator) else "WA"


def local_judge_code(cfg: Dict, cases: List[Dict], language: str, source: str, kind: str,
                     custom_input: Optional[str] = None) -> Dict:
    """cases: [{id, ordinal, visibility, input, expected, weight}] ; kind: run|submit|validate."""
    lang = get_language(language)
    allowed = cfg.get("languages") or []
    if lang is None:
        return {"status": "error", "error": f"Unknown language '{language}'"}
    if allowed and lang.key not in allowed and kind != "validate":
        return {"status": "error", "error": f"{lang.name} is not allowed for this question"}
    if not lang.available():
        return {"status": "error", "error": f"{lang.name} is not installed on this server "
                                            f"(missing: {', '.join(lang.info()['missing'])})"}
    if len(source or "") > 64 * 1024:
        return {"status": "error", "error": "Source code exceeds 64 KB"}
    time_ms = int(cfg.get("time_limit_ms") or 2000)
    mem = int(cfg.get("memory_mb") or 256)
    comparator = cfg.get("comparator") or "trim"
    selected = [c for c in cases if kind != "run" or c["visibility"] == "open"]
    wd = new_workdir()
    try:
        comp = lang.compile(wd, source)
        out: Dict = {"status": "done", "language": lang.key, "compile": {"ok": comp.ok, "message": comp.message,
                                                                         "time_ms": comp.time_ms}, "cases": []}
        if not comp.ok:
            for c in selected:
                out["cases"].append({"ordinal": c["ordinal"], "visibility": c["visibility"], "verdict": "CE",
                                     "passed": False, "weight": float(c["weight"]), "time_ms": 0, "memory_kb": 0})
            if custom_input is not None:
                out["custom"] = {"verdict": "CE", "stdout": "", "stderr": comp.message}
        else:
            for c in selected:
                p = lang.run(wd, source, c["input"], time_ms, mem)
                v = _verdict_from_proc(p, c["expected"], comparator)
                row = {"ordinal": c["ordinal"], "visibility": c["visibility"], "verdict": v, "passed": v == "AC",
                       "weight": float(c["weight"]), "time_ms": p.cpu_ms, "wall_ms": p.wall_ms, "memory_kb": p.peak_kb,
                       "input": c["input"][:OPEN_LIMIT], "expected": c["expected"][:OPEN_LIMIT],
                       "stdout": p.stdout[:OPEN_LIMIT], "stderr": (p.stderr or p.error)[:2048]}
                out["cases"].append(row)
            if custom_input is not None:
                p = lang.run(wd, source, custom_input, time_ms, mem)
                out["custom"] = {"verdict": _verdict_from_proc(p, None, comparator), "stdout": p.stdout[:OPEN_LIMIT],
                                 "stderr": (p.stderr or p.error)[:2048], "time_ms": p.cpu_ms, "memory_kb": p.peak_kb}
        out["score"] = r2(sum(c["weight"] for c in out["cases"] if c["passed"]))
        out["max_score"] = r2(sum(c["weight"] for c in out["cases"]))
        out["passed"] = sum(1 for c in out["cases"] if c["passed"])
        out["total"] = len(out["cases"])
        out["flags"] = cross_verification_flags(out["cases"]) if kind != "run" else []
        return out
    finally:
        remove_workdir(wd)


def local_run_reference(cfg: Dict, language: str, source: str, inputs: List[str]) -> List[Dict]:
    """Run the admin's reference solution on each input; its stdout becomes the expected output.
    Returns [{input, expected, ok, verdict}]. Raises ValueError if the solution cannot be run at all."""
    lang = get_language(language)
    if lang is None or not lang.available():
        raise ValueError(f"'{language}' is not available on this server")
    time_ms, mem = int(cfg.get("time_limit_ms") or 2000), int(cfg.get("memory_mb") or 256)
    wd = new_workdir()
    try:
        comp = lang.compile(wd, source)
        if not comp.ok:
            raise ValueError("The reference solution does not compile: " + comp.message)
        out = []
        for inp in inputs:
            p = lang.run(wd, source, inp, time_ms, mem)
            v = _verdict_from_proc(p, None, "trim")
            out.append({"input": inp, "expected": p.stdout.replace("\r\n", "\n").rstrip("\n") if v == "OK" else "", "ok": v == "OK", "verdict": v})
        return out
    finally:
        remove_workdir(wd)


def local_judge_sql(cfg: Dict, cases: List[Dict], engine: str, query: str, kind: str) -> Dict:
    eng = SQL_ENGINES.get((engine or "sqlite").lower())
    allowed = cfg.get("engines") or ["sqlite"]
    if eng is None:
        return {"status": "error", "error": f"Unknown SQL engine '{engine}'"}
    if eng.key not in allowed and kind != "validate":
        return {"status": "error", "error": f"{eng.name} is not allowed for this question"}
    if not eng.available():
        return {"status": "error", "error": f"{eng.name} is not configured on this server"}
    ordered = bool(cfg.get("ordered"))
    out: Dict = {"status": "done", "language": "sql", "engine": eng.key, "cases": []}
    selected = [c for c in cases if kind != "run" or c["visibility"] == "open"]
    for c in selected:
        r = eng.run(cfg.get("schema", ""), cfg.get("seed", ""), c["input"], query)
        if r.get("ok"):
            try:
                exp = json.loads(c["expected"] or "{}")
            except Exception:
                exp = {}
            passed = bool(exp) and compare_results(r, exp, ordered)
            v = "AC" if passed else "WA"
        else:
            exp, passed, v = None, False, r.get("verdict", "RE")
        out["cases"].append({"ordinal": c["ordinal"], "visibility": c["visibility"], "verdict": v, "passed": passed,
                             "weight": float(c["weight"]), "time_ms": r.get("time_ms", 0), "memory_kb": 0,
                             "result": {"columns": r.get("columns", []), "rows": r.get("rows", [])[:50]} if r.get("ok") else None,
                             "expected_result": ({"columns": exp.get("columns", []), "rows": exp.get("rows", [])[:50]}
                                                 if isinstance(exp, dict) and exp else None),
                             "stderr": r.get("error", "")})
    if kind == "run" and not selected:
        r = eng.run(cfg.get("schema", ""), cfg.get("seed", ""), "", query)
        out["custom"] = r
    out["score"] = r2(sum(c["weight"] for c in out["cases"] if c["passed"]))
    out["max_score"] = r2(sum(c["weight"] for c in out["cases"]))
    out["passed"] = sum(1 for c in out["cases"] if c["passed"])
    out["total"] = len(out["cases"])
    out["flags"] = cross_verification_flags(out["cases"]) if kind != "run" else []
    return out


def local_sql_expected_for(cfg: Dict, dataset: str, engine: str = "sqlite") -> Dict:
    """Compute expected result JSON for a dataset by running the reference query."""
    eng = SQL_ENGINES.get(engine) or SQL_ENGINES["sqlite"]
    r = eng.run(cfg.get("schema", ""), cfg.get("seed", ""), dataset, cfg.get("reference_sql", ""))
    if not r.get("ok"):
        raise ValueError(f"Reference query failed: {r.get('error')}")
    return {"columns": r["columns"], "rows": r["rows"]}


# What the rest of the application calls. In production these go to the isolated judge; they never run candidate code in this process.
def judge_code(cfg: Dict, cases: List[Dict], language: str, source: str, kind: str, custom_input: Optional[str] = None) -> Dict:
    if remote.blocked():
        return {"status": "error", "error": remote.NOT_ISOLATED}
    if not remote.enabled():
        return local_judge_code(cfg, cases, language, source, kind, custom_input)
    try:
        return remote.call("judge_code", cfg=cfg, cases=cases, language=language, source=source, kind=kind, custom_input=custom_input)
    except remote.Unavailable as e:
        return {"status": "error", "error": str(e)}


def judge_sql(cfg: Dict, cases: List[Dict], engine: str, query: str, kind: str) -> Dict:
    if remote.blocked():
        return {"status": "error", "error": remote.NOT_ISOLATED}
    if not remote.enabled():
        return local_judge_sql(cfg, cases, engine, query, kind)
    try:
        return remote.call("judge_sql", cfg=cfg, cases=cases, engine=engine, query=query, kind=kind)
    except remote.Unavailable as e:
        return {"status": "error", "error": str(e)}


def run_reference(cfg: Dict, language: str, source: str, inputs: List[str]) -> List[Dict]:
    """Raises ValueError (with a message for the author) when the solution cannot be run, as before."""
    if remote.blocked():
        raise ValueError(remote.NOT_ISOLATED)
    if not remote.enabled():
        return local_run_reference(cfg, language, source, inputs)
    try:
        return remote.call("run_reference", cfg=cfg, language=language, source=source, inputs=inputs)
    except remote.Unavailable as e:
        raise ValueError(str(e))


def sql_expected_for(cfg: Dict, dataset: str, engine: str = "sqlite") -> Dict:
    if remote.blocked():
        raise ValueError(remote.NOT_ISOLATED)
    if not remote.enabled():
        return local_sql_expected_for(cfg, dataset, engine)
    try:
        return remote.call("sql_expected_for", cfg=cfg, dataset=dataset, engine=engine)
    except remote.Unavailable as e:
        raise ValueError(str(e))


def public_view(result: Dict, show_hidden_counts: bool = True) -> Dict:
    """Strip hidden case data before sending results to a candidate."""
    if not result:
        return {}
    res = {k: v for k, v in result.items() if k not in ("cases",)}
    opn, hid = [], []
    for c in result.get("cases", []):
        if c["visibility"] == "open":
            opn.append(c)
        else:
            # the verdict code (AC, WA, TLE, ...) says how it went, never what the test case contains
            hid.append({"ordinal": c["ordinal"], "verdict": c["verdict"],
                        "passed": c["passed"], "weight": c["weight"], "time_ms": c.get("time_ms"),
                        "memory_kb": c.get("memory_kb")})
    res["open"] = opn
    res["hidden"] = {"passed": sum(1 for h in hid if h["passed"]), "total": len(hid),
                     "cases": hid if show_hidden_counts else []}
    res.pop("flags", None)
    return res
