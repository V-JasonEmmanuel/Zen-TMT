"""Small text utilities shared by relevance, verification and planning."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a an the and or but if of to in on for with by from as at is are was were be been being this that these those
    it its into over under than then there their they them we our you your he she his her i me my not no nor so such
    can could should would may might will shall do does did done have has had having also more most very which who
    whom whose what when where why how all any each few other some only own same too just about between both during
    before after above below up down out off again further once here via per using used use based while within without
    however thus therefore hence e.g i.e etc et al""".split()
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")
# Numbers may carry unit suffixes ("12x", "45ms", "3.5M") - they must still be checked against the source.
NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?(?!\d)")


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    return toks if keep_stopwords else [t for t in toks if t not in STOPWORDS and len(t) > 1]


def stem(token: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "ers", "er", "es", "ed", "ly", "s"):
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            return token[: -len(suf)]
    return token


def stems(text: str) -> set[str]:
    return {stem(t) for t in tokenize(text)}


def numbers_in(text: str) -> set[str]:
    """Normalised numeric tokens: '1,234' -> '1234', '12.50%' -> '12.5%'."""
    out = set()
    for m in NUMBER.findall(text):
        n = m.replace(",", "").lstrip("+")
        pct = n.endswith("%")
        n = n.rstrip("%")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n + ("%" if pct else ""))
    return out


def number_supported(num: str, source_numbers: set[str]) -> bool:
    if num in source_numbers:
        return True
    bare = num.rstrip("%")
    return bare in {s.rstrip("%") for s in source_numbers}


def shorten(text: str, max_words: int) -> str:
    """Shorten at a clause boundary where possible; never invent words."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    cut = " ".join(words[:max_words])
    for sep in ("; ", ", ", " - ", " – "):
        pos = cut.rfind(sep)
        if pos > len(cut) * 0.55:
            return cut[:pos].rstrip(" ,;-–") + "…"
    return cut.rstrip(" ,;:-–") + "…"
