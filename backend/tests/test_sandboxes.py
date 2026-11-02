import json

import pytest

from app.sandbox.judge import judge_code, judge_sql, sql_expected_for
from app.sandbox.languages import REGISTRY
from app.sandbox.selftest import CASES, PROGRAMS

CFG = {"time_limit_ms": 2000, "memory_mb": 256}


@pytest.mark.parametrize("lang", list(REGISTRY))
def test_each_language_accepts_correct_program(lang):
    if not REGISTRY[lang].available():
        pytest.skip(f"{lang} toolchain not installed")
    r = judge_code(CFG, CASES, lang, PROGRAMS[lang], "submit")
    assert r["status"] == "done", r
    assert [c["verdict"] for c in r["cases"]] == ["AC", "AC"]
    assert r["score"] == 2


def test_python_verdicts():
    one = CASES[:1]
    assert judge_code(CFG, one, "python", "print(4)", "submit")["cases"][0]["verdict"] == "WA"
    assert judge_code(CFG, one, "python", "raise SystemExit(2)", "submit")["cases"][0]["verdict"] == "RE"
    assert judge_code(CFG, one, "python", "def x(:\n  pass", "submit")["cases"][0]["verdict"] == "CE"
    assert judge_code({"time_limit_ms": 300, "memory_mb": 64}, one, "python", "while True: pass", "submit")["cases"][0]["verdict"] == "TLE"
    assert judge_code(CFG, one, "python", "x = bytearray(900 * 1024 * 1024)", "submit")["cases"][0]["verdict"] == "MLE"
    assert judge_code(CFG, one, "python", "while True: print('x' * 4096)", "submit")["cases"][0]["verdict"] == "OLE"


def test_run_only_uses_open_cases_and_custom_input():
    r = judge_code(CFG, CASES, "python", PROGRAMS["python"], "run", custom_input="7 8\n")
    assert len(r["cases"]) == 1 and r["custom"]["stdout"].strip() == "15"


def test_cpp_compile_error():
    if not REGISTRY["cpp"].available():
        pytest.skip("g++ not installed")
    r = judge_code(CFG, CASES, "cpp", "int main(){ return y; }", "submit")
    assert not r["compile"]["ok"] and r["cases"][0]["verdict"] == "CE"


def test_sql_sqlite_readonly_and_compare():
    cfg = {"schema": "CREATE TABLE t(id INT, v INT);", "seed": "", "engines": ["sqlite"], "ordered": False,
           "reference_sql": "SELECT id FROM t WHERE v > 1"}
    ds = "INSERT INTO t VALUES (1,1),(2,5),(3,9);"
    exp = json.dumps(sql_expected_for(cfg, ds))
    cases = [{"ordinal": 1, "visibility": "open", "input": ds, "expected": exp, "weight": 1}]
    assert judge_sql(cfg, cases, "sqlite", "select id from t where v>1 order by id desc", "submit")["cases"][0]["verdict"] == "AC"
    assert judge_sql(cfg, cases, "sqlite", "select id from t", "submit")["cases"][0]["verdict"] == "WA"
    assert judge_sql(cfg, cases, "sqlite", "delete from t", "submit")["cases"][0]["verdict"] == "RE"
    assert judge_sql(cfg, cases, "sqlite", "select 1; drop table t", "submit")["cases"][0]["verdict"] == "RE"
