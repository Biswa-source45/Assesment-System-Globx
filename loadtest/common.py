"""Shared bits of the load-test scripts: where the target is, who the run is, pictures like the browser sends, and a small API client.
Nothing secret is ever written to disk: the admin password is read from the environment (LT_ADMIN_PASSWORD) when a script starts."""
import io
import json
import os
import random
import string
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

_RESOLVE = os.environ.get("LT_RESOLVE", "")   # "name=address": reach the site by its real name (the certificate matches) through a chosen address, no hosts file edit
if _RESOLVE and "=" in _RESOLVE:
    import socket
    _name, _addr = _RESOLVE.split("=", 1)
    _real = socket.getaddrinfo

    def _getaddrinfo(host, *a, **kw):
        return _real(_addr if host == _name else host, *a, **kw)

    socket.getaddrinfo = _getaddrinfo
RESULTS = HERE / "results"


def host() -> str:
    return os.environ.get("LT_HOST", "http://localhost:8001").rstrip("/")


def new_run_id() -> str:
    return "LT-" + time.strftime("%Y%m%d-%H%M")


def run_dir(run_id: str) -> Path:
    d = RESULTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_run(run_id: str = "") -> dict:
    """What setup_data.py saved about the run: ids of the exam, the questions, the candidates file."""
    run_id = run_id or os.environ.get("LT_RUN", "")
    if not run_id:  # the newest run
        runs = sorted(p for p in RESULTS.glob("LT-*") if (p / "run.json").exists())
        if not runs:
            raise SystemExit("No run found: run setup_data.py first")
        run_id = runs[-1].name
    return json.loads((RESULTS / run_id / "run.json").read_text(encoding="utf-8"))


def random_password() -> str:
    pool = string.ascii_letters + string.digits
    return "Lt" + "".join(random.choice(pool) for _ in range(14)) + "9a"


class ApiError(RuntimeError):
    pass


class Api:
    """A plain client for the set-up scripts (the load itself is sent by Locust)."""

    def __init__(self, base: str = "", verify: bool = True):
        self.base = (base or host()) + "/api/v1"
        self.s = requests.Session()
        self.s.verify = verify
        self.token = None

    def login(self, email: str, password: str) -> "Api":
        r = self.s.post(self.base + "/auth/login", json={"email": email, "password": password}, timeout=60)
        if r.status_code != 200:
            raise ApiError(f"login failed ({r.status_code}): {r.text[:200]}")
        self.token = r.json()["access_token"]
        self.s.headers["Authorization"] = "Bearer " + self.token
        return self

    def call(self, method: str, path: str, **kw):
        r = self.s.request(method, self.base + path, timeout=kw.pop("timeout", 120), **kw)
        if r.status_code >= 400:
            raise ApiError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, json=body if body is not None else {}, **kw)

    def put(self, path, body=None, **kw):
        return self.call("PUT", path, json=body if body is not None else {}, **kw)


# ---------------------------------------------------------------- pictures like the browser sends
def make_jpeg(width: int, height: int, quality: int, seed: int, noise: float = 38.0) -> bytes:
    """A picture with texture, so its size is like a real camera frame (about 35 KB at 480 x 360, 150 KB at 1280 x 720)."""
    rnd = random.Random(seed)
    base = Image.effect_noise((width, height), noise).convert("RGB")
    d = ImageDraw.Draw(base)
    for _ in range(12):
        x, y = rnd.randrange(width), rnd.randrange(height)
        d.ellipse([x, y, x + rnd.randrange(20, 120), y + rnd.randrange(20, 120)], fill=(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    buf = io.BytesIO()
    base.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def picture_pool():
    """Pictures prepared once per process: a few camera frames and screen frames."""
    cam = [make_jpeg(480, 360, 70, s, 18) for s in range(4)]
    screen = [make_jpeg(1280, 720, 60, 100 + s, 11) for s in range(2)]
    return cam, screen
