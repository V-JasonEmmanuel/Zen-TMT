"""Pipeline orchestration. Each job kind maps to real, reportable stages.

Principles (kept separate on purpose):
  * the instruction decides WHAT is included      -> ContentContract
  * the source document decides WHICH facts exist -> relevance + verification
  * the LLM decides HOW content is worded         -> per-slide writer (optional)
  * the brand decides HOW it looks                -> Theme
  * renderers decide HOW files are produced       -> scene backends
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.branding.brand_profile import BrandStore
from backend.branding.theme import Theme, build_theme
from backend.intelligence.embeddings import embed_chunks_cached
from backend.intelligence.relevance import rank_chunks
from backend.intelligence.verification import Verifier
from backend.llm import LLMUnavailable, get_llm
from backend.llm.base import LLMProvider
from backend.pipeline.jobs import Reporter, StageFailed, runner
from backend.pipeline.outputs import OutputWriter, project_work_dir
from backend.planning.content_contract import parse_instruction
from backend.planning.content_planner import ContentPlanner, PlanningContext, PlanningError
from backend.planning.slide_planner import enforce_limits
from backend.planning.visual_planner import attach_visual
from backend.rendering.video.storyboard import render_video
from backend.schemas import ContentContract, ContentPlan, GenerationJob
from backend.services.documents import DocumentError, doc_dir, process_document
from backend.storage.database import get_db
from backend.utils.logging import get_logger

log = get_logger(__name__)

FULL_STAGES = [
    ("document", "Processing document"),
    ("structure", "Extracting structure"),
    ("index", "Indexing content"),
    ("contract", "Understanding instruction"),
    ("relevance", "Selecting relevant content"),
    ("plan", "Writing & verifying slides"),
    ("sources", "Saving content plan & source mapping"),
    ("design", "Applying brand design system"),
    ("pptx", "Generating presentation"),
    ("previews", "Rendering slide previews & PDF"),
    ("visuals", "Generating visuals"),
    ("video", "Generating video"),
]
SLIDE_STAGES = [("context", "Loading document context"), ("plan", "Rewriting & verifying slide"),
                ("sources", "Saving content plan & source mapping"), ("design", "Applying brand design system"),
                ("pptx", "Updating presentation"), ("previews", "Updating slide previews & PDF"),
                ("visuals", "Updating visuals")]
RENDER_STAGES = [("sources", "Saving content plan & source mapping"), ("design", "Applying brand design system"),
                 ("pptx", "Generating presentation"), ("previews", "Rendering slide previews & PDF"),
                 ("visuals", "Generating visuals"), ("video", "Generating video")]
VIDEO_STAGES = [("design", "Applying brand design system"), ("previews", "Rendering slide previews"),
                ("video", "Generating video")]


# ------------------------------------------------------------------ helpers
def _project(job: GenerationJob) -> dict:
    p = get_db().get_project(job.project_id)
    if not p:
        raise StageFailed("The project no longer exists.")
    return p


def _llm(project: dict, rep: Optional[Reporter]) -> Optional[LLMProvider]:
    if project["options"].get("writing_mode") == "extractive":
        return None
    try:
        llm = get_llm()
        if llm.is_available():
            return llm
        msg = f"Local model '{llm.model}' is not available (is Ollama running?). Content was selected extractively from the source instead."
    except LLMUnavailable as exc:
        msg = f"{exc} Content was selected extractively from the source instead."
    if rep:
        rep.note(msg)
    return None


def _theme(project: dict) -> Theme:
    store = BrandStore()
    brand_id = project.get("brand_id") or "zensar"
    try:
        return build_theme(store.load(brand_id), store)
    except FileNotFoundError as exc:
        raise StageFailed(f"Brand profile '{brand_id}' was not found.") from exc


def _index(project: dict, chunks, rep: Optional[Reporter] = None):
    vectors, embedder = embed_chunks_cached(doc_dir(project["document_id"]), [c.id for c in chunks], [c.text for c in chunks])
    if embedder.degraded and rep:
        rep.note("The embedding model is unavailable; relevance used keyword matching only.")
    return vectors, embedder


def _context(project: dict, contract: ContentContract, llm: Optional[LLMProvider], rep: Optional[Reporter] = None,
             doc_bundle=None, index=None) -> PlanningContext:
    db = get_db()
    doc, st, chunks = doc_bundle or process_document(db, project["document_id"])
    usable = list(chunks)
    vectors, embedder = index or _index(project, usable, rep)
    relevance = rank_chunks(contract, usable, vectors, embedder)
    rs = db.runtime_settings()
    verifier = Verifier({c.id: c for c in usable}, embedder, threshold=rs.verification_threshold)
    row = db.get_document(project["document_id"]) or {}
    return PlanningContext(project["document_id"], row.get("filename", ""), doc.title or st.title, usable, contract,
                           relevance, embedder, verifier, llm, drop_unverified=rs.drop_unverified)


def _render(rep: Reporter, project: dict, plan: ContentPlan, formats: list[str], *, video: bool, stages: set[str]) -> None:
    db = get_db()
    rep.start("design")
    theme = _theme(project)
    if theme.fallbacks:
        core = [f for f in theme.fallbacks if f.startswith(("colors.primary", "typography.heading.family"))]
        msg = (f"Brand '{theme.brand_name}' is not fully configured: neutral defaults were used for "
               f"{len(theme.fallbacks)} value(s). Configure it in the Brand Manager.") if core else \
              f"{len(theme.fallbacks)} brand value(s) used neutral defaults."
        rep.warn("design", msg)
    else:
        rep.done("design", f"{theme.brand_name} design tokens applied")
    writer = OutputWriter(db, project, plan, theme)
    writer.write_plan_files()  # before rendering, so the plan and mapping exist even if a renderer fails
    kinds = ["content_plan", "source_mapping"]

    if "pptx" in stages:
        rep.start("pptx")
        try:
            writer.write_pptx()
            kinds.append("pptx")
            rep.done("pptx", f"{len(plan.slides)} editable slides")
        except Exception as exc:
            log.error("PPTX generation failed", error=type(exc).__name__)
            rep.fail("pptx", "The PowerPoint file could not be generated.")

    images: dict[int, Path] = {}
    if "previews" in stages:
        rep.start("previews")
        try:
            images = writer.render_slide_images()
            kinds.append("slide_image")
            msg = f"{len(images)} slide previews"
            if "pdf" in formats:
                writer.write_pdf(images)
                kinds.append("pdf")
                msg += " + PDF"
            rep.done("previews", msg)
        except Exception as exc:
            log.error("Preview rendering failed", error=type(exc).__name__)
            rep.fail("previews", "Slide previews could not be rendered.")

    if "visuals" in stages:
        if "png" in formats:
            rep.start("visuals")
            try:
                n = len(writer.write_visuals())
                kinds.append("image")
                rep.done("visuals", f"{n} visuals (PNG + SVG)")
            except Exception as exc:
                log.error("Visual generation failed", error=type(exc).__name__)
                rep.fail("visuals", "Visuals could not be generated.")
        else:
            rep.skip("visuals")

    if "video" in stages:
        if video and "mp4" in formats and images:
            rep.start("video", "Synthesising narration and encoding (this can take a few minutes)")
            rs = db.runtime_settings()
            opts = project["options"]
            try:
                res = render_video(plan, images, writer.out / "video", project_work_dir(project),
                                   narration=opts.get("narration", rs.tts_enabled), tts_engine=rs.tts_engine,
                                   voice=opts.get("voice") or rs.tts_voice, speed=float(opts.get("speed") or rs.tts_rate),
                                   subtitles=opts.get("subtitles", rs.subtitles), ffmpeg_path=rs.ffmpeg_path,
                                   fade_color=theme.c("background"))
                if res.video:
                    kinds += ["video", "subtitles"]
                    msg = f"{res.duration:.0f}s video" + (" with narration" if res.narrated else " (no narration)")
                    if res.warnings:
                        rep.warn("video", msg + ". " + " ".join(res.warnings))
                    else:
                        rep.done("video", msg)
                else:
                    rep.fail("video", " ".join(res.warnings) or "The video could not be generated.")
            except Exception as exc:
                log.error("Video generation failed", error=type(exc).__name__)
                rep.fail("video", "The video could not be generated. The presentation and images are unaffected.")
        elif "mp4" in formats and not images:
            rep.fail("video", "The video needs slide previews, which failed to render.")
        else:
            rep.skip("video")

    writer.register(kinds)


# ------------------------------------------------------------------ job handlers
def run_full(rep: Reporter, job: GenerationJob) -> None:
    db = get_db()
    project = _project(job)
    formats = project["output_formats"] or ["pptx"]

    rep.start("document")
    try:
        bundle = process_document(db, project["document_id"])
    except DocumentError as exc:
        hint = " Tip: this looks like a scanned PDF - install an offline OCR engine (see README)." if exc.ocr_may_help else ""
        raise StageFailed(str(exc) + hint) from exc
    doc, st, chunks = bundle
    rep.done("document", f"{doc.page_count} page(s) · {doc.extraction_method} text")
    for w in doc.warnings:
        rep.note(w)

    rep.start("structure")
    types = ", ".join(t.value.replace("_", " ") for t in st.detected_types[:6]) or "no standard sections"
    rep.done("structure", f"{len(st.sections)} sections ({types}) · {st.table_count} tables · {st.figure_count} figures")

    rep.start("index", f"{len(chunks)} content chunks - computing embeddings")
    index = _index(project, chunks, rep)
    rep.done("index", f"{len(chunks)} content chunks indexed ({getattr(index[1], 'kind', '')})")

    rep.start("contract")
    llm = _llm(project, rep)
    defaults = {"brand_profile": project.get("brand_id") or "zensar", "output_formats": formats}
    if project["options"].get("slide_count"):
        defaults["slide_count"] = int(project["options"]["slide_count"])
    contract = parse_instruction(project["instruction"], llm, [s.title for s in st.sections], defaults=defaults)
    db.update_project(project["id"], contract=contract.model_dump())
    focus = ", ".join(contract.include) or "general overview"
    excl = f" · excluding {', '.join(contract.exclude)}" if contract.exclude else ""
    rep.done("contract", f"{contract.slide_count} slides for {contract.audience.replace('_', ' ')} · focus: {focus}{excl}")

    rep.start("relevance")
    ctx = _context(project, contract, llm, rep, bundle, index)
    kept = ctx.relevance.ranked()
    excluded = [s for s in ctx.relevance.scored if s.excluded]
    if not kept:
        raise StageFailed("No content in the document matched the instruction. Try a broader instruction.")
    rep.done("relevance", f"{len(kept)} relevant chunks selected · {len(excluded)} excluded")

    rep.start("plan", "Planning slides")
    planner = ContentPlanner(ctx)
    try:
        plan = planner.build(on_progress=lambda i, n: (rep.check(), rep.update("plan", f"Slide {i} of {n} written and verified")))
    except PlanningError as exc:
        raise StageFailed(str(exc)) from exc
    plan.project_id = project["id"]
    plan.generator = {"llm": llm.model if llm else None, "writing_mode": "llm" if llm else "extractive",
                      "embedding": getattr(ctx.embedder, "name", ""), "document_id": project["document_id"]}
    for w in plan.warnings:
        rep.note(w)
    review = sum(1 for s in plan.slides if s.needs_review)
    removed = sum(1 for s in plan.slides for w in s.warnings if w.startswith("Removed"))
    msg = f"{len(plan.slides)} slides · {review} need review" + (f" · unverifiable statements removed on {removed} slide(s)" if removed else "")
    if llm:
        llm.unload()  # free RAM/VRAM before rendering
    rep.done("plan", msg)

    rep.start("sources")
    db.save_plan(plan)
    rep.done("sources", f"Plan v{plan.version} saved")
    _finish_render(rep, project, plan, formats, video=True)


def _finish_render(rep: Reporter, project: dict, plan: ContentPlan, formats: list[str], video: bool,
                   stages: Optional[set[str]] = None) -> None:
    _render(rep, project, plan, formats, video=video, stages=stages or {"pptx", "previews", "visuals", "video"})


def run_slide(rep: Reporter, job: GenerationJob) -> None:
    db = get_db()
    project = _project(job)
    plan = db.latest_plan(project["id"])
    if not plan:
        raise StageFailed("Generate the presentation before regenerating individual slides.")
    n = int(job.params["slide_number"])
    slide = next((s for s in plan.slides if s.slide_number == n), None)
    if slide is None:
        raise StageFailed(f"Slide {n} does not exist.")
    rep.start("context")
    contract = ContentContract(**project["contract"]) if project.get("contract") else plan.contract
    llm = _llm(project, rep)
    ctx = _context(project, contract, llm, rep)
    rep.done("context", "Cached document index reused")
    rep.start("plan", f"Slide {n}")
    planner = ContentPlanner(ctx)
    layout = job.params.get("layout") or None
    new = planner.regenerate_slide(slide, layout=layout, guidance=job.params.get("guidance", ""))
    plan.slides = [new if s.slide_number == n else s for s in plan.slides]
    planner.finalize_references(plan.slides)
    if llm:
        llm.unload()
    rep.done("plan", f"Slide {n} regenerated as '{new.layout}'" + (" (needs review)" if new.needs_review else ""))
    rep.start("sources")
    db.save_plan(plan)
    rep.done("sources", f"Plan v{plan.version} saved")
    formats = project["output_formats"] or ["pptx"]
    _finish_render(rep, project, plan, formats, video=False, stages={"pptx", "previews", "visuals"})
    if "mp4" in formats:
        rep.note("The video was not updated. Use 'Regenerate video' to include this change.")


def run_render(rep: Reporter, job: GenerationJob) -> None:
    db = get_db()
    project = _project(job)
    plan = db.latest_plan(project["id"])
    if not plan:
        raise StageFailed("There is no content plan to render yet.")
    rep.start("sources")
    rep.done("sources", f"Using plan v{plan.version}")
    formats = project["output_formats"] or ["pptx"]
    _finish_render(rep, project, plan, formats, video=bool(job.params.get("video", False)))


def run_video(rep: Reporter, job: GenerationJob) -> None:
    db = get_db()
    project = _project(job)
    plan = db.latest_plan(project["id"])
    if not plan:
        raise StageFailed("There is no content plan to render yet.")
    formats = list(dict.fromkeys((project["output_formats"] or []) + ["mp4"]))
    _render(rep, project, plan, formats, video=True, stages={"previews", "video"})


def apply_slide_edit(plan: ContentPlan, slide_number: int, edited: dict, ctx: Optional[PlanningContext]) -> ContentPlan:
    """Human edits: keep source mapping, re-verify changed statements (flagged, never silently dropped)."""
    from backend.schemas import Slide

    old = next(s for s in plan.slides if s.slide_number == slide_number)
    data = old.model_dump()
    data.update({k: v for k, v in edited.items() if k in (
        "title", "subtitle", "layout", "key_points", "columns", "steps", "kpis", "quote", "narration", "accent_role", "visual",
        "table", "chart", "image", "custom_shapes", "background_role")})
    new = Slide.model_validate(data)
    new.edited = True

    def mark(items, olds):
        old_text = {getattr(o, "text", None) or f"{getattr(o, 'title', '')}|{getattr(o, 'description', '')}|{getattr(o, 'value', '')}"
                    for o in olds}
        for it in items:
            key = getattr(it, "text", None) or f"{getattr(it, 'title', '')}|{getattr(it, 'description', '')}|{getattr(it, 'value', '')}"
            if key not in old_text:
                it.status = "user_edited"
                if not it.sources:
                    it.sources = []

    mark(new.key_points, old.key_points)
    mark(new.steps, old.steps)
    mark(new.kpis, old.kpis)
    for c in new.columns:
        mark(c.points, [p for oc in old.columns for p in oc.points])
    if ctx is not None:
        new = ctx.verifier.verify_slide(new)
        new = attach_visual(new, ctx.chunk_map, None)
        new.sources = ContentPlanner(ctx).slide_sources(new)
    new = enforce_limits(new)
    plan.slides = [new if s.slide_number == slide_number else s for s in plan.slides]
    return plan


def context_for_project(project: dict) -> PlanningContext:
    contract = ContentContract(**project["contract"]) if project.get("contract") else ContentContract(raw_instruction=project["instruction"])
    return _context(project, contract, None)


def register_handlers() -> None:
    runner.register("full", run_full)
    runner.register("slide", run_slide)
    runner.register("render", run_render)
    runner.register("video", run_video)


STAGES_BY_KIND = {"full": FULL_STAGES, "slide": SLIDE_STAGES, "render": RENDER_STAGES, "video": VIDEO_STAGES}
