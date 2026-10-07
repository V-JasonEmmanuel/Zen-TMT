"""Citation + reference rendering in the target style (official CSL styles via citeproc-py).

Numbering and order are decided here, consistently for every output:
  numeric styles      references numbered in order of first citation (uncited ones last)
  author-year styles  references sorted by first author, year; in-text (Author, Year) from CSL
Each parsed reference is formatted by the publisher's CSL style; a reference that could not be
parsed is printed as written in the source, in its place in the list.
"""
from __future__ import annotations

import html
import re
import warnings
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from backend.papers.formats import Format, author_year, csl_for
from backend.papers.model import Inline, Paper, Reference

STYLES = Path(__file__).parent / "styles"

# in-text numeric citation conventions per CSL style
NUMERIC = {
    "ieee": {"open": "[", "close": "]", "sep": "], [", "range": "]–[", "each": True},
    "springer-basic-brackets": {"open": "[", "close": "]", "sep": ", ", "range": "–"},
    "springer-lecture-notes-in-computer-science": {"open": "[", "close": "]", "sep": ", ", "range": "–"},
    "elsevier-with-titles": {"open": "[", "close": "]", "sep": ",", "range": "–"},
    "association-for-computing-machinery": {"open": "[", "close": "]", "sep": ", ", "range": "–"},
}
LIST_LABEL = {  # how the reference list numbers entries
    "ieee": "[{n}]", "springer-basic-brackets": "{n}.", "springer-lecture-notes-in-computer-science": "{n}.",
    "elsevier-with-titles": "[{n}]", "association-for-computing-machinery": "[{n}]",
}


