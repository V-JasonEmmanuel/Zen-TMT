import { BookOpenText, Check, ClipboardPaste, FileUp, GraduationCap, Loader2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileDrop } from "../components/FileDrop";
import { Alert, Badge, Button, Card, EmptyState, Field, Spinner, Toggle, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";
import type { PaperFormat, PaperMeta } from "../types";
import { timeAgo } from "../utils/format";

const ACCEPT = ".pdf,.docx,.tex,.zip,.md,.markdown,.txt";

export function FormatPicker({ formats, value, onChange }: { formats: PaperFormat[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {formats.map((f) => (
        <button key={f.id} onClick={() => onChange(f.id)} aria-pressed={value === f.id}
          className={`rounded-xl border-2 p-4 text-left transition ${value === f.id ? "border-slate-900 bg-slate-50" : "border-slate-200 hover:border-slate-400"}`}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">{f.name}</div>
              <div className="text-xs text-slate-500">{f.publisher} · {f.columns === 2 ? "two columns" : "single column"} · {f.page} · {f.latex_class}</div>
            </div>
            {value === f.id && <Check className="h-4 w-4 shrink-0 text-slate-900" />}
          </div>
          <p className="mt-2 text-xs text-slate-600">{f.description}</p>
        </button>
      ))}
    </div>
  );
}

export function PaperStatus({ m }: { m: PaperMeta }) {
  if (m.status === "done") return <Badge tone="green">Converted</Badge>;
  if (m.status === "failed") return <Badge tone="red">Failed</Badge>;
  return <Badge tone="blue"><Loader2 className="h-3 w-3 animate-spin" /> {m.status === "queued" ? "Queued" : "Converting"}</Badge>;
}

export function ResearchPapers() {
  const nav = useNavigate();
  const formats = useAsync(() => api.paperFormats(), []);
  const list = useAsync(() => api.papers(), []);
  const status = useAsync(() => api.status(), []);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [format, setFormat] = useState("springer_nature");
  const [style, setStyle] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fmt = formats.data?.find((f) => f.id === format);
  const aiReady = !!status.data?.ollama.model_ready;

  const convert = async () => {
    setBusy(true);
    setError(null);
    try {
      const m = await api.convertPaper({ file: mode === "file" ? file ?? undefined : undefined, text: mode === "text" ? text : undefined,
        format, citation_style: style, use_ai: useAi && aiReady });
      nav(`/papers/${m.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Research papers" subtitle="Convert a paper into a publisher's format: structure, citations, references, captions and layout. Everything runs on this computer." />
      <div className="space-y-6">
        <Card title="1. Your paper">
          <div className="mb-4 flex gap-2">
            <Button size="sm" variant={mode === "file" ? "primary" : "secondary"} icon={<FileUp className="h-3.5 w-3.5" />} onClick={() => setMode("file")}>Upload a file</Button>
            <Button size="sm" variant={mode === "text" ? "primary" : "secondary"} icon={<ClipboardPaste className="h-3.5 w-3.5" />} onClick={() => setMode("text")}>Paste the text</Button>
          </div>
          {mode === "file" ? (
            <>
              <FileDrop label={file ? file.name : "Drop the paper here, or click to browse"} accept={ACCEPT}
                hint="PDF (with selectable text), Word .docx, LaTeX .tex or a .zip of the LaTeX project (with .bib and figures), Markdown or plain text"
                onFiles={(f) => setFile(f[0])} />
              <p className="mt-2 text-xs text-slate-500">For the most exact result upload the LaTeX or Word source: equations then stay editable, and BibTeX references are used as they are.</p>
            </>
          ) : (
            <Field label="Paper text" hint="Title on the first line, then authors, Abstract, sections and References - as in the paper.">
              <textarea className={`${inputCls} min-h-56 font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} placeholder={"Paper title\nAuthor One, Author Two\nUniversity ...\n\nAbstract\n...\n\n1. Introduction\n...\n\nReferences\n[1] ..."} />
            </Field>
          )}
        </Card>

        <Card title="2. Target format">
          {formats.loading && !formats.data ? <Spinner label="Loading formats…" /> : <FormatPicker formats={formats.data ?? []} value={format} onChange={(id) => { setFormat(id); setStyle(""); }} />}
          {fmt && fmt.citation_styles.length > 1 && (
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Citation style</span>
              {fmt.citation_styles.map((s) => (
                <button key={s} onClick={() => setStyle(s === "numeric" ? "" : s)}
                  className={`rounded-full border px-3 py-1 text-xs ${((style || "numeric") === s) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300"}`}>
                  {s === "numeric" ? "Numbered [1]" : "Author–year (Smith, 2020)"}
                </button>
              ))}
            </div>
          )}
          {fmt?.notes.map((n) => <p key={n} className="mt-2 text-xs text-slate-500">{n}</p>)}
        </Card>

        <Card title="3. Convert">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Toggle checked={useAi && aiReady} disabled={!aiReady} onChange={setUseAi}
              label={<span>Use the local AI for references the rules cannot read {!aiReady && <span className="text-xs text-slate-500">(no local model installed)</span>}</span>} />
            <Button icon={<GraduationCap className="h-4 w-4" />} loading={busy}
              disabled={(mode === "file" ? !file : text.trim().length < 200) || !format} onClick={convert}>Convert paper</Button>
          </div>
          <p className="mt-3 text-xs text-slate-500">The paper's wording is never rewritten: the structure, numbering, citations, reference list, captions and layout change. You get a LaTeX project in the publisher's class, a Word file, a PDF and a report of the publisher's checks.</p>
          {error && <div className="mt-4"><Alert tone="error">{error}</Alert></div>}
        </Card>

        <Card title="Converted papers">
          {list.loading && !list.data ? <Spinner label="Loading…" /> : !list.data?.length ? (
            <EmptyState icon={<BookOpenText className="h-8 w-8" />} title="No papers yet">Upload a paper above. Sample papers are in samples/papers.</EmptyState>
          ) : (
            <ul className="divide-y divide-slate-100">
              {list.data.map((m) => (
                <li key={m.id}>
                  <Link to={`/papers/${m.id}`} className="flex items-center justify-between gap-3 py-3 hover:bg-slate-50">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{m.title || m.filename}</div>
                      <div className="text-xs text-slate-500">{m.filename} → {formats.data?.find((f) => f.id === m.format)?.name ?? m.format} · {timeAgo(m.updated_at)}</div>
                    </div>
                    <PaperStatus m={m} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
