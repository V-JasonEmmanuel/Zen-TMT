"""CSL-JSON references -> BibTeX (.bib) for the LaTeX project."""
from __future__ import annotations

from backend.papers.model import Reference
from backend.papers.writers.tex import escape

TYPES = {"article-journal": "article", "article": "article", "paper-conference": "inproceedings", "book": "book",
         "chapter": "incollection", "thesis": "phdthesis", "report": "techreport", "webpage": "misc", "document": "misc",
         "manuscript": "unpublished"}


def _names(names: list[dict]) -> str:
    out = []
    for a in names:
        if a.get("literal") == "et al.":
            out.append("others")
        elif a.get("literal"):
            out.append("{" + escape(a["literal"]) + "}")
        else:
            out.append(f"{escape(a.get('family', ''))}, {escape(a.get('given', ''))}".strip(", "))
    return " and ".join(out)


def entry(r: Reference) -> str:
    c = r.csl
    if r.status == "raw" or not c.get("title"):
        return f"@misc{{{r.key},\n  note = {{{escape(r.raw)}}}\n}}\n"
    typ = TYPES.get(c.get("type", ""), "misc")
    if typ == "phdthesis" and "master" in str(c.get("genre", "")).lower():
        typ = "mastersthesis"
    f: dict[str, str] = {}
    if c.get("author"):
        f["author"] = _names(c["author"])
    if c.get("editor"):
        f["editor"] = _names(c["editor"])
    f["title"] = "{" + escape(c["title"]) + "}"
    cont = c.get("container-title", "")
    if cont:
        f["journal" if typ == "article" else "booktitle" if typ in ("inproceedings", "incollection") else "howpublished"] = escape(cont)
    y = (c.get("issued") or {}).get("date-parts", [[None]])[0][0]
    if y:
        f["year"] = str(y)
    for src, dst in (("volume", "volume"), ("issue", "number"), ("edition", "edition")):
        if c.get(src):
            f[dst] = escape(str(c[src]))
    if c.get("page"):
        f["pages"] = str(c["page"]).replace("–", "--").replace("—", "--")
    if c.get("publisher"):
        f["school" if typ.endswith("thesis") else "institution" if typ == "techreport" else "publisher"] = escape(c["publisher"])
    if c.get("publisher-place"):
        f["address"] = escape(c["publisher-place"])
    if c.get("DOI"):
        f["doi"] = c["DOI"]
    if c.get("URL"):
        f["url"] = c["URL"]
    if c.get("number") and str(c["number"]).startswith("arXiv:"):
        f["eprint"] = str(c["number"])[6:]
        f["archiveprefix"] = "arXiv"
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in f.items())
    return f"@{typ}{{{r.key},\n{body}\n}}\n"


def write(refs: list[Reference]) -> str:
    return "\n".join(entry(r) for r in refs)
