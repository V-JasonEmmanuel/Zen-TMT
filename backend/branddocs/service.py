"""Brand documents: templates learned from reference PDFs, and conversions into them.

    data/branddocs/templates/<tpl_id>/   reference.pdf, template.json, pages/page_N.png (preview)
    data/branddocs/docs/<doc_id>/         source.*, meta.json, work/ (figures), images/, document.pdf, pages/

A conversion: read the document -> plan images (cover + some sections) -> write prompts from the content
-> generate the images locally -> compose the PDF in the template -> check that every word arrived.
Everything runs on this computer.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.branddocs.model import DocTemplate
from backend.utils.config import get_settings
from backend.utils.files import new_id
from backend.utils.logging import get_logger

log = get_logger(__name__)
INPUTS = {".pdf": "pdf", ".docx": "docx", ".md": "markdown", ".markdown": "markdown", ".txt": "text", ".text": "text"}
_lock = threading.Lock()
_running: dict[str, threading.Thread] = {}
_gen_lock = threading.Lock()  # one image-generation job at a time (memory)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root() -> Path:
    d = get_settings().data_path / "branddocs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_id(i: str, prefix: str) -> str:
    if not i.startswith(prefix) or not re.fullmatch(r"[a-z]+_[0-9a-f]{6,32}", i):
        raise KeyError(i)
    return i


# ------------------------------------------------------------------ templates
def tdir(tid: str) -> Path:
    return root() / "templates" / _safe_id(tid, "btp_")


def load_template(tid: str) -> DocTemplate:
    f = tdir(tid) / "template.json"
    if not f.exists():
        raise KeyError(tid)
    return DocTemplate.model_validate_json(f.read_text(encoding="utf-8"))


def save_template(t: DocTemplate) -> None:
    (tdir(t.id) / "template.json").write_text(t.model_dump_json(indent=1), encoding="utf-8")


def template_summary(t: DocTemplate) -> dict:
    from backend.branddocs import fonts

    d = tdir(t.id)
    fam = Counter(f.rsplit("-", 1)[0] for f in t.fonts_seen).most_common(1)
    family = fam[0][0] if fam else ""
    installed = fonts.installed_reference(family, t.brand_id) if family else None
    return {"id": t.id, "name": t.name, "brand_id": t.brand_id, "source_file": t.source_file, "created_at": t.created_at,
            "page": {"w": round(t.page_w, 1), "h": round(t.page_h, 1)},
            "pages": {k: {"source_page": p.source_page, "background": p.background, "has_card": bool(p.card), "has_photo": bool(p.photo),
                          "columns": len(p.columns)} for k, p in t.pages.items()},
            "page_images": sorted(f"pages/{x.name}" for x in (d / "pages").glob("page_*.png")),
            "colors": _palette(t), "font_family": family, "font_installed": installed, "font_fallback": t.font_fallback or "Arial",
            "styles": {k: v.model_dump() for k, v in t.styles.items()}, "label_text": t.cover.label_text,
            "footer": next((p.footer.pattern for p in t.pages.values() if p.footer), ""), "boilerplate": t.back.boilerplate,
            "image_style": t.image_style.prompt_style, "notes": t.notes}


def _palette(t: DocTemplate) -> list[dict]:
    out, seen = [], set()

    def add(role, c):
        if c and c.upper() not in seen:
            seen.add(c.upper())
            out.append({"role": role, "color": c.upper()})
    for k in ("cover", "intro", "body", "image", "conclusion", "back"):
        p = t.pages.get(k)
        if p:
            add(f"{k} page", p.background)
            if p.card:
                add(f"{k} card", p.card.color)
            for s in p.decorations:
                add(f"{k} shape", s.fill)
    add("accent / dash", t.accent)
    if t.styles.get("label"):
        add("run-in label", t.styles["label"].color)
    return out


def create_template(filename: str, src: Path, name: str, brand_id: str = "") -> dict:
    import fitz

    from backend.branddocs.reference import analyze

    if Path(filename).suffix.lower() != ".pdf":
        raise ValueError("Upload the reference as a PDF.")
    tid = new_id("btp_")
    d = root() / "templates" / tid
    (d / "pages").mkdir(parents=True)
    try:
        shutil.copyfile(src, d / "reference.pdf")
        t = analyze(d / "reference.pdf", tid, name.strip() or Path(filename).stem, brand_id)
        t.source_file = filename
        t.created_at = _now()
        if brand_id:
            try:
                typo = json.loads((get_settings().brands_path / brand_id / "typography.json").read_text(encoding="utf-8"))
                t.font_fallback = typo.get("fallback_family") or ""
            except Exception:
                pass
        save_template(t)
        doc = fitz.open(str(d / "reference.pdf"))
        for p in doc:
            p.get_pixmap(dpi=40).save(str(d / "pages" / f"page_{p.number + 1:02d}.png"))
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return template_summary(t)


def list_templates() -> list[dict]:
    out = []
    base = root() / "templates"
    if base.exists():
        for d in sorted(base.glob("btp_*"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(template_summary(load_template(d.name)))
            except Exception:
                continue
    return out


def update_template(tid: str, changes: dict) -> dict:
    t = load_template(tid)
    if "name" in changes and str(changes["name"]).strip():
        t.name = str(changes["name"]).strip()[:120]
    if "label_text" in changes:
        t.cover.label_text = str(changes["label_text"])[:60]
    if "boilerplate" in changes and isinstance(changes["boilerplate"], list):
        t.back.boilerplate = [str(x).strip() for x in changes["boilerplate"] if str(x).strip()][:8]
    if "footer" in changes:
        for p in t.pages.values():
            if p.footer:
                p.footer.pattern = str(changes["footer"])[:160]
    if "image_style" in changes and str(changes["image_style"]).strip():
        t.image_style.prompt_style = str(changes["image_style"]).strip()[:400]
    if "font_fallback" in changes:
        t.font_fallback = str(changes["font_fallback"])[:60]
    save_template(t)
    return template_summary(t)


def delete_template(tid: str) -> None:
    shutil.rmtree(tdir(tid), ignore_errors=True)


def template_file(tid: str, rel: str) -> Path:
    base = tdir(tid).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        raise KeyError(rel)
    return p


# ------------------------------------------------------------------ documents
def ddir(did: str) -> Path:
    return root() / "docs" / _safe_id(did, "bdc_")


def load_meta(did: str) -> dict:
    f = ddir(did) / "meta.json"
    if not f.exists():
        raise KeyError(did)
    return json.loads(f.read_text(encoding="utf-8"))


def update(did: str, **kw) -> dict:
    with _lock:
        f = ddir(did) / "meta.json"
        meta = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        meta.update(kw)
        meta["updated_at"] = _now()
        f.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def list_docs() -> list[dict]:
    base = root() / "docs"
    out = []
    if base.exists():
        for d in sorted(base.glob("bdc_*"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(load_meta(d.name))
            except Exception:
                continue
    return out


DEFAULTS = {"label": None, "title": "", "images": -1, "use_llm": True, "generate_images": True, "seed": 7}


def create_doc(filename: str, src: Optional[Path], text: str, template_id: str, options: dict) -> dict:
    load_template(template_id)
    did = new_id("bdc_")
    d = root() / "docs" / did
    d.mkdir(parents=True)
    if src is not None:
        ext = Path(filename).suffix.lower()
        if ext not in INPUTS:
            shutil.rmtree(d, ignore_errors=True)
            raise ValueError("Upload a PDF, Word (.docx), Markdown or text file.")
        shutil.copyfile(src, d / f"source{ext}")
        kind = INPUTS[ext]
    else:
        if len(text.split()) < 20:
            shutil.rmtree(d, ignore_errors=True)
            raise ValueError("Paste the document text (at least a few sentences).")
        (d / "source.md").write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")
        filename, kind = filename or "Pasted text.md", "markdown"
    opts = {**DEFAULTS, **{k: v for k, v in options.items() if k in DEFAULTS}}
    meta = {"id": did, "filename": filename, "source_kind": kind, "template_id": template_id, "options": opts, "status": "queued",
            "message": "Waiting to start", "progress": 0, "error": "", "created_at": _now(), "updated_at": _now(), "title": "",
            "report": None, "images": [], "pdf": "", "pages": []}
    update(did, **meta)
    start(did)
    return load_meta(did)


def start(did: str) -> None:
    t = threading.Thread(target=_run, args=(did,), daemon=True, name=f"branddoc-{did}")
    _running[did] = t
    t.start()


def is_running(did: str) -> bool:
    t = _running.get(did)
    return bool(t and t.is_alive())


def rerun(did: str, options: dict) -> dict:
    meta = load_meta(did)
    opts = {**DEFAULTS, **meta.get("options", {}), **{k: v for k, v in options.items() if k in DEFAULTS}}
    if "template_id" in options:
        load_template(options["template_id"])
        meta["template_id"] = options["template_id"]
    update(did, options=opts, template_id=meta["template_id"], status="queued", message="Waiting to start", progress=0, error="")
    start(did)
    return load_meta(did)


def delete_doc(did: str) -> None:
    shutil.rmtree(ddir(did), ignore_errors=True)


def doc_file(did: str, rel: str) -> Path:
    base = ddir(did).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        raise KeyError(rel)
    return p


def recover_stale() -> None:
    for m in list_docs():
        if m.get("status") in ("queued", "running") and not is_running(m["id"]):
            update(m["id"], status="failed", message="Interrupted - press Convert again to resume.")


# ------------------------------------------------------------------ pipeline
def _p(did: str, msg: str, pct: int) -> None:
    update(did, status="running", message=msg, progress=pct)


def plan_images(doc, tpl: DocTemplate, n: int) -> list[int]:
    """Sections that get an image page: evenly spread over the sections that flow through text pages."""
    if "image" not in tpl.pages or n <= 0:
        return []
    start = 2 if ("intro" in tpl.pages and tpl.pages["intro"].card) else 0
    cand = [i for i, s in enumerate(doc.sections) if i >= start and s.title and s.level == 1 and s.kind == "body" and s.words >= 25]
    if not cand:
        return []
    n = min(n, len(cand))
    return sorted({cand[min(len(cand) - 1, (2 * k + 1) * len(cand) // (2 * n))] for k in range(n)})


def _words(text: str) -> Counter:
    return Counter(w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’]*", text.replace("’", "'")))


def fidelity(doc, pdf_path: Path) -> dict:
    import fitz

    from backend.papers.readers.pdf import _join_lines

    out_text = "\n".join(p.get_text() for p in fitz.open(str(pdf_path)))
    out_text = re.sub(r"(\w)-\n(\w)", r"\1\2", out_text)
    src = _words(doc.all_text())
    got = _words(out_text)
    missing = {w: c - got.get(w, 0) for w, c in src.items() if c > got.get(w, 0)}
    total = sum(src.values()) or 1
    lost = sum(missing.values())
    return {"source_words": total, "coverage": round(1 - lost / total, 4),
            "missing_sample": [w for w, _ in sorted(missing.items(), key=lambda x: -x[1])][:12]}


def _run(did: str) -> None:
    from backend.branddocs import content, imagegen
    from backend.branddocs.compose import Composer
    from backend.branddocs.fonts import resolve

    try:
        meta = load_meta(did)
        opts = meta["options"]
        tpl = load_template(meta["template_id"])
        d = ddir(did)
        for sub in ("work", "images", "pages"):
            shutil.rmtree(d / sub, ignore_errors=True)
            (d / sub).mkdir(parents=True, exist_ok=True)
        src = next(d.glob("source.*"))
        _p(did, "Reading the document", 5)
        doc = content.read(src, d / "work", meta["source_kind"], meta["filename"],
                           drop_texts=[tpl.cover.label_text] + tpl.back.boilerplate)
        if opts.get("title"):
            doc.title = str(opts["title"]).strip()
        update(did, title=doc.title)
        # images
        n = opts.get("images", -1)
        if n is None or n < 0:
            n = min(3, max(1, len([s for s in doc.sections if s.level == 1 and s.title]) // 4))
        picks = plan_images(doc, tpl, int(n))
        st = tpl.image_style
        jobs: list[imagegen.ImageJob] = []
        scenes = None
        if opts.get("use_llm", True) and opts.get("generate_images", True):
            _p(did, "Describing images for the content", 12)
            scenes = imagegen.llm_scenes([(doc.title, doc.all_text()[:1500])] + [(doc.sections[i].title, doc.sections[i].text) for i in picks])
        seed = int(opts.get("seed", 7))
        cover_w, cover_h = (512, 704) if tpl.page_h >= tpl.page_w else (704, 512)
        if "cover" in tpl.pages:
            prompt = imagegen._safe(f"{scenes[0]}, {st.prompt_style}") if scenes else imagegen.section_prompt(doc.title, doc.all_text()[:3000], st.prompt_style)
            jobs.append(imagegen.ImageJob("cover", prompt, cover_w, cover_h, (int(tpl.page_w * 2.1), int(tpl.page_h * 2.1)), seed=seed))
        img_page = tpl.pages.get("image")
        for k, i in enumerate(picks):
            s = doc.sections[i]
            box = img_page.photo.box if img_page and img_page.photo else [0, 0, tpl.page_w, tpl.page_h * 0.5]
            bw, bh = box[2] - box[0], box[3] - box[1]
            gw = 704 if bw >= bh else 512
            gh = max(384, min(704, int(round(gw * bh / bw / 8)) * 8))
            prompt = imagegen._safe(f"{scenes[k + 1]}, {st.prompt_style}") if scenes else imagegen.section_prompt(s.title, s.text, st.prompt_style)
            jobs.append(imagegen.ImageJob(f"sec-{i}", prompt, gw, gh, (int(bw * 2.1), int(bh * 2.1)), seed=seed + i))
        notes: list[str] = []
        if jobs:
            _p(did, f"Preparing {len(jobs)} image{'s' if len(jobs) > 1 else ''}", 18)
            with _gen_lock:
                done = {"n": 0}

                def prog(m: str):
                    mm = re.search(r"image (\d+) of (\d+)", m)
                    pct = 20 + int(65 * (int(mm.group(1)) - 1) / max(1, int(mm.group(2)))) if mm else 20
                    _p(did, m, pct)
                notes += imagegen.run(jobs, st, d / "images", prog, use_model=bool(opts.get("generate_images", True)))
        _p(did, "Laying out the pages", 88)
        fonts = resolve(Counter(f.rsplit("-", 1)[0] for f in tpl.fonts_seen).most_common(1)[0][0] if tpl.fonts_seen else "",
                        tpl.brand_id, tpl.font_fallback)
        label = opts.get("label")
        comp = Composer(tpl, fonts, doc, {j.key: j.result for j in jobs}, label=tpl.cover.label_text if label is None else str(label))
        out = d / "document.pdf"
        res = comp.build(out, {i: f"sec-{i}" for i in picks})
        _p(did, "Checking the result", 95)
        import fitz

        pages = []
        for p in fitz.open(str(out)):
            name = f"pages/page_{p.number + 1:02d}.png"
            p.get_pixmap(dpi=50).save(str(d / name))
            pages.append(name)
        fid = fidelity(doc, out)
        used = set(res.get("used_images", []))
        images = [{"key": j.key, "file": f"images/{j.result.name}", "prompt": j.prompt, "generated": j.generated,
                   "section": doc.sections[int(j.key[4:])].title if j.key.startswith("sec-") else "Cover"} for j in jobs if j.key in used]
        if len(images) < len(jobs):
            res["notes"].append(f"{len(jobs) - len(images)} planned image page(s) were left out: the text ended before them.")
        report = {"pages": res["pages"], "sections": len(doc.sections) + (1 if doc.conclusion else 0), "words": doc.words,
                  "conclusion": doc.conclusion.title if doc.conclusion else "", "authors": [a.name for a in doc.authors],
                  "fidelity": fid, "font": {"family": fonts.family, "using_reference": fonts.using_reference, "fallback": fonts.fallback},
                  "notes": list(dict.fromkeys(fonts.notes + doc.notes + notes + res["notes"]))}
        update(did, status="done", message="Done", progress=100, pdf="document.pdf", pages=pages, images=images, report=report)
        log.info("Brand document built", doc=did, pages=res["pages"], images=len(jobs))
    except Exception as exc:
        log.error("Brand document failed", doc=did, error=type(exc).__name__, detail=str(exc)[:300])
        log.debug(traceback.format_exc())
        msg = str(exc) if isinstance(exc, ValueError) else "The document could not be converted."
        try:
            update(did, status="failed", message=msg, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        except Exception:
            pass
