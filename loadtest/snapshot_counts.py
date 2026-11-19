"""Read-only: how many rows every table holds, how big the database is, and how many files and bytes the storage folder holds. Run it before a load test and
after the cleanup and compare. It runs INSIDE the exam server's container, fed through standard input (nothing is added to the image):

  docker compose exec -T api python - < snapshot_counts.py          (on the office PC: Get-Content -Raw snapshot_counts.py | docker compose exec -T api python -)
Locally: ..\\backend\\.venv\\Scripts\\python.exe snapshot_counts.py   (with DATABASE_URL and STORAGE_DIR set for the copy you mean)."""
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402

with SessionLocal() as db:
    tables = [r[0] for r in db.execute(text("select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"))]
    counts = {t: int(db.scalar(text(f'select count(*) from "{t}"'))) for t in tables}
    size_mb = round(db.scalar(text("select pg_database_size(current_database())")) / 2 ** 20, 1)

root = get_settings().storage_dir
files, nbytes = 0, 0
for base, _, names in os.walk(root):
    for n in names:
        files += 1
        try:
            nbytes += os.path.getsize(os.path.join(base, n))
        except OSError:
            pass
print(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "tables": counts, "database_mb": size_mb, "storage_files": files, "storage_mb": round(nbytes / 2 ** 20, 1)}))
