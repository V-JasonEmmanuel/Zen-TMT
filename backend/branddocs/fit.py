"""Fit a document's content to the size of the brand reference.

A branded white paper has a set length: the reference has about N words in about K sections plus a
conclusion. A long source (a 14,000-word paper) is condensed and a short one expanded to that size, or
to a word count the user chooses:

* the source is regrouped into K parts (top-level sections, split or merged by length);
* each part is rewritten by the local LLM to its share of the words - plain English, every key point,
  fact, number and name kept, citations / author lists / figure references dropped, nothing added;
* the conclusion is condensed from the source's conclusion (or drawn only from the rewritten sections);
* every number in the result is checked against the source; parts that add numbers are redone or replaced.

Without a local LLM, condensing selects the key sentences of each part (extractive, wording unchanged);
expanding keeps the text as it is. Nothing leaves the computer.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.branddocs.content import DocContent, DocSection
from backend.papers.model import Block, Inline
from backend.utils.logging import get_logger

log = get_logger(__name__)
CITE = re.compile(r"\s*\[(?:\d+(?:\s*[-–,]\s*\d+)*)\]|\s*\((?:[A-Z][A-Za-z'’-]+(?: et al\.)?(?:,| and| &)?\s*)+,?\s*\d{4}[a-z]?\)")
FIGREF = re.compile(r"\s*\((?:see\s+)?(?:Fig(?:ure)?s?\.?|Table|Eq\.?)\s*[\dIVX]+[a-z]?\)|,?\s*as shown in (?:Fig(?:ure)?\.?|Table)\s*[\dIVX]+", re.I)
SKIP_TITLES = re.compile(r"^\s*(references|bibliography|acknowledg|appendix|funding|author contributions|competing interests|"
                         r"conflicts? of interest|data availability|ethics)", re.I)
STOP = set("""a an the and or but if then than that this these those to of in on at by for with from as is are was were be been being it its
we our you your they their them he she his her not no do does did can could should would will may might must have has had about into over
under more most less very also only such so what which who when where why how all any each other another same here there one two""".split())


@dataclass
class FitResult:
    doc: DocContent
    mode: str  # "kept" | "condensed" | "expanded" | "selected"
    source_words: int
    words: int
    method: str  # "local AI" | "key sentences" | ""
    notes: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)


def clean_heading(t: str) -> str:
    t = re.sub(r"^\s*(?:\d+(?:\.\d+)*|[IVXL]+|[A-H])[.)]?\s+(?=\S)", "", t.strip())
    if t.isupper() and len(t) > 3:
        small = {"and", "or", "of", "the", "in", "on", "for", "to", "a", "an", "vs", "with"}
        words = t.lower().split()
        t = " ".join(w if (i and w in small) else (w.upper() if w in {"rag", "ai", "llm", "llms", "nlp", "api"} else w.capitalize())
                     for i, w in enumerate(words))
    return t.strip(" .:")


def plain(text: str) -> str:
    text = CITE.sub("", text)
    text = FIGREF.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _block_text(b: Block) -> str:
    if b.kind in ("figure", "table", "equation", "code"):
        return ""
    if b.kind == "list":
        return "\n".join("- " + plain("".join(r.t for r in it)) for it in b.items)
    return plain("".join(r.t for r in b.runs if not r.img))


def _words(t: str) -> int:
    return len(t.split())


@dataclass
class Part:
    titles: list[str]
    texts: list[str]  # paragraphs, subsection headings as "## ..."

    @property
    def text(self) -> str:
        return "\n\n".join(self.texts)

    @property
    def words(self) -> int:
        return _words(self.text)


def _parts(doc: DocContent) -> list[list[DocSection]]:
    """Top-level groups: a level-1 section with its subsections."""
    groups: list[list[DocSection]] = []
    for s in doc.sections:
        if s.kind != "body" or SKIP_TITLES.match(s.title or ""):
            continue
        if not groups or (s.level <= 1 and s.title):
            groups.append([s])
        else:
            groups[-1].append(s)
    return groups


def regroup(doc: DocContent, k: int) -> list[Part]:
    groups = _parts(doc)
    units: list[list[DocSection]] = [g for g in groups if sum(s.words for s in g) > 0]

    def wsum(u):
        return sum(s.words for s in u)
    # too few parts: split the largest groups at a subsection boundary
    guard = 0
    while len(units) < k and guard < 50:
        guard += 1
        big = max(range(len(units)), key=lambda i: wsum(units[i]) if len(units[i]) > 1 else 0)
        u = units[big]
        if len(u) < 2:
            break
        half, acc, cut = wsum(u) / 2, 0, 1
        for j, s in enumerate(u):
            acc += s.words
            if acc >= half:
                cut = max(1, min(len(u) - 1, j + (1 if acc - s.words < half / 2 else 0)))
                break
        units[big:big + 1] = [u[:cut], u[cut:]]
    # too many: merge the adjacent pair with the fewest words
    while len(units) > k and len(units) > 1:
        i = min(range(len(units) - 1), key=lambda j: wsum(units[j]) + wsum(units[j + 1]))
        units[i:i + 2] = [units[i] + units[i + 1]]
    parts = []
    for u in units:
        texts, titles = [], []
        for n, s in enumerate(u):
            if s.title:
                titles.append(clean_heading(s.title))
                if n:
                    texts.append("## " + clean_heading(s.title))
            texts += [t for t in (_block_text(b) for b in s.blocks) if t]
        parts.append(Part(titles or [""], texts))
    return [p for p in parts if p.words > 0]


# ------------------------------------------------------------------ LLM rewriting
SCHEMA = {"type": "object", "properties": {"heading": {"type": "string"}, "paragraphs": {"type": "array", "items": {"type": "string"}},
                                           "bullets": {"type": "array", "items": {"type": "string"}}},
          "required": ["heading", "paragraphs"]}
SYSTEM = ("You are the editor of a corporate white paper. You rewrite source text faithfully: you never add facts, numbers, names, "
          "examples or claims that are not in the source text. You answer with JSON only.")


def _prompt(part: Part, title: str, n: int, expand: bool) -> str:
    lo, hi = int(n * 0.85), int(n * 1.15)
    task = ("Explain the text below more fully for business readers, as one section of a white paper. Make the points clearer "
            "and add context only from the text itself.") if expand else \
        "Condense the text below into one section of a white paper for business readers."
    src = part.text
    words = src.split()
    if len(words) > 2600:
        src = " ".join(words[:2600])
    return (f"{task}\n"
            f"- Length: about {n} words in total (between {lo} and {hi} words).\n"
            "- Plain, clear English. Keep every key point, fact, figure and name that matters. Drop citations such as [12], author "
            "names and affiliations, e-mail addresses, and references to figures or tables.\n"
            "- Do not add any information that is not in the text.\n"
            "- heading: a short heading for the section, 2 to 6 words, different from the document title.\n"
            "- paragraphs: 2 to 4 short paragraphs.\n"
            "- bullets: leave empty unless the text itself lists several items (types, steps, methods); then up to 4 short "
            "items that are NOT already said in the paragraphs.\n\n"
            f"Document: {title}\nSource section: {' / '.join(t for t in part.titles if t) or 'Opening'}\n\nTEXT:\n{src}")


def _call(llm, prompt: str, n: int) -> Optional[dict]:
    try:
        out = llm.generate(prompt, system=SYSTEM, json_schema=SCHEMA, max_tokens=int(n * 2.2) + 200, temperature=0.2)
        d = json.loads(out)
        paras = [str(p).strip() for p in d.get("paragraphs", []) if str(p).strip()]
        if not paras:
            return None
        bullets = [str(b).strip(" -•") for b in d.get("bullets", []) or [] if str(b).strip()][:4]
        # bullets that only repeat the paragraphs are dropped
        pw = set(re.findall(r"[a-z]{4,}", " ".join(paras).lower()))
        bullets = [b for b in bullets if len(set(re.findall(r"[a-z]{4,}", b.lower())) - pw) >= 2]
        return {"heading": str(d.get("heading", "")).strip().strip("#*: "), "paragraphs": paras, "bullets": bullets}
    except Exception as exc:
        log.info("LLM rewrite failed", error=str(exc)[:160])
        return None


def _wc(d: dict) -> int:
    return sum(_words(p) for p in d["paragraphs"]) + sum(_words(b) for b in d.get("bullets", []))


def _numbers_ok(d: dict, src_numbers: set[str]) -> list[str]:
    from backend.intelligence.text import number_supported, numbers_in

    text = " ".join(d["paragraphs"] + d.get("bullets", []) + [d.get("heading", "")])
    return [n for n in numbers_in(text) if not number_supported(n, src_numbers)]


# ------------------------------------------------------------------ extractive fallback
def _sentences(text: str) -> list[str]:
    text = re.sub(r"^## .*$", "", text, flags=re.M)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", re.sub(r"\s+", " ", text).strip())
    return [s.strip() for s in sents if _words(s) >= 5]


def select_sentences(text: str, n: int) -> list[str]:
    sents = _sentences(text)
    if not sents:
        return []
    tf = Counter(w for s in sents for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in STOP)
    scored = []
    for i, s in enumerate(sents):
        ws = [w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in STOP]
        score = sum(math.log(1 + tf[w]) for w in set(ws)) / (1 + len(ws)) ** 0.35
        score *= 1.25 if i == 0 else 1.0
        scored.append((score, i))
    chosen, total = set(), 0
    for sc, i in sorted(scored, reverse=True):
        if total >= n:
            break
        if total + _words(sents[i]) > n * 1.2 and chosen:
            continue
        chosen.add(i)
        total += _words(sents[i])
    picked = [sents[i] for i in sorted(chosen)]
    # paragraphs of ~3 sentences
    return [" ".join(picked[j:j + 3]) for j in range(0, len(picked), 3)]


# ------------------------------------------------------------------ main
def _section(heading: str, paras: list[str], bullets: list[str]) -> DocSection:
    blocks = [Block(kind="para", runs=[Inline(t=p)]) for p in paras]
    if bullets:
        blocks.insert(min(1, len(blocks)), Block(kind="list", items=[[Inline(t=b)] for b in bullets]))
    return DocSection(title=heading, level=1, blocks=blocks)


def budgets(parts: list[Part], total: int) -> list[int]:
    """Words per part: proportional to the square root of its length (short parts are not starved)."""
    w = [math.sqrt(max(1, p.words)) for p in parts]
    s = sum(w) or 1
    return [max(45, min(260, int(round(total * x / s)))) for x in w]


def trim(sections: list[DocSection], budgets_: list[int], target: int) -> None:
    """Bring the total down to the target by removing closing sentences (never rewriting): always from the section
    that is furthest over its share, never below one sentence per paragraph."""
    def words(sec):
        return sec.words
    guard = 0
    while sum(words(s) for s in sections) > target * 1.04 and guard < 400:
        guard += 1
        order = sorted(range(len(sections)), key=lambda i: -(words(sections[i]) / max(1, budgets_[i] if i < len(budgets_) else 80)))
        done = False
        for i in order:
            paras = [b for b in sections[i].blocks if b.kind == "para" and b.runs]
            # the longest paragraph with more than one sentence loses its last sentence
            for b in sorted(paras, key=lambda b: -len("".join(r.t for r in b.runs).split())):
                text = "".join(r.t for r in b.runs)
                sents = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", text.strip())
                if len(sents) > 1:
                    b.runs = [Inline(t=" ".join(sents[:-1]))]
                    done = True
                    break
            if not done:
                lists = [b for b in sections[i].blocks if b.kind == "list" and len(b.items) > 2]
                if lists:
                    lists[0].items.pop()
                    done = True
            if done:
                break
        if not done:
            break


def fit(doc: DocContent, target_words: int, target_sections: int, conclusion_words: int, use_llm: bool,
        on_progress: Callable[[str, int], None] = lambda m, p: None) -> FitResult:
    from backend.intelligence.text import numbers_in

    src_words = doc.words
    src_text = doc.all_text()
    src_numbers = numbers_in(src_text)
    if target_words <= 0 or abs(src_words - target_words) <= 0.15 * target_words:
        return FitResult(doc, "kept", src_words, src_words, "")
    expand = src_words < target_words
    llm = None
    if use_llm:
        try:
            from backend.llm import get_llm

            cand = get_llm()
            llm = cand if cand.is_available() else None
        except Exception:
            llm = None
    notes: list[str] = []
    if expand and llm is None:
        return FitResult(doc, "kept", src_words, src_words, "",
                         [f"The document has {src_words} words, fewer than the {target_words} asked for. Expanding needs the local AI "
                          "(Settings); the text was kept as it is."])
    k = max(2, target_sections)
    parts = regroup(doc, k)
    if not parts:
        return FitResult(doc, "kept", src_words, src_words, "")
    concl_src = "\n\n".join(t for t in (_block_text(b) for b in doc.conclusion.blocks) if t) if doc.conclusion else ""
    body_target = max(150, target_words - (conclusion_words if (doc.conclusion or llm) else 0))
    bud = budgets(parts, body_target)
    sections: list[DocSection] = []
    unsupported: list[str] = []
    for i, (p, n) in enumerate(zip(parts, bud)):
        on_progress(f"{'Expanding' if expand else 'Condensing'} part {i + 1} of {len(parts)} to about {n} words", int(100 * i / (len(parts) + 1)))
        d = None
        if llm is not None:
            prompt = _prompt(p, doc.title, int(n * 0.9), expand)
            for attempt in range(2):
                d = _call(llm, prompt, n)
                if d is None:
                    continue
                bad = _numbers_ok(d, src_numbers)
                wc = _wc(d)
                if not bad and 0.6 * n <= wc <= 1.5 * n:
                    break
                if attempt == 0:
                    prompt += ("\n\nYour previous answer " + (f"used numbers that are not in the text ({', '.join(bad[:5])}). " if bad else "")
                               + (f"had {wc} words; it must have about {n}." if not 0.6 * n <= wc <= 1.5 * n else ""))
            if d is not None and _numbers_ok(d, src_numbers):
                unsupported += _numbers_ok(d, src_numbers)
                d = None  # never keep invented numbers: fall back to the source's own sentences
        if d is None:
            paras = select_sentences(p.text, n) if not expand else [t for t in p.texts if not t.startswith("## ")]
            heading = next((t for t in p.titles if t), "") or (sections and "") or "Overview"
            d = {"heading": heading, "paragraphs": paras, "bullets": []}
        heading = d["heading"] or next((t for t in p.titles if t), "")
        sections.append(_section(heading, d["paragraphs"], d.get("bullets", [])))
    # conclusion
    conclusion = None
    on_progress("Writing the conclusion", 95)
    if llm is not None:
        base = concl_src or "\n\n".join(f"{s.title}: {s.text}" for s in sections)
        prompt = (f"Write the conclusion of the white paper \"{doc.title}\": 3 to 5 short paragraphs, about {conclusion_words} words in "
                  "total, each one clear statement for business readers. Use only the information in the text below; add nothing. "
                  "heading: 'Conclusion' or a short closing heading.\n\nTEXT:\n" + base[:12000])
        d = _call(llm, prompt, conclusion_words)
        if d is not None and _wc(d) < 0.6 * conclusion_words:
            d2 = _call(llm, prompt + f"\n\nYour previous answer had {_wc(d)} words; it must have about {conclusion_words}.", conclusion_words)
            d = d2 if d2 is not None and _wc(d2) > _wc(d) else d
        if d is not None and not _numbers_ok(d, src_numbers):
            conclusion = DocSection(title=d["heading"] or "Conclusion", blocks=[Block(kind="para", runs=[Inline(t=p)]) for p in d["paragraphs"]])
    if conclusion is None and concl_src:
        paras = select_sentences(concl_src, conclusion_words)
        if paras:
            conclusion = DocSection(title=clean_heading(doc.conclusion.title) or "Conclusion",
                                    blocks=[Block(kind="para", runs=[Inline(t=p)]) for p in paras])
    trim(sections, bud, target_words - (conclusion.words if conclusion else 0))
    out = DocContent(title=doc.title, sections=sections, conclusion=conclusion, authors=doc.authors, base_dir=doc.base_dir,
                     notes=[n for n in doc.notes if "inline math" not in n.lower()], raw_text=doc.raw_text)
    words = out.words
    method = "local AI" if llm is not None else "key sentences"
    if unsupported:
        notes.append(f"{len(set(unsupported))} number(s) written by the local AI were not in the source; those parts use the source's "
                     "own sentences instead.")
    if llm is None:
        notes.append("No local AI is configured, so the document was shortened by selecting its key sentences (wording unchanged). "
                     "With a local model (Settings) it is rewritten into flowing text instead.")
    return FitResult(out, "expanded" if expand else ("condensed" if llm else "selected"), src_words, words, method, notes,
                     sorted(set(unsupported)))
