"""Settings + system status (local AI, embeddings, TTS, FFmpeg, OCR, storage)."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.extraction.ocr import ocr_status
from backend.intelligence.embeddings import embedder_status, unload_embedder
from backend.llm.base import LLMUnavailable
from backend.llm.ollama import OllamaProvider, is_local_host
from backend.rendering.video.ffmpeg import find_ffmpeg
from backend.rendering.video.narration import tts_status
from backend.storage.database import RuntimeSettings, get_db
from backend.utils import network_guard
from backend.utils.config import get_settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_runtime_settings():
    s = get_settings()
    return {"settings": get_db().runtime_settings().model_dump(),
            "storage": {"database": str(s.db_file), "documents": str(s.documents_path), "projects": str(s.projects_path),
                        "outputs": str(s.outputs_path), "brands": str(s.brands_path), "models": str(s.models_path)},
            "privacy": {"strict_offline": network_guard.is_installed(), "telemetry": False,
                        "cloud_apis": "none - all processing is local"}}


@router.put("/settings")
def put_runtime_settings(body: dict[str, Any]):
    db = get_db()
    current = db.runtime_settings().model_dump()
    current.update({k: v for k, v in body.items() if k in current})
    try:
        rs = RuntimeSettings(**current)
    except Exception as exc:
        raise HTTPException(422, f"Invalid settings: {exc}") from exc
    if rs.ollama_host and not is_local_host(rs.ollama_host) and not rs.extra.get("allow_remote_ollama"):
        raise HTTPException(400, "Only an Ollama server on this machine (localhost) is allowed, so documents never leave it.")
    if not 0.5 <= rs.tts_rate <= 2.0:
        raise HTTPException(400, "Narration speed must be between 0.5 and 2.0")
    prev = db.runtime_settings()
    db.save_runtime_settings(rs)
    if prev.embedding_model != rs.embedding_model:
        unload_embedder()
    return get_runtime_settings()


@router.get("/llm/models")
def llm_models():
    rs = get_db().runtime_settings()
    try:
        prov = OllamaProvider(rs.ollama_host, rs.ollama_model)
        return {"running": True, "models": prov.list_models(), "selected": rs.ollama_model}
    except LLMUnavailable as exc:
        return {"running": False, "models": [], "selected": rs.ollama_model, "message": str(exc)}


@router.post("/llm/test")
def llm_test():
    rs = get_db().runtime_settings()
    try:
        prov = OllamaProvider(rs.ollama_host, rs.ollama_model, timeout_s=180)
        import time

        t = time.time()
        out = prov.generate('Reply with the JSON object {"ok": true}.', json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}}, max_tokens=20)
        return {"ok": '"ok"' in out, "seconds": round(time.time() - t, 1), "model": rs.ollama_model}
    except LLMUnavailable as exc:
        return {"ok": False, "message": str(exc)}


@lru_cache(maxsize=1)
def _gpu() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"available": False}
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True,
                           timeout=10, creationflags=0x08000000 if sys.platform == "win32" else 0)
        name, mem = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return {"available": True, "name": name, "memory": mem}
    except Exception:
        return {"available": False}


@router.get("/system/status")
def system_status():
    db = get_db()
    rs = db.runtime_settings()
    s = get_settings()
    try:
        models = OllamaProvider(rs.ollama_host, rs.ollama_model).list_models()
        running = True
    except LLMUnavailable:
        running, models = False, []
    names = {m["name"] for m in models}
    model_ok = bool(rs.ollama_model) and (rs.ollama_model in names or f"{rs.ollama_model}:latest" in names)
    ff = find_ffmpeg(rs.ffmpeg_path)
    tts = tts_status()
    du = shutil.disk_usage(s.data_path)
    return {
        "python": platform.python_version(),
        "ollama": {"running": running, "host": rs.ollama_host, "models": models, "selected": rs.ollama_model, "model_ready": model_ok},
        "embeddings": embedder_status(),
        "ffmpeg": {"available": bool(ff), "path": ff},
        "tts": tts,
        "ocr": ocr_status(),
        "gpu": _gpu(),
        "disk_free_gb": round(du.free / 1e9, 1),
        "offline_guard": network_guard.is_installed(),
        "onboarding_complete": rs.onboarding_complete,
        "ready": running and model_ok and bool(ff),
    }
