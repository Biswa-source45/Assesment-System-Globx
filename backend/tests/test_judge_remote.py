"""The isolated judge: the same answers as running locally, a refusal in production without it, a clear message when it is down, and a whitelist."""
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from test_exam_rules import PW, _login, client  # noqa: F401  (client is a fixture)

import judge_service
from app.core.config import get_settings
from app.sandbox import remote
from app.sandbox.judge import (judge_code, judge_sql, local_judge_code, local_judge_sql, local_run_reference, local_sql_expected_for,
                               run_reference, sql_expected_for)
from app.sandbox.sql import describe_tables, local_describe_tables

CASES = [{"id": "1", "ordinal": 1, "visibility": "open", "input": "2 3\n", "expected": "5", "weight": 1},
         {"id": "2", "ordinal": 2, "visibility": "hidden", "input": "10 20\n", "expected": "30", "weight": 2}]
PROGRAMS = {
    "accepted": "a, b = map(int, input().split())\nprint(a + b)\n",
    "wrong answer": "a, b = map(int, input().split())\nprint(a - b)\n",
    "time limit": "while True:\n    pass\n",
    "does not compile": "print(\n",
    "crashes": "raise SystemExit(3)\n",
}
SQL_CFG = {"schema": "CREATE TABLE t (name TEXT);", "seed": "", "engines": ["sqlite"], "ordered": True, "reference_sql": "SELECT name FROM t ORDER BY name"}
SQL_DATA = "INSERT INTO t VALUES ('b'), ('a');"


