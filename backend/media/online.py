"""Controlled, OPTIONAL online image discovery.

ExternalAssetManager is the only component allowed to reach the internet. It:
  * is disabled unless Settings -> "Allow Internet Image Search" is ON (default OFF);
  * contacts only approved provider hosts (network guard allowlist, per call);
  * sends only generic vocabulary queries (see query.py) - never document text;
  * keeps only licences that permit commercial use with modification;
  * ranks candidates (relevance, quality, composition, aspect, brand colour fit, resolution, licence);
  * downloads the chosen image once into the local Media Library with full licence metadata.
Everything else in the application stays offline. Local providers work without internet.
"""
from __future__ import annotations

import io
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image

from backend.media.library import License, MediaAsset, MediaLibrary
from backend.media.query import is_safe_query
from backend.schemas import utcnow
from backend.storage.database import get_db
from backend.utils import network_guard
from backend.utils.logging import get_logger

log = get_logger(__name__)
UA = {"User-Agent": "ZensarContentStudio/1.0 (internal enterprise tool; offline-first)"}
MAX_BYTES = 12 * 1024 * 1024
BAD_TERMS = re.compile(r"\b(meme|cartoon|clipart|clip art|logo|screenshot|sketch|drawing|map|diagram|text|poster|flag|coat of arms|nsfw)\b", re.I)


class OnlineDisabled(Exception):
    pass


class OnlineUnavailable(Exception):
    pass


@dataclass
class Candidate:
    provider: str
    id: str
    title: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    creator: str = ""
    license: str = ""
    license_url: str = ""
    landing_url: str = ""
    tags: list[str] = field(default_factory=list)
    local_asset_id: Optional[str] = None  # for local providers
    scores: dict[str, float] = field(default_factory=dict)
    score: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def license_confidence(lic: str) -> float:
    l = (lic or "").lower().replace("_", "-")
    if any(x in l for x in ("nc", "nd", "noncommercial", "noderiv")):
        return 0.0  # no commercial use / no modification (crops and treatments are modifications)
    if l in ("cc0", "pdm", "public domain", "pd") or "cc0" in l or "public domain" in l:
        return 1.0
    if l.startswith("by-sa") or "by-sa" in l or "cc by-sa" in l:
        return 0.8
    if l.startswith("by") or "cc by" in l or l == "by":
        return 0.95
    if l in ("unsplash license", "pexels license"):
        return 0.9
    return 0.0


# ------------------------------------------------------------------ providers
class ImageSearchProvider(ABC):
    name = ""
    online = True
    hosts: tuple[str, ...] = ()

    def available(self) -> tuple[bool, str]:
        return True, ""

    @abstractmethod
    def search(self, query: str, limit: int, client: Optional[httpx.Client]) -> list[Candidate]: ...


class LocalLibraryProvider(ImageSearchProvider):
    name, online = "local", False
    collections = ("user", "downloaded")

    def search(self, query, limit, client=None):
        lib = MediaLibrary()
        words = set(query.lower().split())
        out = []
        for col in self.collections:
            for a in lib.list(collection=col):
                if a.kind not in ("image", "illustration"):
                    continue
                text = f"{a.description} {' '.join(a.tags)} {a.category} {a.filename}".lower()
                hits = sum(1 for w in words if w in text)
                out.append(Candidate(self.name if col != "zensar" else "brand_assets", a.id, a.description or a.filename,
                                     f"/api/media/{a.id}/file", f"/api/media/{a.id}/thumb", a.width, a.height,
                                     a.license.creator, a.license.license or "user", a.license.license_url,
                                     tags=a.tags, local_asset_id=a.id, scores={"_hits": hits}))
        return out[: limit * 3]


class ZensarAssetProvider(LocalLibraryProvider):
    name = "brand_assets"
    collections = ("zensar",)


