"""The isolated judge: the only program that runs candidate code in production.

It runs in its own container (see docker-compose.yml): no network, no secrets, a read-only filesystem, every run as a separate
throw-away user. The API reaches it through a Unix socket and may call exactly the functions listed in FUNCS, nothing else.
It holds no database, no .env, no camera pictures; it receives the code and the test cases of one question per call."""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.sandbox import judge, sql
from app.sandbox.languages import REGISTRY, refresh_all
from app.sandbox.selftest import run_selftest

log = logging.getLogger("oap.judge")
MAX_BODY = 2_000_000
FUNCS = {"judge_code": judge.local_judge_code, "judge_sql": judge.local_judge_sql, "run_reference": judge.local_run_reference,
         "sql_expected_for": judge.local_sql_expected_for, "describe_tables": sql.local_describe_tables}
slots = threading.BoundedSemaphore(max(1, get_settings().judge_workers))  # only this many programs run at once; the rest wait

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class RunIn(BaseModel):
    fn: str
    args: Dict[str, Any] = {}


@app.post("/run")
def run(body: RunIn, request: Request):
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "Request too large")
    fn = FUNCS.get(body.fn)
    if fn is None:
        raise HTTPException(400, "Unknown function")
    with slots:
        try:
            return {"ok": True, "result": fn(**body.args)}
        except ValueError as e:  # an expected failure (a solution that does not compile): the API shows the message
            return {"ok": False, "kind": "ValueError", "error": str(e)}
        except Exception:
            log.exception("judge call %s failed", body.fn)
            return {"ok": False, "kind": "Error", "error": "internal"}


@app.get("/catalog")
def catalog(refresh: bool = False):
    return {"languages": refresh_all() if refresh else [s.info() for s in REGISTRY.values()], "sql": [e.info() for e in sql.SQL_ENGINES.values()]}


@app.post("/selftest")
def selftest():
    with slots:
        return run_selftest()


@app.get("/health")
def health():
    return {"status": "ok"}