class _H(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.runs: list[Inline] = []
        self.i = self.b = self.sup = self.sc = False

    def handle_starttag(self, tag, attrs):
        style = dict(attrs).get("style", "")
        if tag == "i":
            self.i = True
        elif tag == "b":
            self.b = True
        elif tag == "sup":
            self.sup = True
        elif tag == "span" and "small-caps" in style:
            self.sc = True

    def handle_endtag(self, tag):
        if tag == "i":
            self.i = False
        elif tag == "b":
            self.b = False
        elif tag == "sup":
            self.sup = False
        elif tag == "span":
            self.sc = False

    def handle_data(self, data):
        t = data.upper() if self.sc else data
        if self.runs and (self.runs[-1].i, self.runs[-1].b, self.runs[-1].sup) == (self.i, self.b, self.sup):
            self.runs[-1].t += t
        else:
            self.runs.append(Inline(t=t, i=self.i, b=self.b, sup=self.sup))


def html_runs(s: str) -> list[Inline]:
    h = _H()
    h.feed(s)
    return [r for r in h.runs if r.t]


@dataclass
class Rendered:
    order: list[str] = field(default_factory=list)  # reference keys in list order
    number: dict[str, int] = field(default_factory=dict)
    entries: dict[str, list[Inline]] = field(default_factory=dict)  # formatted entry body (no label)
    labels: dict[str, str] = field(default_factory=dict)  # "[3]" / "3." for numeric lists, "" for author-year
    author_year: bool = False
    csl: str = ""
    cite_cache: dict[tuple, str] = field(default_factory=dict)

    def cite_text(self, keys: list[str], narrative: bool = False, raw: str = "") -> str:
        return self.cite_cache.get((tuple(keys), narrative), raw or "[?]")


def _first_author(ref: Reference) -> str:
    a = (ref.csl.get("author") or [{}])[0]
    return (a.get("family") or a.get("literal") or ref.raw.split(",")[0]).lower()


def _year(ref: Reference) -> str:
    y = (ref.csl.get("issued") or {}).get("date-parts", [[""]])[0][0]
    if y:
        return str(y)
    m = re.search(r"(?:19|20)\d{2}", ref.raw)
    return m.group() if m else ""


def _citation_order(paper: Paper) -> list[str]:
    order: list[str] = []
    for runs in [paper.abstract] + [r for b in paper.all_blocks() for r in (b.runs, b.caption, *b.items)]:
        for x in runs:
            for k in x.cite:
                if k not in order and paper.ref(k):
                    order.append(k)
    return order


def _clean_csl(ref: Reference) -> dict:
    item = {k: v for k, v in ref.csl.items() if not k.startswith("_")}
    item["id"] = ref.key
    if item.get("author"):
        item["author"] = [a for a in item["author"] if a.get("literal") != "et al."]
    return item


def render(paper: Paper, fmt: Format, style: str = "") -> Rendered:
    from citeproc import Citation, CitationItem, CitationStylesBibliography, CitationStylesStyle, formatter
    from citeproc.source.json import CiteProcJSON

    csl_name = csl_for(fmt, style)
    ay = author_year(fmt, style)
    out = Rendered(author_year=ay, csl=csl_name)
    refs = paper.references
    cited = _citation_order(paper)
    if ay:
        out.order = sorted((r.key for r in refs), key=lambda k: (_first_author(paper.ref(k)), _year(paper.ref(k)), k))
    else:
        out.order = cited + [r.key for r in refs if r.key not in cited]
    out.number = {k: i for i, k in enumerate(out.order, start=1)}
    usable = [r for r in refs if r.status != "raw"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        st = CitationStylesStyle(str(STYLES / f"{csl_name}.csl"), validate=False)
        source = CiteProcJSON([_clean_csl(r) for r in usable])
        bib = CitationStylesBibliography(st, source, formatter.html)
        # register in our order so numbering inside citeproc matches ours
        reg = {}
        for k in out.order:
            if any(r.key == k for r in usable):
                c = Citation([CitationItem(k)])
                bib.register(c)
                reg[k] = c
        groups = []
        for runs in [paper.abstract] + [r for b in paper.all_blocks() for r in (b.runs, b.caption, *b.items)]:
            for x in runs:
                if x.cite:
                    groups.append((tuple(x.cite), x.t == "narrative"))
        ay_cites = {}
        if ay:
            for keys, narrative in dict.fromkeys(groups):
                parsed = [k for k in keys if k in reg]
                if parsed:
                    c = Citation([CitationItem(k) for k in parsed])
                    bib.register(c)
                    ay_cites[(keys, narrative)] = c
        entries = list(bib.bibliography())
        for k, e in zip(bib.keys, entries):
            s = str(e)
            s = re.sub(r"^\s*(?:\[\d+\]|\d+\.)\s*", "", s)  # our own labels are added by the writers
            out.entries[k] = html_runs(_fix_etal(s, paper.ref(k)))
        if ay:
            for (keys, narrative), c in ay_cites.items():
                txt = _flatten(bib.cite(c, lambda item: None))
                txt = html.unescape(re.sub(r"<[^>]+>", "", txt))
                raws = [k for k in keys if k not in reg]
                if raws:
                    txt = txt.rstrip(")") + "; " + "; ".join(_raw_ay(paper.ref(k)) for k in raws) + ")"
                if narrative:  # Smith et al. (2020): authors already in the sentence -> keep "(2020)"
                    yrs = re.findall(r"(?:19|20)\d{2}[a-z]?", txt)
                    txt = "(" + ", ".join(yrs) + ")" if yrs else txt
                out.cite_cache[(keys, narrative)] = txt
    for r in refs:
        if r.key not in out.entries:
            out.entries[r.key] = [Inline(t=r.raw)]
        if not ay:
            out.labels[r.key] = LIST_LABEL.get(csl_name, "[{n}]").format(n=out.number[r.key])
    if not ay:
        conv = NUMERIC.get(csl_name, NUMERIC["springer-basic-brackets"])
        for keys, narrative in dict.fromkeys(groups):
            out.cite_cache[(keys, narrative)] = numeric_label([out.number[k] for k in keys if k in out.number], conv)
    for keys, narrative in dict.fromkeys(groups):
        if (keys, narrative) not in out.cite_cache:  # author-year group of unparsed references only
            out.cite_cache[(keys, narrative)] = "(" + "; ".join(_raw_ay(paper.ref(k)) for k in keys if paper.ref(k)) + ")"
    return out


def numeric_label(nums: list[int], conv: dict) -> str:
    nums = sorted(set(nums))
    if not nums:
        return "[?]"
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{nums[i]}{conv['range']}{nums[j]}")
        else:
            parts += [str(n) for n in nums[i:j + 1]]
        i = j + 1
    return conv["open"] + conv["sep"].join(parts) + conv["close"]


def _flatten(x) -> str:
    if isinstance(x, (list, tuple)):
        return "".join(_flatten(y) for y in x)
    return str(x)


def _fix_etal(s: str, ref: Reference) -> str:
    """Source lists that end an author list with 'et al.' keep it (CSL has no 'et al.' author)."""
    if not ref or not any(a.get("literal") == "et al." for a in ref.csl.get("author", [])):
        return s
    names = [a for a in ref.csl.get("author", []) if a.get("literal") != "et al."]
    if not names:
        return s
    last = names[-1].get("family", "")
    i = s.find(last)
    if i < 0:
        return s
    j = i + len(last)
    # skip initials that follow the family name in this style ("He K", "He, K.")
    m = re.match(r"(?:,?\s*(?:[A-Z]\.?\s?-?)+)?", s[j:])
    j += len(m.group().rstrip()) if m else 0
    if s[j:].lstrip().startswith("et al"):
        return s
    rest = s[j:]
    if rest.startswith("."):
        rest = rest[1:]
    rest = rest.lstrip()
    if not rest:
        return s[:j] + " et al."
    return s[:j] + " et al." + ("" if rest.startswith((",", ".", ":", ";")) else " ") + rest


def _raw_ay(ref: Reference) -> str:
    who = re.split(r"[,(]", ref.raw)[0].strip()
    who = who.split()[0] if who else "Anon."
    return f"{who}, {_year(ref)}".strip(", ")
