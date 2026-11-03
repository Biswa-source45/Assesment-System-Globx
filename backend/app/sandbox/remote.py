"""The way to the isolated judge.

Candidate code must never run inside the API process in production: it would run with the API's rights, next to the database password,
the OpenAI key and every candidate's answers and pictures. With JUDGE_URL set, every call that runs candidate (or author) code goes to the
judge container instead (judge_service.py), which has no network, no secrets and runs each program as its own throw-away user.
With JUDGE_URL empty the same functions run locally, which is only for development; with ENVIRONMENT=production and no judge they refuse.

JUDGE_URL is `unix:///run/judge/judge.sock` (production: a socket in a shared volume, the judge has no network at all)
or `http://host:port` (tests and local development)."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import httpx

from app.core.config import get_settings

JUDGE_DOWN = "The code judge is not available right now. Try again in a moment."
NOT_ISOLATED = "Code cannot be run here: the isolated judge is not configured (JUDGE_URL is empty in production)."
CATALOG_TTL = 60  # seconds the judge's list of languages is reused, so a candidate's page does not ask the judge for every question

_http = {"url": None, "client": None}
_lock = threading.Lock()
_catalog: Dict[str, Any] = {"at": 0.0, "data": None}


class Unavailable(Exception):
    """The judge could not be reached or failed."""


def enabled() -> bool:
    return bool(get_settings().judge_url)


def blocked() -> bool:
    """Production without a judge: candidate code is refused rather than run in the API process."""
    return get_settings().environment.lower() == "production" and not enabled()


def why_not() -> str:
    return NOT_ISOLATED if blocked() else JUDGE_DOWN


def _client() -> httpx.Client:
    url = get_settings().judge_url
    with _lock:
        if _http["url"] != url:
            if url.startswith("unix://"):
                _http["client"] = httpx.Client(transport=httpx.HTTPTransport(uds=url[len("unix://"):]), base_url="http://judge", timeout=120)
            else:
                _http["client"] = httpx.Client(base_url=url, timeout=120)
            _http["url"] = url
        return _http["client"]


def call(fn: str, **args: Any) -> Any:
    """Run one of the judge's functions there. A ValueError raised there is raised here; anything else, or an unreachable judge, is Unavailable."""
    try:
        r = _client().post("/run", json={"fn": fn, "args": args})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise Unavailable(JUDGE_DOWN) from e
    if r.status_code != 200 or not isinstance(data, dict) or "ok" not in data:
        raise Unavailable(JUDGE_DOWN)
    if data["ok"]:
        return data["result"]
    if data.get("kind") == "ValueError":
        raise ValueError(data.get("error", ""))
    raise Unavailable(JUDGE_DOWN)


def catalog(refresh: bool = False) -> Dict[str, Any]:
    """{languages: [...], sql: [...], isolated: bool, reachable: bool} as the judge (or, in development, this machine) reports it."""
    if not enabled():
        from app.sandbox.languages import REGISTRY, refresh_all
        from app.sandbox.sql import SQL_ENGINES
        return {"languages": refresh_all() if refresh else [s.info() for s in REGISTRY.values()],
                "sql": [e.info() for e in SQL_ENGINES.values()], "isolated": False, "reachable": True}
    now = time.time()
    if refresh or _catalog["data"] is None or now - _catalog["at"] > CATALOG_TTL:
        try:
            r = _client().get("/catalog", params={"refresh": "true" if refresh else "false"})
            r.raise_for_status()
            _catalog.update(data=r.json(), at=now)
        except (httpx.HTTPError, ValueError):
            _catalog["at"] = now - CATALOG_TTL + 10  # try again in ten seconds; meanwhile the last known list (or none) is used
            if _catalog["data"] is None:
                return {"languages": [], "sql": [], "isolated": True, "reachable": False}
    return {**_catalog["data"], "isolated": True, "reachable": True}


def language_keys() -> List[str]:
    return [x["key"] for x in catalog()["languages"]]


def language_names() -> Dict[str, str]:
    """The languages candidates can use now: key -> name."""
    return {x["key"]: x["name"] for x in catalog()["languages"] if x["available"]}


def engine_names() -> Dict[str, str]:
    return {x["key"]: x["name"] for x in catalog()["sql"] if x["available"]}


def selftest() -> Dict:
    if not enabled():
        from app.sandbox.selftest import run_selftest
        return run_selftest()
    try:
        r = _client().post("/selftest")
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise Unavailable(JUDGE_DOWN) from e
