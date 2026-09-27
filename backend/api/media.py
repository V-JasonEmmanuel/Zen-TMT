"""Media Library API (local assets, optional online discovery, image treatment previews)."""
from __future__ import annotations

import io
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel

from backend.media.library import CATEGORIES, IMAGE_EXT, MediaLibrary, asset_payload
from backend.media.online import ExternalAssetManager, OnlineDisabled, OnlineUnavailable
from backend.schemas import ImageTreatment
from backend.utils.files import safe_join

router = APIRouter(prefix="/api/media", tags=["media"])
MAX_UPLOAD = 25 * 1024 * 1024


class MetaPatch(BaseModel):
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    description: Optional[str] = None


class DownloadRequest(BaseModel):
    candidate: dict[str, Any]
    category: str = "other"


class TreatmentPreview(BaseModel):
    treatment: ImageTreatment = ImageTreatment()
    brand_id: str = "zensar"
    max_side: int = 900


def _lib() -> MediaLibrary:
    return MediaLibrary()


@router.get("")
def list_media(collection: Optional[str] = None, category: Optional[str] = None, q: str = ""):
    return [asset_payload(a) for a in _lib().list(collection, category, q)]


@router.get("/categories")
def categories():
    return {"categories": list(CATEGORIES), "collections": ["zensar", "user", "downloaded", "generated", "document"]}


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...), category: str = Form("other"), tags: str = Form(""),
                 description: str = Form("")):
    lib, out = _lib(), []
    for f in files:
        name = f.filename or "image"
        if not any(name.lower().endswith(e) for e in IMAGE_EXT):
            raise HTTPException(400, f"'{name}' is not a supported image (PNG, JPG, JPEG, SVG, WebP)")
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(400, f"'{name}' is larger than 25 MB")
        try:
            out.append(asset_payload(lib.add(data, name, "user", category=category,
                                             tags=[t.strip() for t in tags.split(",") if t.strip()], description=description)))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return out


@router.get("/providers")
def providers():
    m = ExternalAssetManager()
    return {"online_allowed": m.online_allowed, "providers": m.provider_status()}


@router.get("/online")
def online_status():
    m = ExternalAssetManager()
    ok = m.reachable()
    return {"allowed": m.online_allowed, "reachable": ok,
            "message": "Online image search available" if ok else
            ("Internet image search unavailable. Using local media library." if m.online_allowed else "Internet image search is off")}


@router.get("/search")
def search(q: str, providers: Optional[str] = None, brand_id: str = "zensar", limit: int = 12):
    from backend.branding.theme import load_theme

    try:
        theme = load_theme(brand_id)
        palette = list(dict.fromkeys(theme.palette + theme.tints + [theme.c("background")]))
    except Exception:
        palette = []
    return ExternalAssetManager().search(q, providers.split(",") if providers else None, min(limit, 30), palette)


@router.post("/download")
def download(body: DownloadRequest):
    try:
        return asset_payload(ExternalAssetManager().download(body.candidate, body.category))
    except OnlineDisabled as exc:
        raise HTTPException(403, str(exc)) from exc
    except OnlineUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{asset_id}")
def get_asset(asset_id: str):
    a = _lib().get(asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    return asset_payload(a)


@router.patch("/{asset_id}")
def patch_asset(asset_id: str, body: MetaPatch):
    lib = _lib()
    a = lib.get(asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    if body.category is not None:
        a.category = body.category if body.category in CATEGORIES else "other"
    if body.tags is not None:
        a.tags = [t.strip().lower() for t in body.tags if t.strip()][:20]
    if body.description is not None:
        a.description = body.description[:500]
    return asset_payload(lib.update(a))


@router.delete("/{asset_id}")
def delete_asset(asset_id: str):
    if not _lib().delete(asset_id):
        raise HTTPException(404, "Asset not found")
    return {"deleted": asset_id}


@router.get("/{asset_id}/file")
def asset_file(asset_id: str, download: bool = False):
    lib = _lib()
    a = lib.get(asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    p = lib.path(a)
    return FileResponse(p, filename=a.filename if download else None, content_disposition_type="attachment" if download else "inline")


@router.get("/{asset_id}/thumb")
def asset_thumb(asset_id: str):
    lib = _lib()
    a = lib.get(asset_id)
    if not a or not a.thumb:
        raise HTTPException(404, "Asset not found")
    return FileResponse(safe_join(lib.root, a.thumb), headers={"Cache-Control": "max-age=86400"})


@router.post("/{asset_id}/preview")
def treatment_preview(asset_id: str, body: TreatmentPreview):
    """Live preview for the image editor (same treatment code as the final render)."""
    from backend.branding.theme import load_theme
    from backend.media.treatment import apply_treatment

    lib = _lib()
    a = lib.get(asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    with Image.open(lib.raster_path(a)) as im:
        im.thumbnail((body.max_side, body.max_side))
        out = apply_treatment(im, body.treatment, load_theme(body.brand_id))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")

