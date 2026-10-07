"""Research paper conversion: storage, background jobs and the pipeline.

    read (PDF / Word / LaTeX / Markdown / text)  ->  structure  ->  references (rules, verified local-AI
    fallback, or the .bib)  ->  link citations  ->  render citations + references in the target CSL
    style  ->  write LaTeX project, Word, PDF, BibTeX  ->  conversion report

Each paper lives in data/papers/<id>/: the uploaded source, paper.json (the structured paper, which
the user can correct in the app), figures/ and outputs/. Re-exporting to another format reuses
paper.json, so a paper is read once and can be converted to every format. Nothing is sent online.
"""
from __future__ import annotations

import json
import shutil
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.papers.formats import FORMATS
from backend.papers.model import Paper, Reference
from backend.utils.files import new_id
from backend.utils.logging import get_logger

log = get_logger(__name__)
INPUTS = {".pdf": "pdf", ".docx": "docx", ".tex": "latex", ".zip": "latex", ".md": "markdown", ".markdown": "markdown",
          ".txt": "text", ".text": "text"}
_lock = threading.Lock()
_running: dict[str, threading.Thread] = {}


def root() -> Path:
    from backend.utils.config import get_settings

    d = get_settings().data_path / "papers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdir(pid: str) -> Path:
    if not pid.startswith("pap_") or "/" in pid or "\\" in pid or ".." in pid:
        raise KeyError(pid)
    return root() / pid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_meta(pid: str) -> dict:
    f = pdir(pid) / "meta.json"
    if not f.exists():
        raise KeyError(pid)
    return json.loads(f.read_text(encoding="utf-8"))


