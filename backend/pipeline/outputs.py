"""Output writer: renders every artefact from the canonical ContentPlan into the project output folder.

outputs/<project>/
  presentation/presentation.pptx, presentation.pdf
  slides/slide_XX.png            (previews; also used for PDF + video)
  images/visual_XX.png|svg       (standalone visuals)
  video/presentation.mp4|vtt|srt
  source/source_mapping.json
  content/content_plan.json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from backend.branding.theme import Theme
from backend.rendering.images.raster import RasterRenderer
from backend.rendering.images.svg import SVGRenderer
from backend.rendering.layouts import RenderContext, build_slide_scene, build_visual_scene
from backend.rendering.ppt.generator import PPTXGenerator
from backend.rendering.scene import Scene
from backend.schemas import ContentPlan, OutputFile, utcnow
from backend.services.documents import doc_dir
from backend.storage.database import Database
from backend.utils.config import get_settings
from backend.utils.files import safe_join
from backend.utils.logging import get_logger

log = get_logger(__name__)
RENDER_VERSION = "4"
KIND_DIRS = {"pptx": "presentation", "pdf": "presentation", "slide_image": "slides", "image": "images",
             "video": "video", "subtitles": "video", "source_mapping": "source", "content_plan": "content"}


def project_output_dir(project: dict) -> Path:
    return safe_join(get_settings().outputs_path, project["output_dir"])


def project_work_dir(project: dict) -> Path:
    return safe_join(get_settings().projects_path, project["id"])


def theme_signature(theme: Theme) -> str:
    return hashlib.sha1(json.dumps({k: str(v) for k, v in vars(theme).items()}, sort_keys=True).encode()).hexdigest()[:12]


def build_source_mapping(plan: ContentPlan, document: dict) -> dict[str, Any]:
    slides, claims = {}, {}
    for s in plan.slides:
        slides[f"slide_{s.slide_number}"] = [
            {"page": r.page, "page_end": r.page_end, "section": r.section, "source": r.document_name,
             "chunk_id": r.chunk_id, "content_type": r.content_type, "table": r.table, "figure": r.figure}
            for r in s.sources
        ]
        items = []
        ref_by_chunk = {r.chunk_id: r for r in s.sources}

        def add(kind: str, text: str, obj):
            first = next((ref_by_chunk[c] for c in obj.sources if c in ref_by_chunk), None)
            items.append({"kind": kind, "claim": text, "source_document": first.document_name if first else None,
                          "page": getattr(obj, "evidence_page", None) or (first.page if first else None),
                          "section": first.section if first else None, "chunk_ids": obj.sources,
                          "confidence": obj.confidence, "status": obj.status})

        for p in s.key_points:
            if p.status != "structural":
                add("point", p.text, p)
        for c in s.columns:
            for p in c.points:
                add("point", f"{c.heading}: {p.text}", p)
        for st in s.steps:
            add("step", f"{st.title}: {st.description}", st)
        for k in s.kpis:
            add("kpi", f"{k.value} — {k.label}", k)
        if s.quote:
            add("quote", s.quote.text, s.quote)
        if s.chart:
            items.append({"kind": "chart", "claim": f"Chart of {', '.join(x.name for x in s.chart.series)} (copied from source table)",
                          "chunk_ids": [s.chart.source], "confidence": 1.0, "status": "verified",
                          "page": ref_by_chunk[s.chart.source].page if s.chart.source in ref_by_chunk else None,
                          "section": ref_by_chunk[s.chart.source].section if s.chart.source in ref_by_chunk else None,
                          "source_document": document.get("filename")})
        claims[f"slide_{s.slide_number}"] = items
    return {"document": {"id": document.get("id"), "name": document.get("filename")}, "generated_at": utcnow(),
            "plan_version": plan.version, "slides": slides, "claims": claims}


class OutputWriter:
    def __init__(self, db: Database, project: dict, plan: ContentPlan, theme: Theme):
        self.db, self.project, self.plan, self.theme = db, project, plan, theme
        self.out = project_output_dir(project)
        self.work = project_work_dir(project)
        self.out.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.ctx = RenderContext(plan, doc_dir(project["document_id"]) if project.get("document_id") else None)
        self._scenes: Optional[list[Scene]] = None

    # -------------------------------------------------------------- scenes
    def scenes(self) -> list[Scene]:
        if self._scenes is None:
            self._scenes = [build_slide_scene(s, self.theme, self.ctx) for s in self.plan.slides]
        return self._scenes

    # -------------------------------------------------------------- plan + mapping
    def write_plan_files(self) -> None:
        doc = self.db.get_document(self.project["document_id"]) or {}
        (self.out / "content").mkdir(exist_ok=True)
        (self.out / "source").mkdir(exist_ok=True)
        (self.out / "content" / "content_plan.json").write_text(self.plan.model_dump_json(indent=2), encoding="utf-8")
        mapping = build_source_mapping(self.plan, doc)
        (self.out / "source" / "source_mapping.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        self.db.save_source_mapping(self.project["id"], {s.slide_number: mapping["slides"][f"slide_{s.slide_number}"]
                                                         for s in self.plan.slides})

    # -------------------------------------------------------------- PPTX
    def write_pptx(self) -> Path:
        return PPTXGenerator(self.theme).build(self.scenes(), self.out / "presentation" / "presentation.pptx", self.plan.title)

    # -------------------------------------------------------------- slide images (cached per slide)
    def render_slide_images(self) -> dict[int, Path]:
        cache_file = self.work / "render_cache.json"
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        sig = theme_signature(self.theme)
        rr = RasterRenderer(1920)
        out: dict[int, Path] = {}
        rendered = 0
        slides_dir = self.out / "slides"
        wanted = set()
        for slide, scene in zip(self.plan.slides, self.scenes()):
            key = hashlib.sha1((RENDER_VERSION + sig + slide.model_dump_json() + str(len(self.plan.slides))).encode()).hexdigest()
            path = slides_dir / f"slide_{slide.slide_number:02d}.png"
            wanted.add(path.name)
            if cache.get(str(slide.slide_number)) != key or not path.exists():
                rr.save(scene, path)
                cache[str(slide.slide_number)] = key
                rendered += 1
            out[slide.slide_number] = path
        for stale in slides_dir.glob("slide_*.png"):
            if stale.name not in wanted:
                stale.unlink()
        cache = {k: v for k, v in cache.items() if int(k) <= len(self.plan.slides)}
        cache_file.write_text(json.dumps(cache))
        log.info("Slide previews rendered", rendered=rendered, reused=len(out) - rendered)
        return out

    def write_pdf(self, images: dict[int, Path]) -> Path:
        import pymupdf

        pdf = pymupdf.open()
        w_pt, h_pt = self.theme.slide_w * 72, self.theme.slide_h * 72
        for n in sorted(images):
            page = pdf.new_page(width=w_pt, height=h_pt)
            page.insert_image(page.rect, filename=str(images[n]))
        pdf.set_metadata({"title": self.plan.title, "creator": "Content Studio (offline)"})
        path = self.out / "presentation" / "presentation.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(path), deflate=True)
        pdf.close()
        return path

    # -------------------------------------------------------------- standalone visuals
    def write_visuals(self) -> list[Path]:
        img_dir = self.out / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        for old in img_dir.glob("visual_*"):
            old.unlink()
        rr, svg = RasterRenderer(1920), SVGRenderer()
        written = []
        for slide in self.plan.slides:
            try:
                scene = build_visual_scene(slide, self.theme, self.ctx)
            except Exception as exc:
                log.warning("Visual skipped", slide=slide.slide_number, error=type(exc).__name__)
                continue
            if scene is None:
                continue
            written.append(rr.save(scene, img_dir / f"visual_{slide.slide_number:02d}.png"))
            svg.save(scene, img_dir / f"visual_{slide.slide_number:02d}.svg")
        log.info("Visuals generated", count=len(written))
        return written

    # -------------------------------------------------------------- registry
    def register(self, kinds: list[str]) -> list[OutputFile]:
        found: list[OutputFile] = []
        patterns = {
            "pptx": ["presentation/presentation.pptx"], "pdf": ["presentation/presentation.pdf"],
            "slide_image": ["slides/slide_*.png"], "image": ["images/visual_*.png", "images/visual_*.svg"],
            "video": ["video/presentation.mp4"], "subtitles": ["video/presentation.vtt", "video/presentation.srt"],
            "source_mapping": ["source/source_mapping.json"], "content_plan": ["content/content_plan.json"],
        }
        for kind in kinds:
            for pat in patterns[kind]:
                for p in sorted(self.out.glob(pat)):
                    rel = p.relative_to(self.out).as_posix()
                    oid = hashlib.sha1(f"{self.project['id']}:{rel}".encode()).hexdigest()[:16]
                    found.append(OutputFile(id=oid, project_id=self.project["id"], kind=kind, path=rel, size=p.stat().st_size))
        self.db.replace_outputs(self.project["id"], kinds, found)
        return found
