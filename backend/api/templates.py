"""Reference template analysis (without attaching it to a brand)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.branding.template_parser import analyze_pptx
from backend.storage.database import get_db

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
def list_templates(brand_id: Optional[str] = None):
    return [{k: t[k] for k in ("id", "brand_id", "name", "created_at")} |
            {"slide_size": (t.get("analysis") or {}).get("slide_size"), "layouts": len((t.get("analysis") or {}).get("layouts", []))}
            for t in get_db().list_templates(brand_id)]


@router.get("/{template_id}")
def get_template(template_id: str):
    t = get_db().get_template(template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    return t


@router.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() not in (".pptx",):
        raise HTTPException(400, "Upload a .pptx file")
    data = await file.read()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "template.pptx"
        p.write_bytes(data)
        try:
            return analyze_pptx(p)
        except Exception as exc:
            raise HTTPException(422, "The file could not be read as a PowerPoint template.") from exc
