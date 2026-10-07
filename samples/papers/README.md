# Sample papers for the Research Papers converter

One fictional paper, "Retrieval-Augmented Invoice Understanding with Small Language Models", in four source formats. The authors and data are fictional; the cited works are real publications.

| File | What it exercises |
|---|---|
| `sample_ieee_two_column.pdf` | Two-column IEEE-style PDF: reading order, author block, `Abstract—` / `Index Terms—`, Roman headings, numbered citations `[1]`, a chart, a ruled `TABLE I`, a numbered equation, IEEE references |
| `sample_author_year.docx` | Word file: styles, author–year citations `(LeCun et al., 2015)`, a native Word equation, a table and a figure with captions, APA references |
| `sample_latex_project.zip` | LaTeX source (article class): `\cite` keys, `references.bib`, `\label`/`\ref`, an equation, a figure file |
| `sample_raw_text.txt` | Raw pasted-style text: numbered headings, a plain-text table, APA references |

Try them in the app under **Research Papers**: upload one, pick a format (for example **Springer Nature** or **IEEE**), convert, then use **Convert to another format** to see the same paper in every style.

Regenerate the files with:

```bat
python samples\papers\make_sample_papers.py
```
