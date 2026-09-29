"""Local Media Library: every image the studio can use, stored once (SHA-256 dedup) with metadata.

Collections:  zensar (approved brand assets) · user (uploads) · downloaded (web, with license) ·
              generated (visuals rendered from documents) · document (figures extracted from sources)
Externally sourced files ALWAYS carry license metadata and are never presented as Zensar-owned.
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
from pathlib import Path
from typing import Any, Literal, Optional

from PIL import Image
from pydantic import BaseModel, Field

from backend.schemas import utcnow
from backend.storage.database import Database, get_db
from backend.utils.config import get_settings
from backend.utils.files import new_id, safe_join, sanitize_filename

Collection = Literal["zensar", "user", "downloaded", "generated", "document"]
Kind = Literal["image", "logo", "icon", "illustration", "reference", "visual", "video", "audio"]
CATEGORIES = ("people", "technology", "business", "healthcare", "finance", "cloud", "ai", "data", "research",
              "architecture", "abstract", "other")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
KIND_DIR = {"image": "images", "logo": "logos", "icon": "icons", "illustration": "illustrations",
            "reference": "references", "visual": "images", "video": "videos", "audio": "audio"}


def media_kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else "image"


def _probe(path: Path) -> dict:
    """Duration / size of a video or audio file via FFmpeg (no ffprobe needed)."""
    import re
    import subprocess

    from backend.rendering.video.ffmpeg import NO_WINDOW, find_ffmpeg

    ff = find_ffmpeg()
    if not ff:
        return {}
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    out: dict = {}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr)
    if m:
        out["duration"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    if m:
        out["width"], out["height"] = int(m.group(1)), int(m.group(2))
    out["has_audio"] = " Audio:" in r.stderr
    return out


class License(BaseModel):
    source: str = ""  # e.g. "User-provided asset", "Openverse", "Wikimedia Commons", "Zensar (official)"
    original_url: str = ""
    creator: str = ""
    license: str = ""  # e.g. "CC BY 2.0", "CC0", "Unsplash License", "Zensar internal"
    license_url: str = ""
    download_date: str = ""
    usage_notes: str = ""


class MediaAsset(BaseModel):
    id: str
    sha256: str
    collection: Collection
    kind: Kind = "image"
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    filename: str
    path: str  # relative to the media root
    thumb: str = ""
    width: int = 0
    height: int = 0
    bytes: int = 0
    mime: str = ""
    colors: list[str] = Field(default_factory=list)  # dominant colours
    brightness: float = 0.0
    saturation: float = 0.0
    description: str = ""
    license: License = Field(default_factory=License)
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow)

    @property
    def source_label(self) -> str:
        L = self.license
        if self.collection == "user":
            return "User-provided asset"
        if self.collection == "zensar":
            return "Zensar brand asset"
        if self.collection == "generated":
            return "Generated locally from document data"
        if self.collection == "document":
            return "Figure from the source document"
        return " · ".join(x for x in (L.source, L.creator, L.license) if x)


def media_root() -> Path:
    return get_settings().media_path


def _raster_bytes(data: bytes, filename: str) -> bytes:
    """SVGs are rasterised for analysis/thumbnails (the original SVG is kept)."""
    if filename.lower().endswith(".svg"):
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="svg")
        page = doc[0]
        zoom = 1200 / max(page.rect.width, 1)
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).tobytes("png")
    return data


def analyze_colors(img: Image.Image) -> tuple[list[str], float, float]:
    small = img.convert("RGB").resize((96, max(1, int(96 * img.height / max(img.width, 1)))))
    q = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    cols = ["#%02X%02X%02X" % tuple(pal[i * 3:i * 3 + 3]) for _, i in sorted(q.getcolors(), reverse=True)]
    hsv = small.convert("HSV")
    import numpy as np

    arr = np.asarray(hsv, dtype=np.float32) / 255.0
    return cols, round(float(arr[..., 2].mean()), 3), round(float(arr[..., 1].mean()), 3)


class MediaLibrary:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.root = media_root()

    # -------------------------------------------------------------- storage
    def add(self, data: bytes, filename: str, collection: Collection, *, kind: Kind = "image", category: str = "other",
            tags: Optional[list[str]] = None, license: Optional[License] = None, description: str = "",
            meta: Optional[dict] = None) -> MediaAsset:
        sha = hashlib.sha256(data).hexdigest()
        existing = self.by_hash(sha)
        if existing:
            return existing  # never store (or download) the same asset twice
        name = sanitize_filename(filename, default="image")
        ext = Path(name).suffix.lower()
        if ext not in IMAGE_EXT:
            raise ValueError(f"Unsupported image type '{ext}'")
        raster = _raster_bytes(data, name)
        try:
            img = Image.open(io.BytesIO(raster))
            img.load()
        except Exception as exc:
            raise ValueError("The file is not a readable image") from exc
        aid = new_id("med_")
        sub = KIND_DIR.get(kind, "images")
        rel = f"{sub}/{aid}{ext}"
        dest = safe_join(self.root, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        thumb_rel = f"thumbs/{aid}.webp"
        t = img.convert("RGBA")
        t.thumbnail((480, 480))
        t.save(safe_join(self.root, thumb_rel), "WEBP", quality=82)
        cols, bright, sat = analyze_colors(img)
        lic = license or License(source={"user": "User-provided asset", "generated": "Generated locally",
                                         "document": "Source document", "zensar": "Zensar (official)"}.get(collection, ""))
        asset = MediaAsset(id=aid, sha256=sha, collection=collection, kind=kind, category=category if category in CATEGORIES else "other",
                           tags=[t.lower() for t in (tags or [])][:20], filename=name, path=rel, thumb=thumb_rel,
                           width=img.width, height=img.height, bytes=len(data), mime=mimetypes.guess_type(name)[0] or "",
                           colors=cols, brightness=bright, saturation=sat, description=description[:500],
                           license=lic, meta=meta or {})
        if collection == "downloaded":
            (self.root / "licenses").mkdir(parents=True, exist_ok=True)
            (self.root / "licenses" / f"{aid}.json").write_text(asset.license.model_dump_json(indent=2), encoding="utf-8")
        with self.db.connect() as con:
            con.execute("INSERT INTO media_assets(id,sha256,collection,kind,category,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                        (aid, sha, collection, kind, asset.category, asset.model_dump_json(), asset.created_at))
        return asset

    def add_path(self, src: Path, filename: str, collection: Collection, *, category: str = "other",
                 tags: Optional[list[str]] = None, license: Optional[License] = None, description: str = "",
                 meta: Optional[dict] = None, move: bool = True) -> MediaAsset:
        """Register a file already on disk (streamed uploads, rendered clips). Videos/audio are never
        loaded into memory; images go through the normal analysis path."""
        import shutil

        kind = media_kind_for(filename)
        if kind == "image":
            return self.add(Path(src).read_bytes(), filename, collection, category=category, tags=tags, license=license,
                            description=description, meta=meta)
        h = hashlib.sha256()
        with open(src, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        sha = h.hexdigest()
        existing = self.by_hash(sha)
        if existing:
            if move:
                Path(src).unlink(missing_ok=True)
            return existing
        name = sanitize_filename(filename, default=kind)
        ext = Path(name).suffix.lower()
        aid = new_id("med_")
        rel = f"{KIND_DIR[kind]}/{aid}{ext}"
        dest = safe_join(self.root, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        (shutil.move if move else shutil.copyfile)(str(src), str(dest))
        info = _probe(dest)
        thumb_rel = ""
        if kind == "video":
            import subprocess

            from backend.rendering.video.ffmpeg import NO_WINDOW, find_ffmpeg

            thumb_rel = f"thumbs/{aid}.jpg"
            at = min(1.0, (info.get("duration") or 2) / 3)
            subprocess.run([find_ffmpeg() or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(dest),
                            "-frames:v", "1", "-vf", "scale=480:-2", str(safe_join(self.root, thumb_rel))],
                           capture_output=True, creationflags=NO_WINDOW)
            if not safe_join(self.root, thumb_rel).exists():
                thumb_rel = ""
        lic = license or License(source={"user": "User-provided asset", "generated": "Generated locally",
                                         "document": "Source document", "zensar": "Zensar (official)"}.get(collection, ""))
        asset = MediaAsset(id=aid, sha256=sha, collection=collection, kind=kind, category=category if category in CATEGORIES else "other",
                           tags=[t.lower() for t in (tags or [])][:20], filename=name, path=rel, thumb=thumb_rel,
                           width=info.get("width", 0), height=info.get("height", 0), bytes=dest.stat().st_size,
                           mime=mimetypes.guess_type(name)[0] or "", description=description[:500], license=lic,
                           meta={**(meta or {}), "duration": info.get("duration", 0), "has_audio": info.get("has_audio", False)})
        with self.db.connect() as con:
            con.execute("INSERT INTO media_assets(id,sha256,collection,kind,category,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                        (aid, sha, collection, kind, asset.category, asset.model_dump_json(), asset.created_at))
        return asset

    def by_hash(self, sha: str) -> Optional[MediaAsset]:
        with self.db.connect() as con:
            r = con.execute("SELECT payload FROM media_assets WHERE sha256=?", (sha,)).fetchone()
        return MediaAsset.model_validate_json(r["payload"]) if r else None

    def get(self, asset_id: str) -> Optional[MediaAsset]:
        with self.db.connect() as con:
            r = con.execute("SELECT payload FROM media_assets WHERE id=?", (asset_id,)).fetchone()
        return MediaAsset.model_validate_json(r["payload"]) if r else None

    def update(self, asset: MediaAsset) -> MediaAsset:
        with self.db.connect() as con:
            con.execute("UPDATE media_assets SET payload=?, category=? WHERE id=?", (asset.model_dump_json(), asset.category, asset.id))
        return asset

    def list(self, collection: Optional[str] = None, category: Optional[str] = None, q: str = "",
             limit: int = 500, kind: Optional[str] = None) -> list[MediaAsset]:
        sql, args = "SELECT payload FROM media_assets WHERE 1=1", []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if collection:
            sql += " AND collection=?"
            args.append(collection)
        if category and category != "all":
            sql += " AND category=?"
            args.append(category)
        with self.db.connect() as con:
            rows = con.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
        items = [MediaAsset.model_validate_json(r["payload"]) for r in rows]
        if q:
            ql = q.lower()
            items = [a for a in items if ql in (a.filename + " " + a.description + " " + " ".join(a.tags) + " " +
                                                a.license.creator + " " + a.license.source).lower()]
        return items

    def delete(self, asset_id: str) -> bool:
        a = self.get(asset_id)
        if not a:
            return False
        for rel in (a.path, a.thumb):
            if rel:
                safe_join(self.root, rel).unlink(missing_ok=True)
        (self.root / "licenses" / f"{asset_id}.json").unlink(missing_ok=True)
        with self.db.connect() as con:
            con.execute("DELETE FROM media_assets WHERE id=?", (asset_id,))
        return True

    def path(self, asset: MediaAsset) -> Path:
        return safe_join(self.root, asset.path)

    def raster_path(self, asset: MediaAsset) -> Path:
        """A raster file usable by Pillow/python-pptx (SVGs are rasterised once and cached)."""
        p = self.path(asset)
        if p.suffix.lower() != ".svg":
            return p
        out = self.root / "processed" / f"{asset.id}_raster.png"
        if not out.exists():
            out.write_bytes(_raster_bytes(p.read_bytes(), p.name))
        return out

    # -------------------------------------------------------------- sync helpers
    def sync_brand_assets(self, brand_id: str = "zensar") -> int:
        """Register the approved brand logos/references in the 'zensar' collection."""
        from backend.branding.brand_profile import BrandStore

        store = BrandStore()
        if not store.exists(brand_id):
            return 0
        b = store.load(brand_id)
        d = store.dir(brand_id)
        n = 0
        for variant, rel in (("logo (light backgrounds)", b.logo.file), ("logo (dark backgrounds)", b.logo.file_on_dark)):
            if rel and (d / "assets" / rel).exists():
                svg = (d / "assets" / rel).with_suffix(".svg")
                src = svg if svg.exists() else d / "assets" / rel
                src_note = b.logo.sources.get(variant, "") or (b.provenance.get("logo.file").note if b.provenance.get("logo.file") else "")
                self.add(src.read_bytes(), src.name, "zensar", kind="logo", category="other", tags=["logo", "zensar"],
                         description=f"Zensar {variant}", license=License(source="Zensar (official)", license="Zensar brand asset",
                                                                         usage_notes=src_note or "Official Zensar asset"))
                n += 1
        for name, meta in b.reference_meta.items():
            f = d / "references" / name
            if f.exists() and f.suffix.lower() in IMAGE_EXT:
                self.add(f.read_bytes(), name, "zensar", kind="reference", category="other", tags=["reference", meta.design_role],
                         description=meta.description, license=License(source="Zensar (official)", original_url=meta.source_url,
                                                                        license="Zensar brand reference", usage_notes="Reference only"))
                n += 1
        return n


def asset_payload(a: MediaAsset) -> dict:
    d = json.loads(a.model_dump_json())
    d["source_label"] = a.source_label
    d["url"] = f"/api/media/{a.id}/file"
    d["thumb_url"] = f"/api/media/{a.id}/thumb" if a.thumb else None
    d["duration"] = a.meta.get("duration")
    return d
