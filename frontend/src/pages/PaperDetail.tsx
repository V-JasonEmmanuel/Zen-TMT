import { AlertTriangle, ArrowLeft, CheckCircle2, Download, FileText, Info, Plus, RefreshCw, Save, Trash2, Wand2, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Alert, Badge, Button, Card, EmptyState, Field, Modal, Spinner, Tabs, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, paperFileUrl } from "../services/api";
import type { PaperDoc, PaperMeta, PaperReference } from "../types";
import { timeAgo } from "../utils/format";
import { FormatPicker, PaperStatus } from "./ResearchPapers";

type Tab = "preview" | "review" | "references" | "report" | "downloads";

const DOWNLOADS: { key: string; label: string; desc: string }[] = [
  { key: "pdf", label: "PDF", desc: "Typeset in the target layout" },
  { key: "docx", label: "Word (.docx)", desc: "Editable, styled to the template" },
  { key: "latex", label: "LaTeX project (.zip)", desc: "main.tex in the publisher's class + references.bib + figures" },
  { key: "bib", label: "BibTeX (.bib)", desc: "All references" },
  { key: "tex", label: "main.tex", desc: "The LaTeX source on its own" },
  { key: "report", label: "Conversion report", desc: "The publisher's checks (Markdown)" },
];

function names(csl: Record<string, unknown>): string {
  const a = (csl.author as { family?: string; given?: string; literal?: string }[] | undefined) ?? [];
  return a.map((x) => x.literal ?? [x.family, x.given].filter(Boolean).join(", ")).join("; ");
}

function year(csl: Record<string, unknown>): string {
  const i = csl.issued as { "date-parts"?: number[][] } | undefined;
  return String(i?.["date-parts"]?.[0]?.[0] ?? "");
}

