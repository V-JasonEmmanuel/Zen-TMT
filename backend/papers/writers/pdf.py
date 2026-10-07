"""PDF in the target layout (ReportLab): page size, margins, one or two columns with a full-width
title block, the template's fonts/sizes, numbered headings, captions, tables, numbered equations,
and the formatted reference list. Fonts: Times New Roman when installed, else DejaVu Serif (ships
with matplotlib), so the PDF renders the same offline on any machine.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, FrameBreak, Image, KeepTogether, NextPageTemplate, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from backend.papers.cite_render import Rendered
from backend.papers.formats import Format
from backend.papers.math_render import as_text, render as render_math
from backend.papers.model import Block, Inline, Paper
from backend.papers.writers.common import email_line, PLACEHOLDER, Layout, ack_title, arrange, caption_label, statement_title

_FONTS: dict[str, str] = {}


def _register_fonts() -> str:
    if _FONTS:
        return _FONTS["family"]
    import os

    win = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    cands = [("TimesNR", win / "times.ttf", win / "timesbd.ttf", win / "timesi.ttf", win / "timesbi.ttf"),
             ("Liberation", Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
              Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
              Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
              Path("/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf"))]
    try:
        import matplotlib

        mpl = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        cands.append(("DejaVuSerif", mpl / "DejaVuSerif.ttf", mpl / "DejaVuSerif-Bold.ttf", mpl / "DejaVuSerif-Italic.ttf",
                      mpl / "DejaVuSerif-BoldItalic.ttf"))
    except Exception:
        pass
    for fam, r, b, i, bi in cands:
        if all(p.exists() for p in (r, b, i, bi)):
            pdfmetrics.registerFont(TTFont(fam, str(r)))
            pdfmetrics.registerFont(TTFont(fam + "-B", str(b)))
            pdfmetrics.registerFont(TTFont(fam + "-I", str(i)))
            pdfmetrics.registerFont(TTFont(fam + "-BI", str(bi)))
            pdfmetrics.registerFontFamily(fam, normal=fam, bold=fam + "-B", italic=fam + "-I", boldItalic=fam + "-BI")
            _FONTS["family"] = fam
            return fam
    _FONTS["family"] = "Times-Roman"
    return "Times-Roman"


class _Rule(Flowable):
    def __init__(self, width: float, thickness: float = 0.5):
        super().__init__()
        self.width, self.t = width, thickness

    def wrap(self, aw, ah):
        return self.width, self.t + 2

    def draw(self):
        self.canv.setLineWidth(self.t)
        self.canv.line(0, 1, self.width, 1)


class PDFWriter:
    def __init__(self, paper: Paper, fmt: Format, rend: Rendered, paper_dir: Path):
        self.p, self.f, self.r, self.dir = paper, fmt, rend, paper_dir
        self.lay: Layout = arrange(paper, fmt)
        self.font = _register_fonts()
        self.math_dir = paper_dir / "outputs" / "_math"
        self.math_as_text = 0
        self.page = A4 if fmt.page == "A4" else LETTER
        top, right, bottom, left = (x * inch for x in fmt.margins_in)
        self.m = (top, right, bottom, left)
        self.text_w = self.page[0] - left - right
        self.col_w = (self.text_w - (fmt.column_gap_in * inch if fmt.columns == 2 else 0)) / fmt.columns
        f = fmt
        lead = f.body_pt * 1.18 * f.line_spacing
        B = self.font
        self.st = {
            "body": ParagraphStyle("body", fontName=B, fontSize=f.body_pt, leading=lead, alignment=TA_JUSTIFY if f.justify else TA_LEFT,
                                   firstLineIndent=f.para_indent_in * inch),
            "body0": ParagraphStyle("body0", fontName=B, fontSize=f.body_pt, leading=lead, alignment=TA_JUSTIFY if f.justify else TA_LEFT),
            "title": ParagraphStyle("title", fontName=B + ("-B" if f.title_bold and B != "Times-Roman" else ""), fontSize=f.title_pt,
                                    leading=f.title_pt * 1.2, alignment=TA_CENTER if f.title_align == "center" else TA_LEFT, spaceAfter=10),
            # APA title page: everything in the body size, double-spaced
            "author": ParagraphStyle("author", fontName=B, fontSize=f.body_pt + (0 if f.title_page else 1),
                                     leading=lead if f.title_page else (f.body_pt + 1) * 1.3,
                                     alignment=TA_CENTER if f.title_align == "center" else TA_LEFT),
            "aff": ParagraphStyle("aff", fontName=B, fontSize=f.body_pt if f.title_page else max(8, f.body_pt - 1),
                                  leading=lead if f.title_page else max(8, f.body_pt - 1) * 1.25,
                                  alignment=TA_CENTER if f.title_align == "center" else TA_LEFT),
            "abs": ParagraphStyle("abs", fontName=B, fontSize=f.body_pt - (1 if f.id == "ieee" else 0), leading=lead * 0.98,
                                  alignment=TA_JUSTIFY if f.justify else TA_LEFT, spaceAfter=5),
            "h1": ParagraphStyle("h1", fontName=B + "-B" if f.h1_case != "smallcaps" else B, fontSize=f.h1_pt, leading=f.h1_pt * 1.25,
                                 spaceBefore=f.h1_pt * 0.9, spaceAfter=f.h1_pt * 0.45,
                                 alignment=TA_CENTER if f.h1_align == "center" else TA_LEFT, keepWithNext=1),
            "h2": ParagraphStyle("h2", fontName=B + ("-I" if f.h2_italic else "-B"), fontSize=f.h2_pt, leading=f.h2_pt * 1.25,
                                 spaceBefore=f.h2_pt * 0.7, spaceAfter=f.h2_pt * 0.35, keepWithNext=1),
            "h3": ParagraphStyle("h3", fontName=B + ("-BI" if f.id == "apa7" else "-I"), fontSize=f.body_pt, leading=f.body_pt * 1.25, spaceBefore=f.body_pt * 0.5,
                                 spaceAfter=f.body_pt * 0.2, keepWithNext=1),
            "cap": ParagraphStyle("cap", fontName=B, fontSize=f.caption_pt, leading=f.caption_pt * 1.2,
                                  alignment=TA_CENTER, spaceBefore=3, spaceAfter=8),
            "cell": ParagraphStyle("cell", fontName=B, fontSize=f.caption_pt, leading=f.caption_pt * 1.15),
            "ref": ParagraphStyle("ref", fontName=B, fontSize=f.ref_pt, leading=f.ref_pt * 1.2 * min(f.line_spacing, 1.5),
                                  alignment=TA_LEFT, spaceAfter=2, bulletFontName=B, bulletFontSize=f.ref_pt),
            "code": ParagraphStyle("code", fontName="Courier", fontSize=f.body_pt - 1.5, leading=(f.body_pt - 1.5) * 1.2),
        }
        for s in self.st.values():
            s.autoLeading = "max"  # a line holding a tall inline formula grows instead of overprinting its neighbours
        if self.font == "Times-Roman":  # built-in Type1 fonts have fixed names
            for s in self.st.values():
                s.fontName = {"Times-Roman-B": "Times-Bold", "Times-Roman-I": "Times-Italic"}.get(s.fontName, s.fontName)

    # ------------------------------------------------------------------ inline markup
    def _markup(self, runs: list[Inline], size: Optional[float] = None) -> str:
        out = []
        size = size or self.f.body_pt
        for r in runs:
            if r.cite:
                out.append(html.escape(self.r.cite_text(list(r.cite), r.t == "narrative", r.raw_cite), quote=False))
                continue
            if r.img:
                p = self.dir / r.img
                if p.exists():
                    scale = min(1.0, (size * 1.9) / max(r.img_h, 1)) if r.img_h > size * 1.9 else 1.0
                    w, h = r.img_w * scale, r.img_h * scale
                    out.append(f'<img src="{p.as_posix()}" width="{w:.1f}" height="{h:.1f}" valign="{-h * 0.3:.1f}"/>')
                continue
            if r.xref:
                from backend.papers.crossrefs import render as xref_text

                out.append(html.escape(xref_text(self.f, self.lay, r.xref, r.t), quote=False))
                continue
            if r.math:
                res = render_math(r.math, self.math_dir, size_pt=size, inline=True)
                if res:
                    path, w, h = res
                    out.append(f'<img src="{path.as_posix()}" width="{w:.1f}" height="{h:.1f}" valign="{-h * 0.28:.1f}"/>')
                else:
                    out.append("<i>" + html.escape(as_text(r.math), quote=False) + "</i>")
                    self.math_as_text += 1
                continue
            t = html.escape(r.t, quote=False)
            # explicit rise/size: ReportLab's defaults drop subscripts into the next line
            bp = self.f.body_pt
            if r.sup:
                t = f'<super rise="{bp * 0.35:.1f}" size="{bp * 0.7:.1f}">{t}</super>'
            if r.sub:
                t = f'<sub rise="{bp * 0.2:.1f}" size="{bp * 0.7:.1f}">{t}</sub>'
            if r.b:
                t = f"<b>{t}</b>"
            if r.i:
                t = f"<i>{t}</i>"
            out.append(t)
        return "".join(out)

    # ------------------------------------------------------------------ pieces
    def _front(self) -> list:
        f, p = self.f, self.p
        fl: list = [Paragraph(html.escape(p.title), self.st["title"])]
        if p.authors:
            parts = []
            for a in p.authors:
                marks = ",".join(str(x + 1) for x in a.affiliations) if len(p.affiliations) > 1 else ""
                if a.corresponding:
                    marks = (marks + "*") if marks else "*"
                parts.append(html.escape(a.name) + (f"<super>{marks}</super>" if marks else ""))
            fl.append(Paragraph(", ".join(parts), self.st["author"]))
            fl.append(Spacer(1, 4))
        for i, aff in enumerate(p.affiliations):
            mark = f"<super>{i + 1}</super>" if len(p.affiliations) > 1 else ""
            txt = html.escape(aff)
            fl.append(Paragraph(mark + (f"<i>{txt}</i>" if f.id in ("ieee", "springer_lncs") else txt), self.st["aff"]))
        emails = [a.email for a in p.authors if a.email]
        if emails:
            fl.append(Paragraph(html.escape(email_line(p)), self.st["aff"]))
        fl.append(Spacer(1, 12))
        if f.title_page:  # APA manuscript: title page, then the abstract on its own page
            from reportlab.platypus import PageBreak

            fl.insert(0, Spacer(1, 2.0 * inch))
            fl.append(PageBreak())
        if p.abstract:
            ab = self._markup(p.abstract, self.st["abs"].fontSize)
            if f.abstract_runin:
                lab = html.escape(f.abstract_label)
                lab = {"bold": f"<b>{lab}</b>", "bold-italic": f"<b><i>{lab}</i></b>", "italic": f"<i>{lab}</i>"}.get(f.abstract_label_style, lab)
                body = f"<b>{ab}</b>" if f.id == "ieee" else ab
                fl.append(Paragraph(lab + ("—" if f.id == "ieee" else " ") + body, self.st["abs"]))
            else:
                hs = ParagraphStyle("abh", parent=self.st["h1"], alignment=TA_CENTER if f.id == "apa7" else TA_LEFT,
                                    fontSize=f.body_pt + (0 if f.id != "acm" else 1), spaceBefore=0)
                fl.append(Paragraph(f"<b>{html.escape(f.abstract_label)}</b>", hs))
                fl.append(Paragraph(ab, self.st["abs"]))
        if p.keywords:
            lab = html.escape(f.keywords_label)
            if f.id == "ieee":
                txt = f"<b><i>{lab}</i>—{html.escape(f.keywords_sep.join(p.keywords))}.</b>"
            elif f.id == "apa7":
                txt = f"<i>{lab}:</i> " + html.escape(f.keywords_sep.join(p.keywords))
            else:
                txt = f"<b>{lab}</b>{'' if lab.endswith(':') else ':'} " + html.escape(f.keywords_sep.join(p.keywords))
            fl.append(Paragraph(txt, self.st["abs"]))
        if p.highlights and f.id == "elsevier":
            fl.append(Paragraph("<b>Highlights</b>", self.st["abs"]))
            for h in p.highlights:
                fl.append(Paragraph("• " + html.escape(h), self.st["abs"]))
        fl.append(Spacer(1, 10))
        if f.title_page:  # the text starts on a new page under the paper title
            from reportlab.platypus import PageBreak

            fl += [PageBreak(), Paragraph(f"<b>{html.escape(p.title)}</b>", ParagraphStyle("t2", parent=self.st["h1"], alignment=TA_CENTER, spaceBefore=0))]
        return fl

    def _heading(self, text: str, level: int) -> Paragraph:
        st = self.st["h1" if level == 1 else "h2" if level == 2 else "h3"]
        t = html.escape(text)
        if level == 1 and self.f.h1_case == "smallcaps":
            # IEEE: "I. Introduction" in small capitals -> emulate with upper case at reduced size for lower-case letters
            t = self._smallcaps(text, st.fontSize)
        return Paragraph(t, st)

    def _smallcaps(self, text: str, size: float) -> str:
        out = []
        for ch in text:
            if ch.islower():
                out.append(f'<font size="{size * 0.8:.1f}">{html.escape(ch.upper())}</font>')
            else:
                out.append(html.escape(ch))
        return "".join(out)

    def _block(self, b: Block, first: bool, width: float) -> list:
        f = self.f
        if b.kind in ("para", "quote"):
            st = self.st["body0"] if (first and f.id != "apa7") else self.st["body"]
            if b.kind == "quote":
                st = ParagraphStyle("q", parent=st, leftIndent=18, rightIndent=18, firstLineIndent=0)
            return [Paragraph(self._markup(b.runs), st)]
        if b.kind == "code":
            return [Paragraph(html.escape("".join(r.t for r in b.runs)).replace("\n", "<br/>"), self.st["code"])]
        if b.kind == "list":
            out = []
            for k, it in enumerate(b.items, start=1):
                bullet = f"{k}." if b.ordered else "•"
                out.append(Paragraph(self._markup(it), ParagraphStyle("li", parent=self.st["body0"], leftIndent=14, bulletIndent=3),
                                     bulletText=bullet))
            return out
        if b.kind == "equation":
            return [self._equation(b, width)]
        if b.kind in ("figure", "table"):
            return [self._float(b, width)]
        return []

    def _equation(self, b: Block, width: float):
        n = self.lay.eq_no.get(id(b), 0)
        cell = None
        if b.latex:
            res = render_math(b.latex, self.math_dir, size_pt=self.f.body_pt)
            if res:
                path, w, h = res
                scale = min(1.0, width * 0.82 / w)
                cell = Image(str(path), width=w * scale, height=h * scale)
        if cell is None and b.image and (self.dir / b.image).exists():
            from PIL import Image as PImage

            with PImage.open(self.dir / b.image) as im:
                w, h = im.width / 4, im.height / 4
            scale = min(1.0, width * 0.82 / w)
            cell = Image(str(self.dir / b.image), width=w * scale, height=h * scale)
        if cell is None:
            self.math_as_text += 1
            cell = Paragraph("<i>" + html.escape(as_text(b.latex) if b.latex else "".join(r.t for r in b.runs)) + "</i>", self.st["body0"])
        t = Table([[cell, Paragraph(f"({n})" if n else "", ParagraphStyle("eqn", parent=self.st["body0"], alignment=2))]],
                  colWidths=[width * 0.88, width * 0.12])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, 0), "CENTER"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    def _float(self, b: Block, width: float):
        f = self.f
        label = caption_label(f, b, self.lay)
        lab_markup = html.escape(label)
        if f.table_roman and b.kind == "table":
            capst = ParagraphStyle("tcap", parent=self.st["cap"], alignment=TA_CENTER)
            cap = Paragraph(self._smallcaps(label, f.caption_pt) + "<br/>" + self._smallcaps(_plain(b.caption), f.caption_pt), capst)
        elif f.caption_newline:  # APA: bold label line, italic title line, flush left
            capst = ParagraphStyle("apacap", parent=self.st["cap"], alignment=TA_LEFT, spaceBefore=8, spaceAfter=4)
            cap = Paragraph(f"<b>{lab_markup}</b><br/><i>{self._markup(b.caption, f.caption_pt)}</i>", capst)
        else:
            capst = ParagraphStyle("c2", parent=self.st["cap"], alignment=TA_CENTER if b.kind == "figure" or f.id in ("ieee", "springer_lncs") else TA_LEFT)
            cap = Paragraph(f"<b>{lab_markup}</b>{f.fig_sep if f.fig_sep else ' '}" + self._markup(b.caption, f.caption_pt), capst)
        items: list = []
        if b.kind == "table" and b.rows:
            ncol = max(len(r) for r in b.rows)
            rows = [[Paragraph(("<b>" if i == 0 else "") + html.escape(c) + ("</b>" if i == 0 else ""), self.st["cell"])
                     for c in (r + [""] * (ncol - len(r)))] for i, r in enumerate(b.rows)]
            cw = _col_widths(b.rows, ncol, width, self.st["cell"].fontName, f.caption_pt)
            t = Table(rows, colWidths=cw, repeatRows=1)
            t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.black), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                                   ("LINEBELOW", (0, -1), (-1, -1), 1.0, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
            body = t
        elif b.image and (self.dir / b.image).exists():
            from PIL import Image as PImage

            with PImage.open(self.dir / b.image) as im:
                ar = im.height / im.width
            w = width * 0.98
            h = w * ar
            max_h = (self.page[1] - self.m[0] - self.m[2]) * 0.62
            if h > max_h:
                h, w = max_h, max_h / ar
            body = Image(str(self.dir / b.image), width=w, height=h)
        else:
            body = Paragraph(f"<i>[{lab_markup}: file not available]</i>", self.st["cap"])
        if (b.kind == "table" and f.table_caption_above) or (b.kind == "figure" and f.fig_caption_above):
            items = [cap, body, Spacer(1, 6)]
        else:
            items = [Spacer(1, 4), body, cap]
        return KeepTogether(items)

    def _refs(self) -> list:
        f = self.f
        title = f.references_title.upper() if f.h1_case == "upper" else f.references_title
        out = [self._heading(title, 1) if f.id != "apa7" else Paragraph(f"<b>{title}</b>", ParagraphStyle("rh", parent=self.st["h1"], alignment=TA_CENTER))]
        for k in self.r.order:
            ref = self.p.ref(k)
            body = self._markup(self.r.entries.get(k) or [Inline(t=ref.raw if ref else k)], f.ref_pt)
            if self.r.author_year:
                st = ParagraphStyle("rha", parent=self.st["ref"], leftIndent=0.3 * inch, firstLineIndent=-0.3 * inch)
                out.append(Paragraph(body, st))
            else:
                st = ParagraphStyle("rhn", parent=self.st["ref"], leftIndent=0.3 * inch, firstLineIndent=0)
                out.append(Paragraph(body, st, bulletText=self.r.labels.get(k, "")))
        return out

    # ------------------------------------------------------------------ assemble
    def write(self, out: Path) -> Path:
        f = self.f
        top, right, bottom, left = self.m
        W, H = self.page
        front = self._front()
        body: list = []
        for n in self.lay.body:
            if n.heading:
                body.append(self._heading(n.heading, n.section.level))
            for i, b in enumerate(n.section.blocks):
                body += self._block(b, i == 0, self.col_w)
        if self.lay.acknowledgements:
            body.append(self._heading(ack_title(f), 1))
            for s in self.lay.acknowledgements:
                for i, b in enumerate(s.blocks):
                    body += self._block(b, i == 0, self.col_w)
        stmts = self.lay.statements
        if stmts or self.lay.missing:
            if f.id == "springer_nature":
                body.append(self._heading("Declarations", 1))
                for k in ("funding", "competing", "ethics", "data", "contributions", "declarations"):
                    if k in stmts:
                        txt = " ".join(self._markup(b.runs) for b in stmts[k].blocks)
                        lab = "" if k == "declarations" else f"<b>{statement_title(f, k)}:</b> "
                        body.append(Paragraph(lab + txt, self.st["body0"], bulletText="•"))
                    elif k in self.lay.missing:
                        body.append(Paragraph(f"<b>{statement_title(f, k)}:</b> <font backColor='#FFF2A8'>{PLACEHOLDER}</font>",
                                              self.st["body0"], bulletText="•"))
            else:
                for k, s in stmts.items():
                    body.append(self._heading(statement_title(f, k) if k != "declarations" else "Declarations", 1))
                    for i, b in enumerate(s.blocks):
                        body += self._block(b, i == 0, self.col_w)
                for k in self.lay.missing:
                    body.append(self._heading(statement_title(f, k), 1))
                    body.append(Paragraph(f"<font backColor='#FFF2A8'>{PLACEHOLDER}</font>", self.st["body0"]))
        for n in self.lay.appendix:
            if n.heading:
                body.append(self._heading(n.heading if n.section.title.lower().startswith("appendix") else f"Appendix {n.number} {n.section.title}"
                                          if n.section.level == 1 else n.heading, n.section.level))
            for i, b in enumerate(n.section.blocks):
                body += self._block(b, i == 0, self.col_w)
        if self.p.references:
            body += self._refs()

        def page_no(canv, doc):
            canv.saveState()
            canv.setFont(self.st["body0"].fontName, 8)
            canv.drawCentredString(W / 2, bottom * 0.5, str(doc.page))
            canv.restoreState()

        doc = BaseDocTemplate(str(out), pagesize=self.page, leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
                              title=self.p.title, author=", ".join(a.name for a in self.p.authors))
        if f.columns == 1:
            frame = Frame(left, bottom, self.text_w, H - top - bottom, id="one", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
            doc.addPageTemplates([PageTemplate(id="one", frames=[frame], onPage=page_no)])
            story = front + body
        else:
            fh = sum(x.wrap(self.text_w, H)[1] + getattr(x, "getSpaceBefore", lambda: 0)() + getattr(x, "getSpaceAfter", lambda: 0)() for x in front) + 6
            fh = min(fh, (H - top - bottom) * 0.75)
            gap = f.column_gap_in * inch
            ch = H - top - bottom - fh
            first = PageTemplate(id="first", onPage=page_no, frames=[
                Frame(left, H - top - fh, self.text_w, fh, id="front", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
                Frame(left, bottom, self.col_w, ch, id="c1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
                Frame(left + self.col_w + gap, bottom, self.col_w, ch, id="c2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])
            later = PageTemplate(id="later", onPage=page_no, frames=[
                Frame(left, bottom, self.col_w, H - top - bottom, id="l1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
                Frame(left + self.col_w + gap, bottom, self.col_w, H - top - bottom, id="l2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])
            doc.addPageTemplates([first, later])
            story = [NextPageTemplate("later")] + front + [FrameBreak()] + body
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.build(story)
        return out


def _col_widths(rows: list[list[str]], ncol: int, width: float, font: str, size: float) -> list[float]:
    """Column widths from real text widths: never narrower than the longest word, the rest shared by need."""
    pad = 7.0
    bold = font + "-B" if font not in ("Times-Roman",) else "Times-Bold"
    need, least = [], []
    for j in range(ncol):
        cells = [(r[j] if j < len(r) else "", i == 0) for i, r in enumerate(rows)]
        sw = lambda s, b: pdfmetrics.stringWidth(s, bold if b else font, size)  # noqa: E731
        need.append(max(sw(c, b) for c, b in cells) + pad)
        least.append(max((sw(w, b) for c, b in cells for w in c.split()), default=10) + pad)
    if sum(need) <= width:
        extra = (width - sum(need)) / ncol
        return [n + extra for n in need]
    base = sum(least)
    if base >= width:
        return [width * l / base for l in least]
    room = width - base
    want = [max(0.0, n - l) for n, l in zip(need, least)]
    tw = sum(want) or 1
    return [l + room * w / tw for l, w in zip(least, want)]


def _plain(runs: list[Inline]) -> str:
    return "".join(r.t for r in runs if not r.cite and not r.math)


def write(paper: Paper, fmt: Format, rend: Rendered, paper_dir: Path, out: Path) -> tuple[Path, int]:
    w = PDFWriter(paper, fmt, rend, paper_dir)
    w.write(out)
    return out, w.math_as_text
