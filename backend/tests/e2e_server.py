"""Server for the Playwright suite (frontend/e2e): seeds a throw-away copy of the database (<name>_test)
and serves the API on port 8001. The generated demo passwords are written to the JSON file given as argument."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402

base, _, name = get_settings().database_url.rpartition("/")
os.environ["DATABASE_URL"] = f"{base}/{name}" if name.endswith("_test") else f"{base}/{name}_test"
get_settings.cache_clear()

from app.seed import seed  # noqa: E402

res = seed(reset=True)
creds = {e: p for e, p, _ in res["staff"]}
creds["candidate"] = res["candidate_password"]
Path(sys.argv[1]).write_text(json.dumps(creds), encoding="utf-8")

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", port=8001, log_level="warning")