def save_meta(pid: str, meta: dict) -> dict:
    meta["updated_at"] = _now()
    with _lock:
        (pdir(pid) / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def update(pid: str, **kw) -> dict:
    with _lock:
        f = pdir(pid) / "meta.json"
        meta = json.loads(f.read_text(encoding="utf-8"))
        meta.update(kw)
        meta["updated_at"] = _now()
        f.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load_paper(pid: str) -> Optional[Paper]:
    f = pdir(pid) / "paper.json"
    return Paper.model_validate_json(f.read_text(encoding="utf-8")) if f.exists() else None


def save_paper(pid: str, paper: Paper) -> None:
    (pdir(pid) / "paper.json").write_text(paper.model_dump_json(indent=1), encoding="utf-8")


def list_all() -> list[dict]:
    out = []
    for d in sorted(root().glob("pap_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append(load_meta(d.name))
        except Exception:
            continue
    return out


def create(filename: str, src: Optional[Path], text: str, format_id: str, citation_style: str, use_ai: bool) -> dict:
    if format_id not in FORMATS:
        raise ValueError("Unknown target format")
    pid = new_id("pap_")
    d = root() / pid
    d.mkdir(parents=True)
    if src is not None:
        ext = Path(filename).suffix.lower()
        if ext not in INPUTS:
            shutil.rmtree(d, ignore_errors=True)
            raise ValueError("Upload a PDF, Word (.docx), LaTeX (.tex or .zip), Markdown or text file.")
        shutil.copyfile(src, d / f"source{ext}")
        kind = INPUTS[ext]
    else:
        if len(text.strip()) < 200:
            shutil.rmtree(d, ignore_errors=True)
            raise ValueError("Paste the full paper text (at least a few paragraphs).")
        # browsers submit CRLF; write LF exactly (Windows text mode would turn \r\n into \r\r\n = blank lines)
        (d / "source.txt").write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")
        filename, kind = filename or "Pasted paper.txt", "text"
    meta = {"id": pid, "filename": filename, "source_kind": kind, "format": format_id, "citation_style": citation_style,
            "use_ai": use_ai, "status": "queued", "message": "Waiting to start", "error": "", "created_at": _now(),
            "updated_at": _now(), "title": "", "outputs": {}, "report": None, "stats": {}}
    save_meta(pid, meta)
    start(pid, read_source=True)
    return meta


def start(pid: str, read_source: bool) -> None:
    t = threading.Thread(target=_run, args=(pid, read_source), daemon=True, name=f"paper-{pid}")
    _running[pid] = t
    t.start()


def is_running(pid: str) -> bool:
    t = _running.get(pid)
    return bool(t and t.is_alive())


# ------------------------------------------------------------------ pipeline
def _progress(pid: str, msg: str, pct: int) -> None:
    update(pid, status="running", message=msg, progress=pct)


def read_paper(pid: str, meta: dict) -> tuple[Paper, str, list[str]]:
    from backend.papers import citations, references, structure
    from backend.papers.readers import read_any

    d = pdir(pid)
    src = next(d.glob("source.*"))
    _progress(pid, f"Reading the {meta['source_kind'].upper() if meta['source_kind'] != 'text' else 'text'}", 8)
    data = read_any(src, d, meta["source_kind"])
    _progress(pid, "Recognising the paper structure", 25)
    paper = structure.build(data["elems"], title=data.get("title", ""), front=data.get("front"),
                            source_format=meta["source_kind"], source_name=meta["filename"])
    paper.meta["footnotes"] = data.get("footnotes", [])
    notes = list(data.get("notes", []))
    # references: the .bib (LaTeX), \bibitem entries, or the reference list text
    if data.get("bib"):
        paper.references = references.from_bibtex(data["bib"])
        paper.source_citation_style = "latex"
    elif data.get("bibitems"):
        used: set[str] = set()
        refs = []
        for key, raw in data["bibitems"]:
            csl = references.verify(references.parse_rules(raw), raw)
            csl["id"] = key
            used.add(key)
            refs.append(Reference(key=key, raw=raw, csl=csl, status=references.completeness(csl), method="rules"))
        paper.references = refs
        paper.source_citation_style = "latex"
    else:
        entries = references.split_entries(data.get("refs", []))
        _progress(pid, f"Reading {len(entries)} references", 40)
        paper.references = references.build_references(entries, use_llm=meta.get("use_ai", True),
                                                        on_progress=lambda m: _progress(pid, m, 45))
        from backend.papers.model import plain

        texts = [plain(b.runs) for b in paper.all_blocks()]
        paper.source_citation_style = citations.detect_style(texts)
    if paper.source_citation_style == "latex":
        keys = {r.key for r in paper.references}
        cited = {k for b in paper.all_blocks() for r in (*b.runs, *b.caption, *[x for it in b.items for x in it]) for k in r.cite}
        for r in paper.references:
            r.cited = r.key in cited
        missing = sorted(cited - keys)
        if missing:
            notes.append(f"{len(missing)} cited key(s) are not in the bibliography: {', '.join(missing[:8])}")
    else:
        _progress(pid, "Linking citations to references", 60)
        notes += citations.link_paper(paper)
    from backend.papers import crossrefs

    crossrefs.link(paper)
    structure.normalize(paper)
    paper.warnings = notes
    (d / "source_text.txt").write_text(data.get("raw_text", ""), encoding="utf-8")
    return paper, data.get("raw_text", ""), notes


def export(pid: str, paper: Paper, format_id: str, style: str, raw_text: str = "") -> dict:
    from backend.papers import checks
    from backend.papers.cite_render import render
    from backend.papers.writers import pdf as pdf_w
    from backend.papers.writers import tex as tex_w
    from backend.papers.writers import word as word_w

    fmt = FORMATS[format_id]
    d = pdir(pid)
    out = d / "outputs" / format_id
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    _progress(pid, f"Formatting citations and references ({fmt.name})", 70)
    rend = render(paper, fmt, style)
    _progress(pid, "Writing the LaTeX project", 76)
    tex_w.write_project(paper, fmt, style, d, out / "latex_project.zip")
    _progress(pid, "Writing the Word document", 84)
    _, m1 = word_w.write(paper, fmt, rend, d, out / "paper.docx", style)
    _progress(pid, "Typesetting the PDF", 92)
    _, m2 = pdf_w.write(paper, fmt, rend, d, out / "paper.pdf")
    if not raw_text and (d / "source_text.txt").exists():
        raw_text = (d / "source_text.txt").read_text(encoding="utf-8")
    rep = checks.report(paper, fmt, raw_text, math_as_text=max(m1, m2))
    (out / "conversion_report.md").write_text(checks.markdown(rep, fmt, paper.title), encoding="utf-8")
    (out / "conversion_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    files = {"pdf": "paper.pdf", "docx": "paper.docx", "latex": "latex_project.zip", "bib": "references.bib",
             "tex": "main.tex", "report": "conversion_report.md"}
    return {"format": format_id, "citation_style": style, "files": {k: f"outputs/{format_id}/{v}" for k, v in files.items() if (out / v).exists()},
            "report": rep}


def _run(pid: str, read_source: bool) -> None:
    try:
        meta = load_meta(pid)
        raw = ""
        if read_source or load_paper(pid) is None:
            paper, raw, _ = read_paper(pid, meta)
            save_paper(pid, paper)
        else:
            paper = load_paper(pid)
        res = export(pid, paper, meta["format"], meta.get("citation_style", ""), raw)
        outputs = meta.get("outputs") or {}
        outputs[meta["format"]] = res
        stats = {"sections": len(paper.sections), "references": len(paper.references),
                 "references_parsed": sum(1 for r in paper.references if r.status == "parsed"),
                 "figures": sum(1 for b in paper.all_blocks() if b.kind == "figure"),
                 "tables": sum(1 for b in paper.all_blocks() if b.kind == "table"),
                 "equations": sum(1 for b in paper.all_blocks() if b.kind == "equation"),
                 "authors": len(paper.authors), "words": sum(len(" ".join(r.t for r in b.runs).split()) for b in paper.all_blocks())}
        update(pid, status="done", message="Converted", progress=100, title=paper.title, outputs=outputs, report=res["report"],
               stats=stats, error="")
        log.info("Paper converted", paper=pid, format=meta["format"], refs=len(paper.references))
    except Exception as exc:
        log.error("Paper conversion failed", paper=pid, error=type(exc).__name__, detail=str(exc)[:300])
        log.debug(traceback.format_exc())
        msg = str(exc) if isinstance(exc, ValueError) else "The paper could not be converted. Check that the file is a readable paper."
        try:
            update(pid, status="failed", message=msg, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        except Exception:
            pass


def reexport(pid: str, format_id: str, style: str) -> dict:
    if format_id not in FORMATS:
        raise ValueError("Unknown target format")
    meta = update(pid, format=format_id, citation_style=style, status="queued", message="Waiting to start", progress=0)
    start(pid, read_source=False)
    return meta


def delete(pid: str) -> None:
    shutil.rmtree(pdir(pid), ignore_errors=True)


def recover_stale() -> None:
    """Conversions interrupted by an app restart are marked failed (they can be re-run)."""
    for m in list_all():
        if m.get("status") in ("queued", "running") and not is_running(m["id"]):
            update(m["id"], status="failed", message="Interrupted - press Convert again to resume.")


def file_path(pid: str, rel: str) -> Path:
    base = pdir(pid).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        raise KeyError(rel)
    return p


def _json_safe(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str))