class OpenverseProvider(ImageSearchProvider):
    name, hosts = "openverse", ("api.openverse.org",)

    def search(self, query, limit, client):
        r = client.get("https://api.openverse.org/v1/images/", params={
            "q": query, "page_size": min(limit, 20), "license_type": "commercial,modification", "mature": "false"})
        r.raise_for_status()
        out = []
        for it in r.json().get("results", []):
            lic = f"CC {it.get('license', '').upper()} {it.get('license_version', '')}".strip()
            if it.get("license") in ("cc0", "pdm"):
                lic = it["license"].upper()
            out.append(Candidate(self.name, it["id"], it.get("title") or "", it.get("url", ""), it.get("thumbnail") or it.get("url", ""),
                                 it.get("width") or 0, it.get("height") or 0, it.get("creator") or "", lic, it.get("license_url") or "",
                                 it.get("foreign_landing_url") or "", [t.get("name", "") for t in (it.get("tags") or [])][:15]))
        return out


class WikimediaProvider(ImageSearchProvider):
    name, hosts = "wikimedia", ("commons.wikimedia.org", "upload.wikimedia.org")

    def search(self, query, limit, client):
        r = client.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "generator": "search", "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
            "gsrlimit": min(limit, 20), "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 400,
            "format": "json"})
        r.raise_for_status()
        out = []
        for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
            ii = (page.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata", {})
            val = lambda k: re.sub(r"<[^>]+>", "", (meta.get(k) or {}).get("value", "")).strip()  # noqa: E731
            if not ii.get("mime", "").startswith("image/"):
                continue
            out.append(Candidate(self.name, str(page.get("pageid")), page.get("title", "").replace("File:", ""), ii.get("url", ""),
                                 ii.get("thumburl") or ii.get("url", ""), ii.get("width", 0), ii.get("height", 0),
                                 val("Artist")[:120], val("LicenseShortName"), val("LicenseUrl"), ii.get("descriptionurl", ""),
                                 [c for c in val("Categories").split("|")][:10]))
        return out


class KeyedProvider(ImageSearchProvider):
    key_setting = ""

    def _key(self) -> str:
        return (get_db().runtime_settings().extra.get(self.key_setting) or "").strip()

    def available(self):
        return (True, "") if self._key() else (False, "Optional provider · API key not configured · using free/local alternatives")


class UnsplashProvider(KeyedProvider):
    name, hosts, key_setting = "unsplash", ("api.unsplash.com", "images.unsplash.com"), "unsplash_access_key"

    def search(self, query, limit, client):
        r = client.get("https://api.unsplash.com/search/photos", params={"query": query, "per_page": min(limit, 20),
                                                                         "orientation": "landscape"},
                       headers={"Authorization": f"Client-ID {self._key()}"})
        r.raise_for_status()
        return [Candidate(self.name, it["id"], it.get("alt_description") or "", it["urls"]["regular"], it["urls"]["small"],
                          it.get("width", 0), it.get("height", 0), (it.get("user") or {}).get("name", ""), "Unsplash License",
                          "https://unsplash.com/license", (it.get("links") or {}).get("html", ""),
                          [t.get("title", "") for t in it.get("tags", [])]) for it in r.json().get("results", [])]


class PexelsProvider(KeyedProvider):
    name, hosts, key_setting = "pexels", ("api.pexels.com", "images.pexels.com"), "pexels_api_key"

    def search(self, query, limit, client):
        r = client.get("https://api.pexels.com/v1/search", params={"query": query, "per_page": min(limit, 20),
                                                                  "orientation": "landscape"},
                       headers={"Authorization": self._key()})
        r.raise_for_status()
        return [Candidate(self.name, str(it["id"]), it.get("alt") or "", it["src"]["large2x"], it["src"]["medium"],
                          it.get("width", 0), it.get("height", 0), it.get("photographer", ""), "Pexels License",
                          "https://www.pexels.com/license/", it.get("url", "")) for it in r.json().get("photos", [])]


PROVIDERS: dict[str, ImageSearchProvider] = {p.name: p for p in (
    LocalLibraryProvider(), ZensarAssetProvider(), OpenverseProvider(), WikimediaProvider(), UnsplashProvider(), PexelsProvider())}


# ------------------------------------------------------------------ ranking
def _thumb_metrics(img: Image.Image, palette: list[str]) -> dict[str, float]:
    small = img.convert("RGB").resize((64, 36))
    arr = np.asarray(small, dtype=np.float32) / 255
    gray = arr.mean(axis=2)
    gx, gy = np.abs(np.diff(gray, axis=1)).mean(), np.abs(np.diff(gray, axis=0)).mean()
    busy = float(gx + gy)
    composition = float(math.exp(-((busy - 0.09) / 0.07) ** 2))  # moderate detail, not flat, not chaotic
    brightness = float(gray.mean())
    readable = 1.0 - min(1.0, abs(brightness - 0.55) * 1.6)
    pal = np.array([[int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)] for h in palette] or [[0.5, 0.5, 0.5]])
    px = arr.reshape(-1, 3)
    dist = np.sqrt(((px[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
    mx, mn = px.max(axis=1), px.min(axis=1)
    sat = float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0).mean())
    colour = float(max(0.0, 1.0 - dist.mean() / 0.8))
    brand_fit = 0.6 * colour + 0.4 * (1.0 - max(0.0, sat - 0.45) / 0.55)  # garish images don't sit with the palette
    return {"composition": round(composition, 3), "readability": round(readable, 3), "brand_fit": round(brand_fit, 3)}


def rank(cands: list[Candidate], query: str, palette: list[str], target_ar: float = 16 / 9, min_width: int = 1200,
         client: Optional[httpx.Client] = None) -> list[Candidate]:
    words = set(query.lower().split())
    kept = []
    for i, c in enumerate(cands):
        text = f"{c.title} {' '.join(c.tags)}".lower()
        if BAD_TERMS.search(text):
            continue
        lic = 1.0 if c.local_asset_id else license_confidence(c.license)
        if lic == 0.0 or not c.width or not c.height:
            continue
        hits = c.scores.pop("_hits", None)
        rel = (hits if hits is not None else sum(1 for w in words if w in text)) / max(1, len(words))
        relevance = min(1.0, 0.55 * rel + 0.45 * (1 - i / max(1, len(cands))))  # provider order carries relevance too
        resolution = min(1.0, c.width / 1920)
        if c.width < min_width * 0.6:
            continue
        ar = c.width / c.height
        aspect = math.exp(-abs(math.log(ar / target_ar)) * 1.5)
        m = {"composition": 0.6, "readability": 0.6, "brand_fit": 0.6}
        try:
            if c.local_asset_id:
                lib = MediaLibrary()
                a = lib.get(c.local_asset_id)
                with Image.open(lib.root / a.thumb) as im:
                    m = _thumb_metrics(im, palette)
            elif client is not None and c.thumb_url.startswith("https://"):
                r = client.get(c.thumb_url)
                if r.status_code == 200 and len(r.content) < 3_000_000:
                    m = _thumb_metrics(Image.open(io.BytesIO(r.content)), palette)
        except Exception:
            pass
        c.scores = {"relevance": round(relevance, 3), "composition": m["composition"], "aspect_ratio": round(aspect, 3),
                    "brand_fit": m["brand_fit"], "readability": m["readability"], "resolution": round(resolution, 3),
                    "license_confidence": lic}
        c.score = round(0.28 * relevance + 0.14 * m["composition"] + 0.1 * aspect + 0.18 * m["brand_fit"] +
                        0.08 * m["readability"] + 0.1 * resolution + 0.12 * lic, 4)
        kept.append(c)
    return sorted(kept, key=lambda c: -c.score)


# ------------------------------------------------------------------ manager
class ExternalAssetManager:
    SUITABLE = 0.55  # below this, a deterministic diagram/composition is preferred over a weak photo

    def __init__(self):
        self.rs = get_db().runtime_settings()

    @property
    def online_allowed(self) -> bool:
        return bool(self.rs.allow_internet_image_search)

    def provider_status(self) -> list[dict]:
        out = []
        for p in PROVIDERS.values():
            ok, msg = p.available()
            if p.online and not self.online_allowed:
                ok, msg = False, "Internet image search is turned off (Settings)"
            out.append({"name": p.name, "online": p.online, "available": ok, "message": msg})
        return out

    def reachable(self) -> bool:
        if not self.online_allowed:
            return False
        try:
            with network_guard.allow_hosts(["api.openverse.org"]):
                httpx.head("https://api.openverse.org/v1/", timeout=4, headers=UA)
            return True
        except Exception:
            return False

    def search(self, query: str, providers: Optional[list[str]] = None, limit: int = 12, palette: Optional[list[str]] = None,
               min_width: int = 1200) -> dict:
        providers = providers or ["brand_assets", "local", "openverse", "wikimedia", "unsplash", "pexels"]
        results, notes = [], []
        online = [PROVIDERS[p] for p in providers if p in PROVIDERS and PROVIDERS[p].online]
        local = [PROVIDERS[p] for p in providers if p in PROVIDERS and not PROVIDERS[p].online]
        for p in local:
            results += p.search(query, limit)
        if online:
            if not self.online_allowed:
                notes.append("Internet image search is turned off. Using the local media library.")
                online = []
            elif not is_safe_query(query):
                notes.append("The search query contained non-generic words and was not sent to the internet.")
                online = []
        client = None
        if online:
            hosts = sorted({h for p in online for h in p.hosts})
            try:
                with network_guard.allow_hosts(hosts):
                    with httpx.Client(timeout=15, headers=UA, follow_redirects=True) as client:
                        for p in online:
                            ok, msg = p.available()
                            if not ok:
                                notes.append(f"{p.name}: {msg}")
                                continue
                            try:
                                results += p.search(query, limit, client)
                            except httpx.HTTPError:
                                notes.append(f"{p.name}: unavailable right now")
                        # thumbnails for ranking come from the providers' own CDN hosts
                        thumb_hosts = sorted({urlparse(c.thumb_url).hostname for c in results
                                              if c.thumb_url.startswith("https://")} - {None})
                        with network_guard.allow_hosts(thumb_hosts):
                            ranked = rank(results, query, palette or [], min_width=min_width, client=client)
                        return {"query": query, "candidates": [c.as_dict() for c in ranked[:limit]], "notes": notes,
                                "suitable": bool(ranked and ranked[0].score >= self.SUITABLE)}
            except (httpx.ConnectError, httpx.ConnectTimeout, OSError):
                notes.append("Internet image search unavailable. Using local media library.")
        ranked = rank(results, query, palette or [], min_width=min_width)
        return {"query": query, "candidates": [c.as_dict() for c in ranked[:limit]], "notes": notes,
                "suitable": bool(ranked and ranked[0].score >= self.SUITABLE)}

    def download(self, cand: dict, category: str = "other") -> MediaAsset:
        """Fetch a chosen web candidate ONCE into the media library with its licence metadata."""
        if cand.get("local_asset_id"):
            a = MediaLibrary().get(cand["local_asset_id"])
            if not a:
                raise ValueError("Asset not found")
            return a
        if not self.online_allowed:
            raise OnlineDisabled("Internet image search is turned off in Settings.")
        if license_confidence(cand.get("license", "")) == 0.0:
            raise ValueError("This image's licence does not permit commercial use with modification.")
        url = cand["image_url"]
        host = urlparse(url).hostname or ""
        if not url.startswith("https://") or not host:
            raise ValueError("Only HTTPS image URLs from the provider are accepted")
        try:
            with network_guard.allow_hosts([host]):
                with httpx.Client(timeout=30, headers=UA, follow_redirects=False) as client:
                    r = client.get(url)
        except (httpx.HTTPError, OSError) as exc:
            raise OnlineUnavailable("The image could not be downloaded (offline?).") from exc
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/") or len(r.content) > MAX_BYTES:
            raise ValueError("The provider did not return a usable image")
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(r.headers["content-type"].split(";")[0], ".jpg")
        lic = License(source={"openverse": "Openverse", "wikimedia": "Wikimedia Commons", "unsplash": "Unsplash",
                              "pexels": "Pexels"}.get(cand["provider"], cand["provider"]),
                      original_url=cand.get("landing_url") or url, creator=cand.get("creator", ""), license=cand.get("license", ""),
                      license_url=cand.get("license_url", ""), download_date=utcnow(),
                      usage_notes="Externally sourced - not a Zensar-owned asset. Keep the attribution with any use.")
        return MediaLibrary().add(r.content, f"{cand['provider']}_{cand['id']}{ext}", "downloaded", category=category,
                                  tags=[t for t in cand.get("tags", []) if t][:15], license=lic,
                                  description=(cand.get("title") or "")[:300], meta={"query": cand.get("query", ""), "scores": cand.get("scores", {})})
