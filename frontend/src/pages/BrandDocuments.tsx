import { Check, ClipboardPaste, FileStack, FileUp, ImageIcon, Loader2, Palette, Pencil, Save, Trash2, Upload, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileDrop } from "../components/FileDrop";
import { Alert, Badge, Button, Card, EmptyState, Field, Modal, Spinner, Toggle, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api, brandTemplateFileUrl } from "../services/api";
import type { BrandDocMeta, BrandDocTemplate } from "../types";
import { timeAgo } from "../utils/format";

const ACCEPT = ".pdf,.docx,.md,.markdown,.txt";
const PAGE_LABEL: Record<string, string> = { cover: "Cover", intro: "Opening card", body: "Text page", image: "Image page", conclusion: "Conclusion card", back: "Back cover" };

export function BrandDocStatus({ m }: { m: BrandDocMeta }) {
  if (m.status === "done") return <Badge tone="green">Ready</Badge>;
  if (m.status === "failed") return <Badge tone="red">Failed</Badge>;
  return <Badge tone="blue"><Loader2 className="h-3 w-3 animate-spin" /> {m.status === "queued" ? "Queued" : `${m.progress ?? 0}%`}</Badge>;
}

function Swatches({ t }: { t: BrandDocTemplate }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {t.colors.slice(0, 10).map((c) => (
        <span key={c.role + c.color} title={`${c.role}: ${c.color}`} className="h-5 w-5 rounded-full border border-slate-300" style={{ background: c.color }} />
      ))}
    </div>
  );
}

function TemplateCard({ t, selected, onSelect, onEdit }: { t: BrandDocTemplate; selected: boolean; onSelect: () => void; onEdit: () => void }) {
  return (
    <div className={`rounded-xl border-2 p-3 transition ${selected ? "border-slate-900 bg-slate-50" : "border-slate-200 hover:border-slate-400"}`}>
      <button className="w-full text-left" onClick={onSelect} aria-pressed={selected}>
        <div className="flex gap-1 overflow-hidden rounded-md bg-slate-100 p-1">
          {t.page_images.slice(0, 7).map((p) => <img key={p} src={brandTemplateFileUrl(t.id, p)} alt="" className="h-20 w-auto rounded-sm shadow-sm" />)}
        </div>
        <div className="mt-2 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{t.name}</div>
            <div className="text-xs text-slate-500">{Object.keys(t.pages).length} page designs · {t.font_family || "fonts"}{t.font_installed ? "" : ` → ${t.font_fallback}`}</div>
          </div>
          {selected && <Check className="h-4 w-4 shrink-0" />}
        </div>
      </button>
      <div className="mt-2 flex items-center justify-between">
        <Swatches t={t} />
        <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={onEdit}>Details</Button>
      </div>
    </div>
  );
}