@pytest.fixture(scope="module")
def judge_url():
    """A real judge service on a local port (in a thread). Isolation itself is tested in the container; this tests the way to it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(judge_service.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.fixture()
def settings(monkeypatch):
    s = get_settings()
    remote._catalog.update(at=0.0, data=None)
    yield lambda **kw: [monkeypatch.setattr(s, k, v) for k, v in kw.items()]
    remote._catalog.update(at=0.0, data=None)


def _verdicts(res):
    return res["status"], [c["verdict"] for c in res.get("cases", [])], res.get("score")


def test_the_judge_gives_the_same_answers_as_running_locally(judge_url, settings):
    cfg = {"time_limit_ms": 300, "memory_mb": 128, "languages": ["python"]}
    settings(judge_url=judge_url)
    for name, source in PROGRAMS.items():
        via_judge = judge_code(cfg, CASES, "python", source, "submit")
        assert _verdicts(via_judge) == _verdicts(local_judge_code(cfg, CASES, "python", source, "submit")), name
    assert _verdicts(judge_code(cfg, CASES, "python", PROGRAMS["accepted"], "submit")) == ("done", ["AC", "AC"], 3.0)
    assert _verdicts(judge_code(cfg, CASES, "python", PROGRAMS["time limit"], "submit"))[1] == ["TLE", "TLE"]
    assert _verdicts(judge_code(cfg, CASES, "python", PROGRAMS["does not compile"], "submit"))[1] == ["CE", "CE"]
    run = judge_code(cfg, CASES, "python", PROGRAMS["accepted"], "run", custom_input="7 8\n")  # a Run with the candidate's own input
    assert run["custom"]["stdout"].strip() == "15" and len(run["cases"]) == 1

    # SQL, the expected answer of a reference query, the sample tables, and a reference solution
    sql_cases = [{"id": "1", "ordinal": 1, "visibility": "open", "input": SQL_DATA, "expected": "", "weight": 1}]
    sql_cases[0]["expected"] = __import__("json").dumps(sql_expected_for(SQL_CFG, SQL_DATA))
    assert sql_expected_for(SQL_CFG, SQL_DATA) == local_sql_expected_for(SQL_CFG, SQL_DATA) == {"columns": ["name"], "rows": [["a"], ["b"]]}
    assert _verdicts(judge_sql(SQL_CFG, sql_cases, "sqlite", "SELECT name FROM t ORDER BY name", "submit")) == _verdicts(
        local_judge_sql(SQL_CFG, sql_cases, "sqlite", "SELECT name FROM t ORDER BY name", "submit")) == ("done", ["AC"], 1.0)
    assert describe_tables(SQL_CFG["schema"], "", SQL_DATA) == local_describe_tables(SQL_CFG["schema"], "", SQL_DATA) != []
    ref = run_reference({"time_limit_ms": 2000}, "python", PROGRAMS["accepted"], ["1 2\n", "5 6\n"])
    assert [r["expected"] for r in ref] == [r["expected"] for r in local_run_reference({"time_limit_ms": 2000}, "python", PROGRAMS["accepted"], ["1 2\n", "5 6\n"])] == ["3", "11"]
    with pytest.raises(ValueError, match="does not compile"):  # an author's mistake arrives as the same ValueError
        run_reference({"time_limit_ms": 2000}, "python", PROGRAMS["does not compile"], ["1\n"])

    cat = remote.catalog(refresh=True)
    assert cat["isolated"] and cat["reachable"] and {l["key"] for l in cat["languages"]} == {"python", "c", "cpp", "java", "javascript"}
    assert remote.language_names().get("python") == "Python 3"


def test_in_production_without_a_judge_code_is_refused_and_the_admin_is_told(client, settings):
    settings(environment="production", judge_url="")
    assert remote.blocked()
    res = judge_code({}, CASES, "python", PROGRAMS["accepted"], "submit")
    assert res == {"status": "error", "error": remote.NOT_ISOLATED}            # never run in the API process
    assert judge_sql(SQL_CFG, [], "sqlite", "SELECT 1", "run") == {"status": "error", "error": remote.NOT_ISOLATED}
    for call in (lambda: run_reference({}, "python", "print(1)", ["\n"]), lambda: sql_expected_for(SQL_CFG, SQL_DATA)):
        with pytest.raises(ValueError, match="isolated judge is not configured"):
            call()
    assert describe_tables(SQL_CFG["schema"], "", SQL_DATA) == []
    admin = _login(client, "orgadmin@globx.co.in", PW["orgadmin@globx.co.in"])
    info = client.get("/api/v1/system/sandboxes", headers=admin).json()
    assert info["unsafe_in_production"] is True and info["isolated"] is False and info["environment"] == "production"
    settings(environment="dev")
    assert client.get("/api/v1/system/sandboxes", headers=admin).json()["unsafe_in_production"] is False  # development: no warning


def test_a_judge_that_is_down_gives_a_clear_message_and_never_a_crash(settings):
    settings(judge_url="http://127.0.0.1:1")  # nothing listens there
    res = judge_code({}, CASES, "python", PROGRAMS["accepted"], "submit")
    assert res == {"status": "error", "error": remote.JUDGE_DOWN}
    assert judge_sql(SQL_CFG, [], "sqlite", "SELECT 1", "run")["error"] == remote.JUDGE_DOWN
    with pytest.raises(ValueError, match="not available right now"):
        run_reference({}, "python", "print(1)", ["\n"])
    assert describe_tables(SQL_CFG["schema"], "", SQL_DATA) == []
    assert remote.catalog() == {"languages": [], "sql": [], "isolated": True, "reachable": False}  # no list yet: no languages, no crash
    assert remote.language_names() == {}


def test_the_judge_runs_only_the_functions_it_lists_and_refuses_huge_requests(judge_url):
    post = lambda body: httpx.post(judge_url + "/run", json=body, timeout=30)
    for fn in ("os.system", "__import__", "eval", "local_judge_code ", "judge_code; rm"):
        assert post({"fn": fn, "args": {"cmd": "echo hi"}}).status_code == 400
    assert post({"fn": "judge_code", "args": {"unexpected": 1}}).json()["ok"] is False        # wrong arguments: refused, not run
    assert httpx.post(judge_url + "/run", content=b"x" * 2_100_000, headers={"content-type": "application/json"}, timeout=30).status_code in (413, 422)
    assert httpx.get(judge_url + "/health").json() == {"status": "ok"}
    assert httpx.get(judge_url + "/docs").status_code == 404                                    # no interactive documentation on the judge