function RefEditor({ r, onClose, onSave }: { r: PaperReference; onClose: () => void; onSave: (r: PaperReference) => void }) {
  const [raw, setRaw] = useState(r.raw);
  const [csl, setCsl] = useState<Record<string, unknown>>({ ...r.csl });
  const [authors, setAuthors] = useState(names(r.csl));
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setCsl((c) => ({ ...c, [k]: v || undefined }));
  const reparse = async () => {
    setBusy(true);
    try {
      const res = await api.parseReference(raw);
      setCsl({ ...res.csl });
      setAuthors(names(res.csl));
    } finally { setBusy(false); }
  };
  const save = () => {
    const list = authors.split(";").map((s) => s.trim()).filter(Boolean).map((s) => {
      if (s === "et al.") return { literal: "et al." };
      const [family, given] = s.split(",").map((x) => x.trim());
      return given ? { family, given } : { literal: family };
    });
    const y = Number(String(csl._year ?? year(csl)).slice(0, 4));
    const out: Record<string, unknown> = { ...csl, author: list.length ? list : undefined };
    delete out._year;
    if (y) out.issued = { "date-parts": [[y]] };
    onSave({ ...r, raw, csl: out, method: "user" });
  };
  const field = (k: string, label: string) => (
    <Field label={label}><input className={inputCls} value={String(csl[k] ?? "")} onChange={(e) => set(k, e.target.value)} /></Field>
  );
  return (
    <Modal open wide title={`Reference ${r.source_label || r.key}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={save} icon={<Save className="h-4 w-4" />}>Save</Button></>}>
      <div className="space-y-4">
        <Field label="As written in the paper" hint="Correct the text if it was split wrongly, then read it again.">
          <textarea className={`${inputCls} min-h-20 text-xs`} value={raw} onChange={(e) => setRaw(e.target.value)} />
        </Field>
        <Button size="sm" variant="secondary" loading={busy} icon={<Wand2 className="h-3.5 w-3.5" />} onClick={reparse}>Read the fields from this text</Button>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Authors (Family, Given; Family, Given)"><input className={inputCls} value={authors} onChange={(e) => setAuthors(e.target.value)} /></Field>
          <Field label="Year"><input className={inputCls} value={String(csl._year ?? year(csl))} onChange={(e) => setCsl((c) => ({ ...c, _year: e.target.value }))} /></Field>
          <div className="md:col-span-2">{field("title", "Title")}</div>
          {field("container-title", "Journal / proceedings / book")}
          <Field label="Type">
            <select className={inputCls} value={String(csl.type ?? "article-journal")} onChange={(e) => set("type", e.target.value)}>
              {["article-journal", "paper-conference", "book", "chapter", "thesis", "report", "webpage", "article"].map((t) => <option key={t}>{t}</option>)}
            </select>
          </Field>
          {field("volume", "Volume")}{field("issue", "Issue")}{field("page", "Pages")}{field("publisher", "Publisher")}{field("DOI", "DOI")}{field("URL", "URL")}
        </div>
      </div>
    </Modal>
  );
}

export function PaperDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [meta, setMeta] = useState<(PaperMeta & { paper: PaperDoc | null }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("preview");
  const [draft, setDraft] = useState<PaperDoc | null>(null);
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState<PaperReference | null>(null);
  const [exporting, setExporting] = useState(false);
  const [target, setTarget] = useState("");
  const [targetStyle, setTargetStyle] = useState("");
  const formats = useAsync(() => api.paperFormats(), []);

  const load = useCallback(async () => {
    try {
      const m = await api.paper(id);
      setMeta(m);
      if (!dirty) setDraft(m.paper);
      setError(null);
      return m;
    } catch (e) { setError((e as Error).message); return null; }
  }, [id, dirty]);

  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const active = meta && (meta.status === "queued" || meta.status === "running" || meta.running);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [active, load]);

  const fmt = formats.data?.find((f) => f.id === meta?.format);
  const out = meta?.outputs?.[meta.format];
  const v = meta?.updated_at ?? "";
  const refs = draft?.references ?? [];

  const patch = (p: Partial<PaperDoc>) => { if (draft) { setDraft({ ...draft, ...p }); setDirty(true); } };

  const saveAndExport = async (format?: string, style?: string) => {
    if (!meta) return;
    setExporting(true);
    setError(null);
    try {
      if (dirty && draft) await api.savePaper(meta.id, draft);
      setDirty(false);
      const m = await api.exportPaper(meta.id, format ?? meta.format, style ?? meta.citation_style);
      setMeta({ ...meta, ...m, paper: draft });
      setTarget("");
    } catch (e) { setError((e as Error).message); }
    setExporting(false);
  };

  const counts = useMemo(() => ({
    parsed: refs.filter((r) => r.status === "parsed").length, partial: refs.filter((r) => r.status === "partial").length,
    raw: refs.filter((r) => r.status === "raw").length,
  }), [refs]);

  if (!meta) return error ? <Alert tone="error">{error}</Alert> : <Spinner label="Loading…" />;

  return (
    <>
      <div className="mb-6">
        <Link to="/papers" className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"><ArrowLeft className="h-3.5 w-3.5" /> Research papers</Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3"><h1 className="truncate text-2xl font-semibold tracking-tight">{meta.title || meta.filename}</h1><PaperStatus m={meta} /></div>
            <p className="mt-1 text-sm text-slate-500">{meta.filename} → <b>{fmt?.name ?? meta.format}</b>{meta.citation_style ? ` (${meta.citation_style})` : ""} · updated {timeAgo(meta.updated_at)}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {dirty && <Button icon={<Save className="h-4 w-4" />} loading={exporting} onClick={() => saveAndExport()}>Save corrections & re-convert</Button>}
            <Button variant="secondary" icon={<RefreshCw className="h-4 w-4" />} disabled={!!active} onClick={() => setTarget(meta.format)}>Convert to another format</Button>
            <Button variant="ghost" icon={<Trash2 className="h-4 w-4 text-red-600" />} disabled={!!active}
              onClick={async () => { if (confirm("Delete this paper and its converted files?")) { await api.deletePaper(meta.id); nav("/papers"); } }}>Delete</Button>
          </div>
        </div>
      </div>
      {error && <div className="mb-4"><Alert tone="error">{error}</Alert></div>}
      {active && (
        <Card className="mb-6">
          <div className="flex items-center justify-between text-sm"><span className="font-medium">{meta.message}</span><span className="text-slate-500">{meta.progress ?? 0}%</span></div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-slate-900 transition-all" style={{ width: `${meta.progress ?? 3}%` }} /></div>
        </Card>
      )}
      {meta.status === "failed" && (
        <div className="mb-6"><Alert tone="error" title="The conversion failed">{meta.message}{meta.error && <span className="block text-xs opacity-70">{meta.error}</span>}
          <div className="mt-2"><Button size="sm" variant="secondary" onClick={async () => { await api.rereadPaper(meta.id); load(); }}>Try again</Button></div></Alert></div>
      )}
      {meta.status === "done" && meta.report && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Badge tone="green">{meta.report.summary.ok ?? 0} checks passed</Badge>
          {(meta.report.summary.warning ?? 0) > 0 && <Badge tone="amber">{meta.report.summary.warning} to review</Badge>}
          {(meta.report.summary.error ?? 0) > 0 && <Badge tone="red">{meta.report.summary.error} errors</Badge>}
          <Badge tone="blue">{Math.round((meta.report.fidelity.coverage ?? 0) * 1000) / 10}% of the text preserved</Badge>
          {meta.stats && <Badge>{meta.stats.sections} sections · {meta.stats.figures} figure{meta.stats.figures === 1 ? "" : "s"} · {meta.stats.tables} table{meta.stats.tables === 1 ? "" : "s"} · {meta.stats.equations} equation{meta.stats.equations === 1 ? "" : "s"} · {meta.stats.references} references</Badge>}
        </div>
      )}

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "preview", label: "Preview" }, { id: "review", label: "Structure" },
        { id: "references", label: "References", badge: refs.length ? <Badge tone={counts.raw || counts.partial ? "amber" : "green"}>{refs.length}</Badge> : undefined },
        { id: "report", label: "Report" }, { id: "downloads", label: "Downloads" },
      ]} />
      <div className="mt-6">
        {tab === "preview" && (out?.files.pdf ? (
          <object data={paperFileUrl(meta.id, out.files.pdf, false, v)} type="application/pdf" className="h-[80vh] w-full rounded-xl border border-slate-200 bg-white">
            <p className="p-6 text-sm">The PDF cannot be shown here. <a className="underline" href={paperFileUrl(meta.id, out.files.pdf, true)}>Download it</a>.</p>
          </object>
        ) : active ? <Spinner label="Converting…" /> : <EmptyState title="No preview yet" />)}

        {tab === "review" && draft && (
          <div className="space-y-6">
            <Card title="Front matter">
              <div className="space-y-4">
                <Field label="Title"><input className={inputCls} value={draft.title} onChange={(e) => patch({ title: e.target.value })} /></Field>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Authors</div>
                  <div className="space-y-2">
                    {draft.authors.map((a, i) => (
                      <div key={i} className="grid gap-2 md:grid-cols-[1fr_8rem_1fr_auto_auto] md:items-center">
                        <input className={inputCls} value={a.name} placeholder="Name" onChange={(e) => patch({ authors: draft.authors.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} />
                        <input className={inputCls} value={a.affiliations.map((n) => n + 1).join(",")} placeholder="Affil. 1,2" title="Affiliation numbers"
                          onChange={(e) => patch({ authors: draft.authors.map((x, j) => j === i ? { ...x, affiliations: e.target.value.split(",").map((s) => Number(s.trim()) - 1).filter((n) => n >= 0) } : x) })} />
                        <input className={inputCls} value={a.email} placeholder="Email" onChange={(e) => patch({ authors: draft.authors.map((x, j) => j === i ? { ...x, email: e.target.value } : x) })} />
                        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={a.corresponding} onChange={(e) => patch({ authors: draft.authors.map((x, j) => j === i ? { ...x, corresponding: e.target.checked } : x) })} /> Corresponding</label>
                        <button className="text-slate-400 hover:text-red-600" aria-label="Remove author" onClick={() => patch({ authors: draft.authors.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>
                      </div>
                    ))}
                    <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => patch({ authors: [...draft.authors, { name: "", affiliations: [], email: "", orcid: "", corresponding: false }] })}>Add author</Button>
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Affiliations</div>
                  {draft.affiliations.map((a, i) => (
                    <div key={i} className="mb-2 flex items-center gap-2">
                      <span className="w-6 text-right text-xs text-slate-500">{i + 1}</span>
                      <input className={inputCls} value={a} onChange={(e) => patch({ affiliations: draft.affiliations.map((x, j) => j === i ? e.target.value : x) })} />
                      <button className="text-slate-400 hover:text-red-600" aria-label="Remove affiliation" onClick={() => patch({ affiliations: draft.affiliations.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>
                    </div>
                  ))}
                  <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => patch({ affiliations: [...draft.affiliations, ""] })}>Add affiliation</Button>
                </div>
                <Field label="Abstract" hint={draft.abstract.some((r) => r.cite?.length || r.math) ? "Contains citations or math - edit them in the source." : `${draft.abstract.map((r) => r.t).join("").split(/\s+/).filter(Boolean).length} words`}>
                  <textarea className={`${inputCls} min-h-32`} value={draft.abstract.map((r) => r.t).join("")} disabled={draft.abstract.some((r) => r.cite?.length || r.math)}
                    onChange={(e) => patch({ abstract: [{ t: e.target.value }] })} />
                </Field>
                <Field label="Keywords (comma separated)">
                  <input className={inputCls} value={draft.keywords.join(", ")} onChange={(e) => patch({ keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
                </Field>
                {meta.format === "elsevier" && (
                  <Field label="Highlights (one per line, max. 85 characters each)">
                    <textarea className={`${inputCls} min-h-20`} value={draft.highlights.join("\n")} onChange={(e) => patch({ highlights: e.target.value.split("\n").filter((s) => s.trim()) })} />
                  </Field>
                )}
              </div>
            </Card>
            <Card title="Sections" actions={<span className="text-xs text-slate-500">Numbering is applied by the target format</span>}>
              <ul className="space-y-2">
                {draft.sections.map((s, i) => (
                  <li key={i} className="flex items-center gap-2" style={{ paddingLeft: (s.level - 1) * 20 }}>
                    <select className={`${inputCls} w-20`} value={s.level} onChange={(e) => patch({ sections: draft.sections.map((x, j) => j === i ? { ...x, level: Number(e.target.value) } : x) })}>
                      {[1, 2, 3].map((n) => <option key={n} value={n}>H{n}</option>)}
                    </select>
                    <input className={inputCls} value={s.title} onChange={(e) => patch({ sections: draft.sections.map((x, j) => j === i ? { ...x, title: e.target.value } : x) })} />
                    <select className={`${inputCls} w-48`} value={s.kind} onChange={(e) => patch({ sections: draft.sections.map((x, j) => j === i ? { ...x, kind: e.target.value } : x) })}>
                      {[["body", "Body section"], ["acknowledgements", "Acknowledgements"], ["funding", "Funding"], ["competing", "Competing interests"],
                        ["data", "Data availability"], ["contributions", "Author contributions"], ["ethics", "Ethics"], ["declarations", "Declarations"], ["appendix", "Appendix"]]
                        .map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                    <span className="w-28 shrink-0 text-right text-xs text-slate-500">{s.blocks.length} block{s.blocks.length === 1 ? "" : "s"}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        )}

        {tab === "references" && draft && (
          <Card title={`References (${refs.length})`} actions={<span className="text-xs text-slate-500">{counts.parsed} fully read · {counts.partial} partly · {counts.raw} kept as written</span>}>
            {refs.length === 0 ? <EmptyState title="No reference list was found" /> : (
              <ul className="divide-y divide-slate-100">
                {refs.map((r, i) => (
                  <li key={r.key} className="flex items-start gap-3 py-3">
                    <span className="w-10 shrink-0 pt-0.5 text-xs text-slate-500">{r.source_label || i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm"><b>{String(r.csl.title ?? "")}</b>{r.csl.title ? " · " : ""}<span className="text-slate-600">{names(r.csl)}</span>{year(r.csl) && <span className="text-slate-600"> ({year(r.csl)})</span>}</div>
                      <div className="text-xs text-slate-500">{String(r.csl["container-title"] ?? r.csl.publisher ?? "")}{r.csl.volume ? `, vol. ${r.csl.volume}` : ""}{r.csl.issue ? `(${r.csl.issue})` : ""}{r.csl.page ? `, pp. ${r.csl.page}` : ""}{r.csl.DOI ? ` · doi:${r.csl.DOI}` : ""}</div>
                      <div className="mt-1 text-xs text-slate-400">{r.raw}</div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge tone={r.status === "parsed" ? "green" : r.status === "partial" ? "amber" : "red"}>{r.status === "parsed" ? "Read" : r.status === "partial" ? "Check" : "As written"}</Badge>
                      {!r.cited && <Badge tone="amber">Not cited</Badge>}
                      {r.method === "llm" && <Badge tone="blue">Local AI</Badge>}
                      <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Edit</Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}

        {tab === "report" && (meta.report ? (
          <Card title={`Checks for ${fmt?.name ?? meta.format}`}>
            <ul className="space-y-2">
              {meta.report.checks.map((c, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  {c.level === "ok" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : c.level === "info" ? <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
                    : c.level === "warning" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />}
                  <div><div className="font-medium">{c.title}</div>{c.detail && <div className="text-xs text-slate-500">{c.detail}</div>}</div>
                </li>
              ))}
            </ul>
          </Card>
        ) : <EmptyState title="No report yet" />)}

        {tab === "downloads" && (
          <div className="space-y-6">
            {Object.values(meta.outputs ?? {}).map((o) => (
              <Card key={o.format} title={formats.data?.find((f) => f.id === o.format)?.name ?? o.format}>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {DOWNLOADS.filter((d) => o.files[d.key]).map((d) => (
                    <a key={d.key} href={paperFileUrl(meta.id, o.files[d.key], true)} className="flex items-start gap-3 rounded-xl border border-slate-200 p-4 hover:border-slate-400">
                      {d.key === "pdf" || d.key === "docx" ? <FileText className="h-5 w-5 text-slate-500" /> : <Download className="h-5 w-5 text-slate-500" />}
                      <div><div className="text-sm font-semibold">{d.label}</div><div className="text-xs text-slate-500">{d.desc}</div></div>
                    </a>
                  ))}
                </div>
              </Card>
            ))}
            {!Object.keys(meta.outputs ?? {}).length && <EmptyState title="Nothing to download yet" />}
          </div>
        )}
      </div>

      {editing && draft && (
        <RefEditor r={editing} onClose={() => setEditing(null)} onSave={(r) => {
          patch({ references: draft.references.map((x) => x.key === r.key ? r : x) });
          setEditing(null);
        }} />
      )}
      {target && (
        <Modal open wide title="Convert to another format" onClose={() => setTarget("")} footer={<>
          <Button variant="secondary" onClick={() => setTarget("")}>Cancel</Button>
          <Button loading={exporting} onClick={() => saveAndExport(target, targetStyle)}>Convert</Button>
        </>}>
          <p className="mb-4 text-sm text-slate-600">The paper is not read again - your corrections are kept. Each format's files are kept side by side in Downloads.</p>
          <FormatPicker formats={formats.data ?? []} value={target} onChange={(f) => { setTarget(f); setTargetStyle(""); }} />
          {formats.data?.find((f) => f.id === target)?.citation_styles.length === 2 && (
            <div className="mt-4 flex gap-2">
              {["numeric", "author-year"].map((s) => (
                <button key={s} onClick={() => setTargetStyle(s === "numeric" ? "" : s)}
                  className={`rounded-full border px-3 py-1 text-xs ${((targetStyle || "numeric") === s) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300"}`}>
                  {s === "numeric" ? "Numbered [1]" : "Author–year (Smith, 2020)"}
                </button>
              ))}
            </div>
          )}
        </Modal>
      )}
    </>
  );
}