function TemplateEditor({ t, onClose, onSaved, onDeleted }: { t: BrandDocTemplate; onClose: () => void; onSaved: (t: BrandDocTemplate) => void; onDeleted: () => void }) {
  const [name, setName] = useState(t.name);
  const [label, setLabel] = useState(t.label_text);
  const [footer, setFooter] = useState(t.footer);
  const [boiler, setBoiler] = useState(t.boilerplate.join("\n\n"));
  const [style, setStyle] = useState(t.image_style);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    try {
      onSaved(await api.updateBrandDocTemplate(t.id, { name, label_text: label, footer, image_style: style,
        boilerplate: boiler.split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean) }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const del = async () => {
    if (!confirm(`Delete the template "${t.name}"? Documents already made keep their PDF.`)) return;
    await api.deleteBrandDocTemplate(t.id);
    onDeleted();
  };
  return (
    <Modal open wide title={t.name} onClose={onClose}
      footer={<><Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={del}>Delete</Button><div className="flex-1" />
        <Button variant="secondary" onClick={onClose}>Close</Button><Button loading={busy} icon={<Save className="h-4 w-4" />} onClick={save}>Save</Button></>}>
      <div className="space-y-5">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Learned from {t.source_file}</div>
          <div className="flex gap-2 overflow-x-auto pb-2">
            {t.page_images.map((p, i) => {
              const kind = Object.entries(t.pages).find(([, v]) => v.source_page === i + 1)?.[0];
              return (
                <figure key={p} className="shrink-0 text-center">
                  <img src={brandTemplateFileUrl(t.id, p)} alt="" className="h-36 rounded border border-slate-200" />
                  <figcaption className="mt-1 text-[11px] text-slate-500">{kind ? PAGE_LABEL[kind] : "—"}</figcaption>
                </figure>
              );
            })}
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Colours (measured)</div>
            <ul className="space-y-1 text-xs">
              {t.colors.map((c) => (
                <li key={c.role + c.color} className="flex items-center gap-2"><span className="h-4 w-4 rounded border border-slate-300" style={{ background: c.color }} />
                  <code>{c.color}</code><span className="text-slate-500">{c.role}</span></li>
              ))}
            </ul>
          </div>
          <div className="space-y-2 text-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Typography</div>
            <p>Family in the reference: <b>{t.font_family || "—"}</b></p>
            {t.font_installed ? <p className="text-emerald-700">Installed: {t.font_installed.join(", ")}</p>
              : <Alert tone="warning">{t.font_family} is not installed, so documents use {t.font_fallback}. Put the licensed {t.font_family} font files (.otf/.ttf) in <code>brands/{t.brand_id || "<brand>"}/assets/fonts</code> to use the exact typeface.</Alert>}
            {Object.entries(t.styles).map(([k, s]) => (
              <p key={k} className="text-xs text-slate-600">{k}: {s.size} pt / {s.leading || "auto"} · weight {s.weight}</p>
            ))}
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Template name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Cover label" hint="Printed under the title, e.g. White Paper"><input className={inputCls} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="Footer" hint="{year} and {page} are filled in"><input className={inputCls} value={footer} onChange={(e) => setFooter(e.target.value)} /></Field>
          <Field label="Image style" hint="Added to every image description (measured from the reference photos)"><textarea className={`${inputCls} min-h-16 text-xs`} value={style} onChange={(e) => setStyle(e.target.value)} /></Field>
        </div>
        <Field label="Back-cover text" hint="Paragraphs separated by a blank line (taken from the reference)">
          <textarea className={`${inputCls} min-h-28 text-xs`} value={boiler} onChange={(e) => setBoiler(e.target.value)} />
        </Field>
        {t.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}
        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Modal>
  );
}

function AddTemplate({ onAdded }: { onAdded: (t: BrandDocTemplate) => void }) {
  const brands = useAsync(() => api.brands(), []);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("zensar");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const add = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onAdded(await api.createBrandDocTemplate(file, name, brand));
      setFile(null);
      setName("");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl border border-dashed border-slate-300 p-4">
      <div className="mb-3 text-sm font-semibold">Add a reference PDF</div>
      <FileDrop accept=".pdf" label={file ? file.name : "Drop a branded PDF (white paper, brochure, report)"}
        hint="Its page designs, colours, type, layout, logos and artwork become a template." onFiles={(f) => setFile(f[0])} />
      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_200px_auto] sm:items-end">
        <Field label="Template name"><input className={inputCls} value={name} placeholder="e.g. Zensar White Paper" onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Brand (fonts)">
          <select className={inputCls} value={brand} onChange={(e) => setBrand(e.target.value)}>
            <option value="">None</option>
            {brands.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </Field>
        <Button icon={<Upload className="h-4 w-4" />} loading={busy} disabled={!file} onClick={add}>Learn template</Button>
      </div>
      {error && <div className="mt-3"><Alert tone="error">{error}</Alert></div>}
    </div>
  );
}

export function BrandDocuments() {
  const nav = useNavigate();
  const templates = useAsync(() => api.brandDocTemplates(), []);
  const docs = useAsync(() => api.brandDocs(), []);
  const status = useAsync(() => api.brandDocStatus(), []);
  const sys = useAsync(() => api.status(), []);
  const [tpl, setTpl] = useState("");
  const [editing, setEditing] = useState<BrandDocTemplate | null>(null);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [label, setLabel] = useState<string | null>(null);
  const [images, setImages] = useState(-1);
  const [gen, setGen] = useState(true);
  const [useLlm, setUseLlm] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = templates.data?.find((t) => t.id === tpl);
  const genReady = !!status.data?.images.available;
  const llmReady = !!sys.data?.ollama.model_ready;

  useEffect(() => {
    if (!tpl && templates.data?.length) setTpl(templates.data[0].id);
  }, [templates.data, tpl]);

  // refresh the list while conversions run
  useEffect(() => {
    if (!docs.data?.some((d) => d.status === "queued" || d.status === "running")) return;
    const t = setInterval(() => docs.reload(), 3000);
    return () => clearInterval(t);
  }, [docs.data, docs]);

  const convert = async () => {
    setBusy(true);
    setError(null);
    try {
      const m = await api.convertBrandDoc({ file: mode === "file" ? file ?? undefined : undefined, text: mode === "text" ? text : undefined,
        template_id: tpl, title: title.trim() || undefined, label: label ?? undefined, images, generate_images: gen && genReady, use_llm: useLlm && llmReady });
      nav(`/brand-docs/${m.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  const nImg = images < 0 ? "auto (1–3)" : String(images);

  return (
    <>
      <PageHeader title="Brand documents"
        subtitle="Turn text, PDF or Word documents into your company's branded PDF - the layout, colours, type and artwork of a reference PDF, with images created for the content on this computer." />
      <div className="space-y-6">
        <Card title="1. Brand template" actions={<Badge tone="slate"><Palette className="h-3 w-3" /> learned from a reference PDF</Badge>}>
          {templates.loading && !templates.data ? <Spinner label="Loading templates…" /> : (
            <div className="space-y-4">
              {templates.data?.length ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {templates.data.map((t) => <TemplateCard key={t.id} t={t} selected={t.id === tpl} onSelect={() => { setTpl(t.id); setLabel(null); }} onEdit={() => setEditing(t)} />)}
                </div>
              ) : <EmptyState icon={<FileStack className="h-8 w-8" />} title="No templates yet">Add your reference PDF below - the template is learned from it.</EmptyState>}
              <AddTemplate onAdded={(t) => { templates.reload(); setTpl(t.id); setEditing(t); }} />
            </div>
          )}
        </Card>

        <Card title="2. Your document">
          <div className="mb-4 flex gap-2">
            <Button size="sm" variant={mode === "file" ? "primary" : "secondary"} icon={<FileUp className="h-3.5 w-3.5" />} onClick={() => setMode("file")}>Upload a file</Button>
            <Button size="sm" variant={mode === "text" ? "primary" : "secondary"} icon={<ClipboardPaste className="h-3.5 w-3.5" />} onClick={() => setMode("text")}>Paste the text</Button>
          </div>
          {mode === "file" ? (
            <FileDrop label={file ? file.name : "Drop the document here, or click to browse"} accept={ACCEPT}
              hint="PDF (with selectable text), Word .docx, Markdown or plain text. Headings, lists, figures and tables are kept." onFiles={(f) => setFile(f[0])} />
          ) : (
            <Field label="Document text" hint="Title on the first line. Mark headings with # (Markdown) or put them on their own line.">
              <textarea className={`${inputCls} min-h-56 text-sm`} value={text} onChange={(e) => setText(e.target.value)}
                placeholder={"# From AI talk to real value\n\n## The buzz - the hype\nEverywhere you turn...\n\n## Conclusion\n..."} />
            </Field>
          )}
        </Card>

        <Card title="3. Options">
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Title" hint="Leave empty to use the document's title"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
            <Field label="Cover label" hint="Under the title on the cover">
              <input className={inputCls} value={label ?? current?.label_text ?? ""} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. White Paper" />
            </Field>
            <Field label="Image pages" hint="Plus the cover image">
              <select className={inputCls} value={images} onChange={(e) => setImages(Number(e.target.value))}>
                <option value={-1}>Automatic (1–3)</option>
                {[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </Field>
          </div>
          <div className="mt-4 space-y-3">
            <Toggle checked={gen && genReady} disabled={!genReady} onChange={setGen}
              label={<span>Create images for the content with the local image model <span className="text-xs text-slate-500">
                ({genReady ? `${status.data?.images.model}, ${status.data?.images.license}` : status.data?.images.message ?? "checking…"})</span></span>} />
            <Toggle checked={useLlm && llmReady} disabled={!llmReady} onChange={setUseLlm}
              label={<span>Let the local AI describe each image from the text {!llmReady && <span className="text-xs text-slate-500">(no local model - key terms are used)</span>}</span>} />
          </div>
          {gen && genReady && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500"><ImageIcon className="h-3.5 w-3.5" /> Cover + {nImg} image page(s). On this computer's CPU each image takes about 1–2 minutes; nothing leaves the computer.</p>
          )}
          <div className="mt-5 flex justify-end">
            <Button icon={<Wand2 className="h-4 w-4" />} loading={busy} disabled={!tpl || (mode === "file" ? !file : text.trim().split(/\s+/).length < 20)} onClick={convert}>
              Create branded PDF
            </Button>
          </div>
          {error && <div className="mt-4"><Alert tone="error">{error}</Alert></div>}
        </Card>

        <Card title="Branded documents">
          {docs.loading && !docs.data ? <Spinner label="Loading…" /> : !docs.data?.length ? (
            <EmptyState icon={<FileStack className="h-8 w-8" />} title="Nothing yet">Your branded PDFs appear here.</EmptyState>
          ) : (
            <ul className="divide-y divide-slate-100">
              {docs.data.map((m) => (
                <li key={m.id}>
                  <Link to={`/brand-docs/${m.id}`} className="flex items-center justify-between gap-3 py-3 hover:bg-slate-50">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{m.title || m.filename}</div>
                      <div className="text-xs text-slate-500">{m.filename} · {templates.data?.find((t) => t.id === m.template_id)?.name ?? "template"} · {timeAgo(m.updated_at)}
                        {m.report ? ` · ${m.report.pages} pages` : ""}</div>
                    </div>
                    <BrandDocStatus m={m} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {editing && <TemplateEditor t={editing} onClose={() => setEditing(null)}
        onSaved={(t) => { setEditing(null); templates.reload(); if (t.id === tpl) setLabel(null); }}
        onDeleted={() => { setEditing(null); setTpl(""); templates.reload(); }} />}
    </>
  );
}
