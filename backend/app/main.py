"""FastAPI application: API under /api/v1, the built React app under /."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import ROOT_DIR, get_settings
from app.db import migrate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("oap")
settings = get_settings()
DIST = ROOT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import models  # noqa: F401  (register tables)
    migrate()
    os.makedirs(settings.storage_dir, exist_ok=True)
    os.makedirs(settings.sandbox_dir, exist_ok=True)
    from app.services import jobs
    if os.environ.get("OAP_NO_BACKGROUND") != "1":
        jobs.start_background()
    from app.sandbox.languages import REGISTRY
    for s in REGISTRY.values():
        i = s.info()
        log.info("sandbox %-11s %s %s", s.key, "OK " if i["available"] else "MISSING", i["version"] or ", ".join(i["missing"]))
    log.info("%s ready on %s (demo_mode=%s)", settings.app_name, settings.public_base_url, settings.demo_mode)
    yield
    jobs.stop_background()


app = FastAPI(title="GLOBX Assess API", version="2.1.0", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), display-capture=(self)")
    return resp


from app.api import auth, candidate, departments, exam_pack, library, live, results, staff, tests  # noqa: E402

for r in (auth.router, departments.router, library.router, tests.router, exam_pack.router, results.router, live.router, candidate.router, staff.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal server error. The administrator can see details in logs/server.log."}, 500)


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, 404)
    f = (DIST / path).resolve()
    if path and f.is_file() and str(f).startswith(str(DIST.resolve())):
        return FileResponse(f)
    idx = DIST / "index.html"
    if idx.exists():
        return FileResponse(idx, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Frontend not built. API docs at /api/docs"}, 404)
