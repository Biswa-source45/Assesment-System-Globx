"""A throw-away copy of the exam server on THIS computer for load tests: its own database (oap_load), its own files, the same way the Docker image starts it
(one uvicorn process, access log on). Run it with the backend's Python:

  ..\\backend\\.venv\\Scripts\\python.exe local_server.py start      (prints the admin login it made; also saved in results/local_creds.json)
  ..\\backend\\.venv\\Scripts\\python.exe local_server.py stop

It reads the database settings from the repository's .env but only ever touches the database named oap_load."""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"
STATE = HERE / "results" / "local_server.json"
PORT = int(os.environ.get("LT_PORT", "8001"))


def base_url() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return re.sub(r"/[^/?]+(\?.*)?$", "", line.split("=", 1)[1].strip().strip("\"'"))
    raise SystemExit("DATABASE_URL is not in .env")


def ensure_database(url_base: str) -> str:
    import psycopg
    admin = re.sub(r"^postgresql\+psycopg", "postgresql", url_base) + "/postgres"
    with psycopg.connect(admin, autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = 'oap_load'").fetchone():
            c.execute("CREATE DATABASE oap_load")
    return url_base + "/oap_load"


def start(reseed: bool = True) -> None:
    old = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    stop(quiet=True)
    db_url = ensure_database(base_url())
    storage = Path(tempfile.gettempdir()) / "oap-load-storage"
    env = {**os.environ, "DATABASE_URL": db_url, "STORAGE_DIR": str(storage), "LLM_PROVIDER": "none", "DEMO_MODE": "false", "SECRET_KEY": "load-test-only-not-a-secret",
           "SMTP_HOST": "", "PYTHONUNBUFFERED": "1"}
    sys.path.insert(0, str(BACKEND))
    os.environ.update(env)
    from app.core.config import get_settings
    get_settings.cache_clear()
    if reseed or not old.get("creds"):
        from app.seed import seed
        res = seed(reset=True)
        creds = {"email": "orgadmin@globx.co.in", "password": dict((e, p) for e, p, _ in res["staff"])["orgadmin@globx.co.in"]}
    else:  # the same database and logins, only the server process starts again
        creds = old["creds"]
    STATE.parent.mkdir(exist_ok=True)
    log = open(HERE / "results" / "local_server.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--proxy-headers"],
                            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    STATE.write_text(json.dumps({"pid": proc.pid, "port": PORT, "storage": str(storage), "creds": creds}), encoding="utf-8")
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2)
            print(f"local server up on http://127.0.0.1:{PORT} (pid {proc.pid}); admin {creds['email']}; the password is in results/local_server.json")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("the server did not start; see results/local_server.log")


def stop(quiet: bool = False) -> None:
    if not STATE.exists():
        return
    pid = json.loads(STATE.read_text(encoding="utf-8")).get("pid")
    try:
        import psutil
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            child.kill()
        p.kill()
        if not quiet:
            print(f"stopped pid {pid}")
    except Exception:
        pass
    STATE.unlink(missing_ok=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"start": start, "restart": lambda: start(reseed=False), "stop": stop}[cmd]()
