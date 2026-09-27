"""Claim verification: every generated statement is checked against its cited source text.

Signals (all local, deterministic):
  * numeric grounding  - every number in a claim must appear in the cited evidence (hard rule)
  * semantic support   - best cosine similarity between the claim and an evidence sentence
  * lexical support    - share of the claim's content words present in the evidence
Claims without valid citations are re-grounded by retrieval over the slide's candidate chunks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from backend.intelligence.chunking import split_sentences
from backend.intelligence.text import number_supported, numbers_in, stems
from backend.schemas import DocumentChunk, Slide
from backend.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Verdict:
    confidence: float
    status: str
    sources: list[str]
    evidence_page: int | None
    reason: str = ""


class Verifier:
    def __init__(self, chunks: dict[str, DocumentChunk], embedder, threshold: float = 0.45):
        self.chunks = chunks
        self.embedder = embedder
        self.threshold = threshold
        self._sent_cache: dict[str, tuple[list[str], np.ndarray]] = {}

    def _sentences(self, chunk_id: str) -> tuple[list[str], np.ndarray]:
        if chunk_id not in self._sent_cache:
            ch = self.chunks[chunk_id]
            sents = [s for s in split_sentences(ch.text.replace("\n", ". ")) if len(s) > 8][:60] or [ch.text[:500]]
            self._sent_cache[chunk_id] = (sents, self.embedder.encode(sents))
        return self._sent_cache[chunk_id]

    def verify(self, text: str, cited: list[str], candidates: list[str]) -> Verdict:
        text = (text or "").strip()
        if not text:
            return Verdict(0.0, "unsupported", [], None, "empty")
        sources = [c for c in dict.fromkeys(cited) if c in self.chunks]
        claim_vec = self.embedder.encode([text])[0]

        def support(ids: list[str]) -> tuple[float, float, int | None, str | None]:
            best_sem, best_page, best_id = 0.0, None, None
            for cid in ids:
                _, vecs = self._sentences(cid)
                s = float((vecs @ claim_vec).max()) if len(vecs) else 0.0
                if s > best_sem:
                    best_sem, best_page, best_id = s, self.chunks[cid].page, cid
            ev = " ".join(self.chunks[c].text for c in ids)
            cs = stems(text)
            lex = len(cs & stems(ev)) / max(1, len(cs))
            return best_sem, lex, best_page, best_id

        sem, lex, page, best = support(sources) if sources else (0.0, 0.0, None, None)
        # re-ground: citation missing or weak -> search the slide's candidate chunks
        if (not sources or sem < 0.5) and candidates:
            pool = [c for c in candidates if c in self.chunks and c not in sources]
            scored = []
            for cid in pool:
                _, vecs = self._sentences(cid)
                if len(vecs):
                    scored.append((float((vecs @ claim_vec).max()), cid))
            scored.sort(reverse=True)
            if scored and scored[0][0] > max(sem, 0.55):
                sources = [scored[0][1]] + sources
                sem, lex, page, best = support(sources[:3])
        if not sources:
            return Verdict(0.0, "unsupported", [], None, "no supporting source found")

        evidence_numbers: set[str] = set()
        for c in sources:
            evidence_numbers |= numbers_in(self.chunks[c].text)
        claim_numbers = numbers_in(text)
        missing = [n for n in claim_numbers if not number_supported(n, evidence_numbers)]
        confidence = round(max(0.0, min(1.0, 0.6 * sem + 0.4 * lex)), 3)
        if missing:
            return Verdict(min(confidence, 0.2), "unsupported", sources, page, f"numbers not in source: {', '.join(missing[:3])}")
        status = "verified" if confidence >= self.threshold else "needs_review"
        # put the best-supporting chunk first so references point to the right page
        if best and sources[0] != best:
            sources = [best] + [s for s in sources if s != best]
        return Verdict(confidence, status, sources, page)

    # ------------------------------------------------------------------ slide level
    def verify_slide(self, slide: Slide, drop_unverified: bool = False) -> Slide:
        cands = slide.candidate_chunks
        removed = 0

        def check(item, text: str) -> bool:
            nonlocal removed
            if item.status == "structural":
                return True
            v = self.verify(text, item.sources, cands)
            item.confidence, item.sources = v.confidence, v.sources
            if hasattr(item, "evidence_page"):
                item.evidence_page = v.evidence_page
            item.status = "user_edited" if item.status == "user_edited" else v.status
            keep = v.status != "unsupported" and not (drop_unverified and v.status == "needs_review")
            if item.status == "user_edited":
                keep = True  # humans own their edits; confidence is still shown
            if not keep:
                removed += 1
            return keep

        slide.key_points = [p for p in slide.key_points if check(p, p.text)]
        for col in slide.columns:
            col.points = [p for p in col.points if check(p, p.text)]
        slide.steps = [s for s in slide.steps if check(s, step_text(s))]
        slide.kpis = [k for k in slide.kpis if check(k, f"{k.value} {k.label}")]
        if slide.quote and not check(slide.quote, slide.quote.text):
            slide.quote = None
        slide.warnings = [w for w in slide.warnings if not w.startswith("Removed ")]
        if removed:
            slide.warnings.append(f"Removed {removed} statement(s) that could not be verified against the source.")
        slide.narration = self.clean_narration(slide)
        return slide

    def clean_narration(self, slide: Slide) -> str:
        """Drop narration sentences whose numbers are not in the slide's sources."""
        if not slide.narration:
            return ""
        ids = {s for item in _items(slide) for s in item.sources} | set(slide.candidate_chunks)
        evidence = set()
        for cid in ids:
            if cid in self.chunks:
                evidence |= numbers_in(self.chunks[cid].text)
        kept = [s for s in split_sentences(slide.narration)
                if all(number_supported(n, evidence) for n in numbers_in(s))]
        return " ".join(kept)


STRUCTURAL_TITLE = re.compile(r"^(step|phase|stage|part)\s+\d+$", re.I)


def step_text(step) -> str:
    """Generated ordinal titles ('Step 2') are structure, not claims - verify the description only."""
    if STRUCTURAL_TITLE.match(step.title.strip()):
        return step.description
    return f"{step.title}. {step.description}".strip(". ")


def _items(slide: Slide):
    yield from slide.key_points
    for c in slide.columns:
        yield from c.points
    yield from slide.steps
    yield from slide.kpis
    if slide.quote:
        yield slide.quote
