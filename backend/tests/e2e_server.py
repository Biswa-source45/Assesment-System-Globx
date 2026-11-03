"""Server for the Playwright suite (frontend/e2e): seeds a throw-away copy of the database (<name>_test)
and serves the API on port 8001. The generated demo passwords are written to the JSON file given as argument."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402

# the browser tests write camera pictures too: into a throw-away folder, never into the real user-assets
e2e_storage = Path(tempfile.gettempdir()) / "oap-e2e-storage"
shutil.rmtree(e2e_storage, ignore_errors=True)
os.environ["STORAGE_DIR"] = str(e2e_storage)

if not os.environ.get("RUN_AI"):  # the browser tests must not spend money or depend on the network; RUN_AI=1 keeps the real provider
    os.environ["LLM_PROVIDER"] = "none"

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
