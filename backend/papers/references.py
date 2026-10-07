"""Reference lists: split a source reference list into entries and parse each entry into CSL-JSON.

Parsing is rule-based first (IEEE, Springer, APA/Harvard, Elsevier, ACM and Vancouver-like
patterns). The local LLM is used only as a fallback for entries the rules cannot read completely,
and every field it returns must occur verbatim in the raw reference - nothing is invented. An entry
that still cannot be parsed is kept as written (status "raw") and flagged for review.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.papers.model import Reference

DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
URL = re.compile(r"(https?://[^\s<>\"]+)")
YEAR = re.compile(r"(?<![\d/.-])((?:19|20)\d{2})([a-z])?(?![\d/])")
ARXIV = re.compile(r"arXiv[:\s]*(\d{4}\.\d{4,5})(v\d+)?", re.I)
PAGES = re.compile(r"(?:\bpp?\.\s*)?\b([A-Za-z]?\d+)\s*[-–—]{1,2}\s*([A-Za-z]?\d+)\b")
LABEL = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})\.(?=\s|$)|(\d{1,4})\s(?=[A-Z]))\s*")
QUOTED = re.compile(r"[“\"]\s*(.+?)\s*[,.]?\s*[”\"]")
CONF_CUES = re.compile(r"\b(proc\.|proceedings|conference|conf\.|symposium|workshop|in:|in proc|annual meeting|congress)\b", re.I)
BOOK_CUES = re.compile(r"\b(press|publishers?|publishing|verlag|springer,|wiley,|elsevier,|mit press|cambridge university|oxford university|edn\.|ed\.)\b", re.I)
THESIS = re.compile(r"\b(ph\.?\s?d\.?|doctoral|master'?s?)\s+(thesis|dissertation)\b", re.I)
REPORT = re.compile(r"\b(tech(nical)?\.?\s+rep(ort)?\.?|white\s*paper)\b", re.I)


# ------------------------------------------------------------------ splitting
def split_entries(lines: list[tuple[str, float]], body_x: Optional[float] = None) -> list[tuple[str, str]]:
    """lines: (text, x0) of the reference section in reading order. Returns [(label, raw entry)].

    Numbered lists split on their labels ([1], 1., 1); author-year lists split on hanging indents
    (a line starting further left than the continuation lines) or on an author-pattern line start."""
    lines = [(t.strip(), x) for t, x in lines if t.strip()]
    if not lines:
        return []
    labelled = [LABEL.match(t) for t, _ in lines]
    nums = [int(next(g for g in m.groups() if g)) for m in labelled if m]
    sequential = len(nums) >= 2 and sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1) >= 0.6 * (len(nums) - 1)
    entries: list[list[str]] = []
    labels: list[str] = []
    if sequential:
        expect = nums[0]
        for (t, _), m in zip(lines, labelled):
            if m and int(next(g for g in m.groups() if g)) == expect:
                labels.append(m.group(0).strip())
                entries.append([t[m.end():]])
                expect += 1
            elif entries:
                entries[-1].append(t)
        return [(lb, _join(e)) for lb, e in zip(labels, entries)]
    # author-year: hanging indent, or an author-name start once the previous entry is complete
    xs = sorted(x for _, x in lines)
    left = xs[0] if xs else 0.0
    indented = len(set(round(v) for v in xs)) > 1
    for t, x in lines:
        hanging_start = x <= left + 2.0
        starts_author = bool(re.match(r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]+,?\s+(?:[A-Z]\.|[A-Z]{1,3}\b|[A-Z][a-z]+)", t))
        prev = " ".join(entries[-1]) if entries else ""
        prev_complete = bool(YEAR.search(prev)) and (prev.rstrip()[-1:] in ".)" or bool(re.search(r"(doi\.org/\S+|https?://\S+|\d)\s*$", prev)))
        new = hanging_start if indented else (starts_author and prev_complete)
        if new or not entries:
            entries.append([t])
            labels.append("")
        else:
            entries[-1].append(t)
    return [(lb, _join(e)) for lb, e in zip(labels, entries)]


def _join(parts: list[str]) -> str:
    out = ""
    for p in parts:
        if out.endswith("-") and p[:1].islower():
            out = out[:-1] + p  # hyphenated line break
        elif out.endswith(("/", "-")) and URL.search(out.split()[-1] if out.split() else ""):
            out += p  # URLs broken across lines
        else:
            out = (out + " " + p).strip()
    return re.sub(r"\s+", " ", out).strip()


# ------------------------------------------------------------------ names
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


INITIALS = r"(?:[A-Z]\.(?:\s?-?[A-Z]\.)*|[A-Z]{1,3}(?![a-z]))"
NAME_WORD = r"(?:[A-ZÀ-Ý]|[Ā-ſ])[A-Za-zÀ-ÿĀ-ſ'’\-]+"  # Latin-1 + Latin Extended-A (Ś, Ł, Č, Ž ...)
PARTICLE = r"(?:(?:van|von|der|de|del|della|di|da|la|le|du|dos|das|ter|ten|al|el|bin|ibn)\s+)*"


def parse_names(text: str) -> list[dict]:
    """Author list in any common form -> CSL names (family, given). Unknown forms -> literal names."""
    t = re.sub(r"\bet\s+al\.?", "", text).strip(" ,;")
    if t.endswith(".") and not re.search(r"\b[A-Z]\.$", t):
        t = t[:-1]
    t = re.sub(r"\s*(?:,\s*)?(?:&|\band\b)\s*", ", ", t)
    if not t:
        return []
    names: list[dict] = []
    # Family, I. (APA / Elsevier Harvard / Springer LNCS):  "He, K., Zhang, X."
    if re.fullmatch(rf"(?:{PARTICLE}{NAME_WORD}(?:\s{NAME_WORD})*,\s*{INITIALS}(?:,\s*|$))+", t + ("" if t.endswith(",") else "")):
        for m in re.finditer(rf"({PARTICLE}{NAME_WORD}(?:\s{NAME_WORD})*),\s*({INITIALS})", t):
            names.append({"family": m.group(1).strip(), "given": m.group(2).strip()})
        return names
    parts = [p.strip() for p in t.split(",") if p.strip()]
    for p in parts:
        suffix = ""
        sm = re.search(r"\s(Jr|Sr|II|III|IV)\.?$", p)
        if sm:
            suffix, p = sm.group(1), p[:sm.start()]
        # Family Initials (Springer basic / Vancouver): "He K", "van der Berg JH", "Abou Daya A", "Hosmer DW Jr"
        m = re.fullmatch(rf"({PARTICLE}{NAME_WORD}(?:\s{NAME_WORD})*)\s+([A-Z]{{1,4}}|{INITIALS})", p)
        if m and not re.fullmatch(INITIALS, m.group(1)):
            names.append({"family": m.group(1), "given": _initials(m.group(2)), **({"suffix": suffix} if suffix else {})})
            continue
        # Initials Family (IEEE): "K. He", "J.-H. Kim"
        m = re.fullmatch(rf"({INITIALS}(?:\s?{INITIALS})*)\s+({PARTICLE}{NAME_WORD}(?:\s{NAME_WORD})*)", p)
        if m:
            names.append({"family": m.group(2), "given": m.group(1).replace(" ", " ")})
            continue
        # Given Family (ACM full names): "Kaiming He", "Ashish Vaswani"
        words = p.split()
        if 2 <= len(words) <= 5 and all(re.fullmatch(rf"{NAME_WORD}|{INITIALS}|{PARTICLE.strip()}", w) or w in ("van", "von", "de", "der") for w in words):
            fam_start = next((i for i, w in enumerate(words) if w.lower() in ("van", "von", "de", "der", "del", "di", "da", "la")), len(words) - 1)
            names.append({"family": " ".join(words[fam_start:]), "given": " ".join(words[:fam_start])})
            continue
        if p:
            names.append({"literal": p})
    return names


def _initials(s: str) -> str:
    if "." in s:
        return s
    return " ".join(f"{c}." for c in s)


# ------------------------------------------------------------------ rule-based parsing
MODIFIERS = {"ˆ": "̂", "´": "́", "`": "̀", "¨": "̈", "˜": "̃", "¸": "̧", "˚": "̊", "ˇ": "̌"}


def join_urls(s: str) -> str:
    """URLs/DOIs the source broke over two lines: 'https://doi.org/10. 1109/TSE' -> one URL."""
    s = re.sub(r"((?:https?://|www\.)\S*/)\s+(?=[\w%#?=&~-])", r"\1", s)
    return re.sub(r"((?:https?://|www\.|\b10\.)\S*\.)\s+(?=\d+(?:[/A-Za-z_-]|\.\d))", r"\1", s)  # not '...263127.' + '63.' (next list label)


def fix_diacritics(s: str) -> str:
    """PDFs often store accented letters as letter + spacing accent ('Lemaıˆtre', 'Mu¨ller'): recombine them."""
    def rep(m):
        a, b = m.group(1), m.group(2)
        letter, mod = (a, b) if b in MODIFIERS else (b, a)
        letter = "i" if letter == "ı" else letter
        return unicodedata.normalize("NFC", letter + MODIFIERS[mod])
    return re.sub(r"([A-Za-zı])([ˆ´`¨˜¸˚ˇ])|([ˆ´`¨˜¸˚ˇ])([A-Za-zı])",
                  lambda m: rep(re.match(r"(.)(.)", m.group(0))), s)


def parse_rules(raw: str) -> dict[str, Any]:
    s = fix_diacritics(raw.strip())
    csl: dict[str, Any] = {}
    om = ORG.match(s)
    if om and URL.search(s) and not VANC.match(s):  # organisation as author: "Google. Imbalanced Data; 2022. https://..."
        csl = {"type": "webpage", "author": [{"literal": om.group(1).strip()}], "title": om.group(2).strip(),
               "issued": {"date-parts": [[int(om.group(3))]]}, "URL": URL.search(s).group(1).rstrip(".,;)]")}
        return csl
    if (m := DOI.search(s)):
        csl["DOI"] = m.group(1).rstrip(".,;)]")
    urls = [u.rstrip(".,;)]") for u in URL.findall(s)]
    if urls and not ("DOI" in csl and all("doi.org" in u for u in urls)):
        csl["URL"] = next((u for u in urls if "doi.org" not in u), urls[0])
    if (m := ARXIV.search(s)):
        csl["number"] = f"arXiv:{m.group(1)}"
    body = DOI.sub("", URL.sub("", s))
    body = re.sub(r"\b(?:doi|DOI)\s*:?\s*", "", body)
    # IEEE web markers "[Online]. Available:" / "Accessed: Jan. 1, 2020" - never words inside a title ("Deepwalk: Online learning")
    body = re.sub(r"\[(?:Online|Accessed|Available)[^\]]*\]\.?|\b(?:Available(?: online)?|Accessed(?: on)?)\s*:[^.]*", "", body).strip(" .,;")
    years = list(YEAR.finditer(body))
    year_m = next((y for y in years if body[max(0, y.start() - 1):y.start()] in ("(", " ") and
                   body[y.end():y.end() + 1] in (")", ".", ",", ";", " ", "")), years[0] if years else None)
    if year_m:
        csl["issued"] = {"date-parts": [[int(year_m.group(1))]]}
        if year_m.group(2):
            csl["year-suffix"] = year_m.group(2)

    authors, title, container = _best_reading(body, year_m)
    etal = bool(re.search(r"\bet\s+al\b", authors))
    if authors:
        names = parse_names(authors)
        editors = re.search(r"\(eds?\.?\)", authors)
        if names and not editors:
            csl["author"] = names + ([{"literal": "et al."}] if etal else [])
    if title:
        csl["title"] = title
    if container:
        csl["container-title"] = container
    _numbers(body, csl)
    csl["type"] = _type(s, csl)
    if csl["type"] == "book":
        pub = container or csl.get("publisher", "")
        if pub:
            csl["publisher"] = pub
        csl.pop("container-title", None)
    if csl["type"] == "thesis":
        m = THESIS.search(s)
        csl["genre"] = m.group(0) if m else "Thesis"
        rest = (container or "")[m.end() - m.start():] if m and container and container.startswith(m.group(0)) else container
        csl["publisher"] = (rest or "").strip(" ,.")
        csl.pop("container-title", None)
    if (am := ARXIV.search(s)) and csl["type"] in ("article", "article-journal", "document"):
        csl["type"], csl["container-title"], csl["number"] = "article", "arXiv", f"arXiv:{am.group(1)}"
        csl.pop("page", None)
    return csl


VANC_NAME = r"[A-ZÀ-ÝŚŁŻČŠŽ][\w'’\-]*(?:\s(?:[a-z]{1,3}\s)?[A-ZÀ-ÝŚŁŻČŠŽ][\w'’\-]+)*\s[A-Z]{1,4}(?:\s(?:Jr|Sr|II|III|IV))?"
VANC = re.compile(rf"^((?:{VANC_NAME})(?:,\s(?:{VANC_NAME}))*(?:,\set\sal)?)\.\s+(.*)$")
ORG = re.compile(r"^([A-Z][\w&.\- ]{1,50}?)\.\s+(.+?)[;.]\s*((?:19|20)\d{2})\b")


def _readings(body: str, year_m) -> list[tuple[str, str, str]]:
    """Candidate (authors, title, rest) readings, one per reference-style pattern."""
    out = []
    m = VANC.match(body)
    if m:  # Vancouver / NLM (PLOS, medicine, many CS journals): Family AB, Family C. Title. Journal. 2020; 1(2):3-4.
        t, r = _split_title(m.group(2))
        out.append((m.group(1), t, r))
    q = QUOTED.search(body)
    if q:  # IEEE: Authors, “Title,” in Container, vol. 1, pp. 1-2, 2020.
        out.append((body[:q.start()], q.group(1).strip().rstrip(",."), body[q.end():]))
    if year_m and body[year_m.start() - 1:year_m.start()] == "(":
        # Springer basic / APA: Authors (2016) Title. Container 38:770-778
        rest = body[year_m.end():].lstrip(")").lstrip(" .,:")
        t, r = _split_title(rest)
        out.append((body[:year_m.start() - 1], t, r))
    if year_m and re.match(r"^[,.]\s", body[year_m.end():year_m.end() + 2] or ""):
        # Elsevier Harvard: Authors, 2016. Title. | ACM: Authors. 2016. Title.
        rest = body[year_m.end():].lstrip(" .,")
        t, r = _split_title(rest)
        out.append((body[:year_m.start()], t, r))
    m = re.match(r"^(.+?):\s+(.*)$", body)
    if m and len(m.group(1)) < 400:
        # LNCS: Authors: Title. Container 38(7), 436–444 (2015)
        t, r = _split_title(m.group(2))
        out.append((m.group(1), t, r))
    names_end = _names_end(body)
    if names_end:
        # Elsevier numeric / Vancouver: Authors, Title, Container 521 (2015) 436–444.
        rest = body[names_end:].strip(" ,.")
        t, r = _split_title(rest, sep_comma=True)
        out.append((body[:names_end], t, r))
    return out


def _best_reading(body: str, year_m) -> tuple[str, str, str]:
    best, best_score = ("", "", ""), -1
    for authors, title, rest in _readings(body, year_m):
        authors = authors.strip(" ,")
        if authors.endswith(".") and not re.search(r"\b[A-Z]\.$", authors):
            authors = authors[:-1]
        names = parse_names(authors)
        clean = bool(names) and all("literal" not in n for n in names)
        container = _container(rest)
        score = (4 if clean else 0) + (2 if 3 <= len(title) <= 300 else 0) + (1 if container else 0) - (2 if len(authors) > 400 else 0)
        if score > best_score:
            best, best_score = (authors, title, container), score
    return best


def _names_end(body: str) -> int:
    """End of a leading author list written as 'A. Name, B. Name, and C. Name,' or 'Name A, Name B,'."""
    m = re.match(rf"^((?:{INITIALS}\s?)+{PARTICLE}{NAME_WORD}(?:,\s*(?:and\s+)?(?:{INITIALS}\s?)+{PARTICLE}{NAME_WORD})*(?:,?\s*(?:and|&)\s+(?:{INITIALS}\s?)+{PARTICLE}{NAME_WORD})?)(?:,?\s*et\s+al\.?)?[,.]", body)
    if m:
        return m.end()
    m = re.match(rf"^((?:{PARTICLE}{NAME_WORD}\s+[A-Z]{{1,3}}(?:,\s*|\s+and\s+))*{PARTICLE}{NAME_WORD}\s+[A-Z]{{1,3}})(?:,?\s*et\s+al\.?)?[.,]", body)
    return m.end() if m else 0


def _split_title(rest: str, sep_comma: bool = False) -> tuple[str, str]:
    """Title runs to the first sentence end ('. ', '? ', '! ') that is not an initial/abbreviation."""
    for m in re.finditer(r"([.?!])\s+(?=[A-Z0-9(“\"]|In[: ]|in\s)", rest):
        cand = rest[:m.start() + (1 if m.group(1) in "?!" else 0)]
        if len(cand) < 8 or re.search(r"\b[A-Z]$|\b(?:vs|no|vol|pp|ed|eds|e\.g|i\.e|al|Proc|Int|J|Conf)$", cand):
            continue
        return cand.strip(" ,"), rest[m.end():]
    if sep_comma and ", " in rest:
        cand, after = rest.split(", ", 1)
        return cand.strip(), after
    return rest.strip(" ."), ""


def _container(rest: str) -> str:
    r = re.sub(r"^(?:In:|in:|In|in)\s+", "", rest.strip(" ,."))
    r = re.sub(r"^(?:Proc\.|Proceedings)\s+of\s+the\s+", lambda m: m.group(0), r)
    # stop at volume / pages / year / publisher-location markers
    stop = re.search(r",?\s*(?:vol\.|Vol\.|no\.|pp\b\.?|p\.|\(\d|\d+\s*\(|\d+:\d|\d+,\s*\d+\s*[-–]|\b(?:19|20)\d{2}\b|\d+\s*[-–]\d+|,\s*\d+\b|\s\d+\b)", r)
    c = r[:stop.start()] if stop else r
    c = re.sub(r"\(eds?\.?\)|\beds?\.\s*", "", c).strip(" ,.:;(")
    c = re.sub(r"^[A-Z][^,:]{0,80}\(eds?\.?\)[,:]?\s*", "", c)
    return c if 2 <= len(c) <= 250 else ""


def _numbers(body: str, csl: dict) -> None:
    if (m := re.search(r"\bvol(?:ume)?\.?\s*(\d+)", body, re.I)):
        csl["volume"] = m.group(1)
    if (m := re.search(r"\bno\.?\s*(\d+)|\bissue\s*(\d+)", body, re.I)):
        csl["issue"] = m.group(1) or m.group(2)
    if "volume" not in csl and (m := re.search(r"\b(\d{1,4})\s*\((\d{1,4}(?:[-–]\d{1,4})?)\)", body)):
        if not YEAR.fullmatch(m.group(1)) and not YEAR.fullmatch(m.group(2)):
            csl["volume"], csl["issue"] = m.group(1), m.group(2)
    if "volume" not in csl and (m := re.search(r"[A-Za-z.],\s*(\d{1,4})\s*(?:\((\d{1,4})\))?,\s*[A-Za-z]?\d+\s*[-–]", body)):
        if not YEAR.fullmatch(m.group(1)):  # APA: Journal, 33, 1877–1901 | Journal, 521(7553), 436–444
            csl["volume"] = m.group(1)
            if m.group(2):
                csl["issue"] = m.group(2)
    if "volume" not in csl and (m := re.search(r"[A-Za-z.]\s+(\d{1,4})\s*\((?:19|20)\d{2}\)", body)):
        csl["volume"] = m.group(1)  # Elsevier numeric: Nature 521 (2015) 436-444
    if "volume" not in csl and (m := re.search(r"\b(\d{1,4}):\s*([A-Za-z]?\d+(?:\s*[-–]\s*[A-Za-z]?\d+)?)", body)):
        csl["volume"], csl["page"] = m.group(1), m.group(2).replace(" ", "")
    if "page" not in csl:
        pm = [p for p in PAGES.finditer(body) if not (YEAR.fullmatch(p.group(1)) and YEAR.fullmatch(p.group(2)))]
        if pm:
            p = pm[-1]
            csl["page"] = f"{p.group(1)}–{p.group(2)}"
        elif (m := re.search(r"\bp\.\s*(\d+)\b|\barticle\s+(?:no\.\s*)?(\w+)|\b(e\d{4,})\b", body, re.I)):
            csl["page"] = next(g for g in m.groups() if g)
    if "volume" not in csl and (m := re.search(r"[A-Za-z]\s+(\d{1,4})\s*,\s*\d", body)):
        csl["volume"] = m.group(1)
    if (m := re.search(r"(\d+)(?:st|nd|rd|th)?\s+edn?\.", body)):
        csl["edition"] = m.group(1)
    if (m := re.search(r"\b([A-Z][A-Za-z.&\s]+(?:Press|Publishers?|Verlag|Springer|Wiley|Elsevier|IEEE|ACM))\b", body)) and BOOK_CUES.search(body):
        csl["publisher"] = m.group(1).strip()


def _type(s: str, csl: dict) -> str:
    if THESIS.search(s):
        return "thesis"
    if REPORT.search(s):
        return "report"
    if "number" in csl and str(csl["number"]).startswith("arXiv") and not csl.get("container-title"):
        csl["container-title"] = f"arXiv preprint {csl['number']}"
        return "article"
    if CONF_CUES.search(s):
        return "paper-conference"
    if BOOK_CUES.search(s) and not csl.get("volume"):
        return "book" if not re.search(r"\bIn:?\s", s) else "chapter"
    if csl.get("container-title") and (csl.get("volume") or csl.get("page")):
        return "article-journal"
    if csl.get("URL") and not csl.get("container-title"):
        return "webpage"
    return "article-journal" if csl.get("container-title") else "document"


# ------------------------------------------------------------------ quality + verification
def completeness(csl: dict) -> str:
    has = lambda k: bool(csl.get(k))  # noqa: E731
    if has("author") and has("title") and has("issued") and (has("container-title") or has("publisher") or csl.get("type") in ("webpage", "document", "book", "report", "thesis")):
        authors = csl.get("author", [])
        org = len(authors) == 1 and "literal" in authors[0] and len(authors[0]["literal"].split()) <= 6
        if org or all("literal" not in a or a["literal"] == "et al." for a in authors):
            return "parsed"
    if has("title") and (has("author") or has("issued")):
        return "partial"
    return "raw"


def verify(csl: dict, raw: str) -> dict:
    """Keep only fields that literally occur in the raw reference (protects against invented values)."""
    nr = _norm(raw)
    out: dict[str, Any] = {}
    for k, v in csl.items():
        if k in ("type", "id"):
            out[k] = v
        elif k == "author":
            names = [a for a in v if all(_norm(p) in nr for p in (a.get("family"), a.get("literal")) if p)]
            if names and len(names) == len(v):
                out[k] = names
        elif k == "issued":
            y = str(v.get("date-parts", [[None]])[0][0])
            if y in raw:
                out[k] = v
        elif isinstance(v, str) and v:
            if _norm(v) and _norm(v) in nr:
                out[k] = v
        elif v:
            out[k] = v
    return out


# ------------------------------------------------------------------ LLM fallback
class LLMName(BaseModel):
    family: str
    given: str = ""


class LLMReference(BaseModel):
    type: str = Field("article-journal", description="article-journal | paper-conference | book | chapter | thesis | report | webpage | article")
    authors: list[LLMName] = Field(default_factory=list)
    year: Optional[int] = None
    title: str = ""
    container_title: str = Field("", description="journal, proceedings or book title")
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    doi: str = ""


def parse_llm(raw: str, llm) -> dict:
    from backend.llm.structured_output import generate_structured

    prompt = ("Split this bibliography entry into its fields. Copy every value exactly as written in the entry; "
              "leave a field empty if it is not present. Do not correct, complete or translate anything.\n\n"
              f"Entry: {raw}")
    r = generate_structured(llm, prompt, LLMReference, system="You extract bibliographic fields. Output JSON only.",
                            retries=1, max_tokens=500)
    csl: dict[str, Any] = {"type": r.type if r.type in ("article-journal", "paper-conference", "book", "chapter", "thesis",
                                                         "report", "webpage", "article") else "article-journal"}
    if r.authors:
        csl["author"] = [{"family": a.family.strip(), "given": a.given.strip()} for a in r.authors if a.family.strip()]
    if r.year:
        csl["issued"] = {"date-parts": [[r.year]]}
    for k, v in (("title", r.title), ("container-title", r.container_title), ("volume", r.volume), ("issue", r.issue),
                 ("page", r.pages), ("publisher", r.publisher), ("DOI", r.doi)):
        if v.strip():
            csl[k] = v.strip()
    return csl


# ------------------------------------------------------------------ public
def make_key(csl: dict, raw: str, used: set[str]) -> str:
    fam = ""
    if csl.get("author"):
        a = csl["author"][0]
        fam = a.get("family") or a.get("literal") or ""
    if not fam:
        fam = re.sub(r"\W+", "", raw.split()[0] if raw.split() else "ref")
    fam = re.sub(r"[^A-Za-z]", "", unicodedata.normalize("NFKD", fam).encode("ascii", "ignore").decode()).lower() or "ref"
    year = str((csl.get("issued") or {}).get("date-parts", [[""]])[0][0] or "")
    word = ""
    if csl.get("title"):
        w = [x for x in re.findall(r"[A-Za-z]+", csl["title"]) if x.lower() not in ("a", "an", "the", "on", "of", "for", "and", "in", "to")]
        word = w[0].lower() if w else ""
    base = f"{fam}{year}{word}"[:40] or "ref"
    key, n = base, 2
    while key in used:
        key, n = f"{base}{chr(96 + n)}", n + 1
    used.add(key)
    return key


def build_references(entries: list[tuple[str, str]], use_llm: bool = True, on_progress=None) -> list[Reference]:
    llm = None
    if use_llm:
        try:
            from backend.llm import get_llm

            llm = get_llm()
            if not llm.is_available():
                llm = None
        except Exception:
            llm = None
    used: set[str] = set()
    refs: list[Reference] = []
    for i, (label, raw) in enumerate(entries):
        raw = join_urls(fix_diacritics(raw))
        if on_progress:
            on_progress(f"Reading reference {i + 1} of {len(entries)}")
        csl = verify(parse_rules(raw), raw)
        status, method = completeness(csl), "rules"
        if status != "parsed" and llm is not None:
            try:
                alt = verify(parse_llm(raw, llm), raw)
                alt.setdefault("type", csl.get("type", "article-journal"))
                if _score(alt) > _score(csl):
                    csl, method = {**csl, **alt}, "llm"
                    status = completeness(csl)
            except Exception:
                pass
        csl["id"] = make_key(csl, raw, used)
        refs.append(Reference(key=csl["id"], raw=raw, csl=csl, status=status, method=method, source_label=label))
    return refs


def _score(csl: dict) -> int:
    return sum(1 for k in ("author", "title", "issued", "container-title", "volume", "page", "publisher") if csl.get(k)) + \
        (2 if completeness(csl) == "parsed" else 0)


def from_bibtex(text: str) -> list[Reference]:
    """BibTeX (.bib) entries -> references (exact fields, no parsing guesswork)."""
    import bibtexparser
    from bibtexparser.bparser import BibTexParser
    from pylatexenc.latex2text import LatexNodes2Text

    l2t = LatexNodes2Text()
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    db = bibtexparser.loads(text, parser=parser)
    tmap = {"article": "article-journal", "inproceedings": "paper-conference", "conference": "paper-conference",
            "book": "book", "incollection": "chapter", "inbook": "chapter", "phdthesis": "thesis", "mastersthesis": "thesis",
            "techreport": "report", "misc": "document", "online": "webpage", "unpublished": "manuscript"}
    refs = []
    for e in db.entries:
        f = {k: l2t.latex_to_text(v).strip() for k, v in e.items() if k not in ("ID", "ENTRYTYPE")}
        csl: dict[str, Any] = {"id": e["ID"], "type": tmap.get(e["ENTRYTYPE"].lower(), "document")}
        if f.get("author"):
            csl["author"] = [_bib_name(n) for n in re.split(r"\s+and\s+", f["author"]) if n.strip()]
        if f.get("editor"):
            csl["editor"] = [_bib_name(n) for n in re.split(r"\s+and\s+", f["editor"]) if n.strip()]
        if f.get("year") and re.match(r"\d{4}", f["year"]):
            csl["issued"] = {"date-parts": [[int(f["year"][:4])]]}
        for src, dst in (("title", "title"), ("journal", "container-title"), ("booktitle", "container-title"),
                         ("volume", "volume"), ("number", "issue"), ("pages", "page"), ("publisher", "publisher"),
                         ("doi", "DOI"), ("url", "URL"), ("edition", "edition"), ("address", "publisher-place"),
                         ("school", "publisher"), ("institution", "publisher")):
            if f.get(src) and dst not in csl:
                csl[dst] = f[src].replace("--", "–") if src == "pages" else f[src]
        raw = ", ".join(x for x in (f.get("author", ""), f.get("title", ""), f.get("journal") or f.get("booktitle", ""), f.get("year", "")) if x)
        refs.append(Reference(key=e["ID"], raw=raw, csl=csl, status=completeness(csl), method="bibtex"))
    return refs


def _bib_name(n: str) -> dict:
    n = n.strip().strip("{}")
    if n.lower() == "others":
        return {"literal": "et al."}
    if "," in n:
        fam, given = n.split(",", 1)
        return {"family": fam.strip(), "given": given.strip()}
    parts = n.split()
    return {"family": parts[-1], "given": " ".join(parts[:-1])} if len(parts) > 1 else {"literal": n}
