"""Zensar Content Studio - local backend.

    python backend/main.py

Serves the REST API on http://127.0.0.1:8000 and, if built, the frontend (frontend/dist).
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from backend.api import branddocs, brands, documents, generation, media, papers, projects, settings, templates, video  # noqa: E402
from backend.branding.brand_profile import BrandStore, ensure_default_brands  # noqa: E402
from backend.pipeline.jobs import runner  # noqa: E402
from backend.pipeline.orchestrator import register_handlers  # noqa: E402
from backend.storage.database import get_db  # noqa: E402
from backend.utils import network_guard  # noqa: E402
from backend.utils.config import APP_ROOT, get_settings  # noqa: E402
from backend.utils.logging import get_logger  # noqa: E402

log = get_logger("backend.main")
FRONTEND_DIST = APP_ROOT / "frontend" / "dist"


def startup() -> None:
    s = get_settings()
    s.ensure_dirs()
    if os.environ.get("STRICT_OFFLINE", "true").lower() != "false":
        network_guard.install()
    db = get_db()
    n = db.mark_interrupted_jobs()
    if n:
        log.warning("Marked interrupted jobs as failed", jobs=n)
    ensure_default_brands()
    for b in BrandStore().list():
        db.upsert_brand(b.id, b.name, b.status)
    try:
        from backend.media.library import MediaLibrary

        MediaLibrary().sync_brand_assets("zensar")
    except Exception as exc:  # never block startup on media sync
        log.warning("Brand asset sync skipped", error=type(exc).__name__)
    register_handlers()
    runner.start()
    try:
        from backend.papers.service import recover_stale

        recover_stale()  # research-paper conversions interrupted by a restart
    except Exception as exc:
        log.warning("Paper recovery skipped", error=type(exc).__name__)
    try:
        from backend.branddocs.service import recover_stale as recover_branddocs

        recover_branddocs()  # brand-document conversions interrupted by a restart
    except Exception as exc:
        log.warning("Brand document recovery skipped", error=type(exc).__name__)
    log.info("Content Studio backend ready", data=str(s.data_path), offline_guard=network_guard.is_installed())


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    yield


app = FastAPI(title="Zensar Content Studio", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])
for r in (documents, projects, generation, brands, templates, settings, media, video, papers, branddocs):
    app.include_router(r.router)
app.include_router(video.script_router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("Unhandled API error", path=request.url.path, error=type(exc).__name__)
    return JSONResponse({"detail": "An unexpected error occurred. Please try again."}, status_code=500)


# ---- built frontend (single-port mode used by start.bat); SPA fallback for client routes
if FRONTEND_DIST.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(app, host=s.backend_host, port=s.backend_port, log_level="warning")
