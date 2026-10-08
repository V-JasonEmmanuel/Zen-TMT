import { ArrowLeft, CheckCircle2, Download, ImageIcon, Info, RefreshCw, Shuffle, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Alert, Badge, Button, Card, Field, Spinner, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api, brandDocFileUrl } from "../services/api";
import type { BrandDocMeta } from "../types";
import { timeAgo } from "../utils/format";
import { BrandDocStatus } from "./BrandDocuments";

export function BrandDocDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [meta, setMeta] = useState<BrandDocMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const templates = useAsync(() => api.brandDocTemplates(), []);
  const [title, setTitle] = useState("");
  const [label, setLabel] = useState("");
  const [images, setImages] = useState(-1);
  const [tpl, setTpl] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const m = await api.brandDoc(id);
      setMeta(m);
      setError(null);
      return m;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  useEffect(() => {
    load().then((m) => {
      if (m) {
        setTitle(m.options.title || "");
        setLabel(m.options.label ?? "");
        setImages(m.options.images ?? -1);
        setTpl(m.template_id);
      }
    });
  }, [load]);

  const active = meta && (meta.status === "queued" || meta.status === "running" || meta.running);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [active, load]);

  const rerun = async (extra: Record<string, unknown> = {}) => {
    if (!meta) return;
    setBusy(true);
    try {
      setMeta(await api.rerunBrandDoc(id, { title, label, images, template_id: tpl, ...extra }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const del = async () => {
    if (!confirm("Delete this branded document?")) return;
    await api.deleteBrandDoc(id);
    nav("/brand-docs");
  };

  if (!meta) return error ? <Alert tone="error">{error}</Alert> : <Spinner label="Loading…" />;
  const r = meta.report;
  const v = meta.updated_at;
  const cov = r ? Math.round(r.fidelity.coverage * 1000) / 10 : 0;

  return (
    <>
      <Link to="/brand-docs" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Brand documents</Link>
      <PageHeader title={meta.title || meta.filename}
        subtitle={<span>{meta.filename} · {templates.data?.find((t) => t.id === meta.template_id)?.name ?? "template"} · {timeAgo(meta.updated_at)}</span>}
        actions={<>
          <BrandDocStatus m={meta} />
          {meta.status === "done" && <a href={brandDocFileUrl(id, meta.pdf, true)}><Button icon={<Download className="h-4 w-4" />}>Download PDF</Button></a>}
          <Button variant="secondary" icon={<Trash2 className="h-4 w-4" />} disabled={!!active} onClick={del}>Delete</Button>
        </>} />

      {active && (
        <Card className="mb-6">
          <div className="flex items-center justify-between text-sm"><span>{meta.message}</span><span className="text-slate-500">{meta.progress ?? 0}%</span></div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-slate-900 transition-all" style={{ width: `${meta.progress ?? 2}%` }} /></div>
          <p className="mt-2 text-xs text-slate-500">Images are created on this computer; on the CPU each takes about 1–2 minutes. You can leave this page - the work continues.</p>
        </Card>
      )}
      {meta.status === "failed" && <div className="mb-6"><Alert tone="error" title="The document could not be created">{meta.message}</Alert></div>}

      {meta.status === "done" && (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <Card title="Preview">
            <iframe title="Branded PDF" src={brandDocFileUrl(id, meta.pdf, false, v)} className="h-[78vh] w-full rounded-lg border border-slate-200" />
            <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
              {meta.pages.map((p, i) => (
                <a key={p} href={`${brandDocFileUrl(id, meta.pdf, false, v)}#page=${i + 1}`} target="_blank" rel="noreferrer" className="shrink-0">
                  <img src={brandDocFileUrl(id, p, false, v)} alt={`Page ${i + 1}`} className="h-28 rounded border border-slate-200 hover:ring-2 hover:ring-slate-400" />
                </a>
              ))}
            </div>
          </Card>
          <div className="space-y-6">
            {r && (
              <Card title="Check">
                <ul className="space-y-2 text-sm">
                  <li className="flex items-center gap-2">{cov >= 98 ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Info className="h-4 w-4 text-amber-600" />}
                    {cov}% of the {r.length && r.length.mode !== "full" && r.length.mode !== "kept" ? "fitted text's" : "document's"} {r.fidelity.source_words} words are in the PDF</li>
                  {r.fidelity.missing_sample.length > 0 && cov < 99.5 && <li className="text-xs text-slate-500">Not found: {r.fidelity.missing_sample.join(", ")}</li>}
                  <li>{r.pages} pages · {r.sections} sections{r.conclusion ? ` · closing card: ${r.conclusion}` : ""}</li>
                  {r.length && r.length.mode !== "full" && r.length.mode !== "kept" && (
                    <li>{r.length.mode === "expanded" ? "Expanded" : "Condensed"} from {r.length.source_words.toLocaleString()} to {r.length.words.toLocaleString()} words
                      ({r.length.method === "local AI" ? "rewritten by the local AI; every number checked against the source" : "key sentences of the source"})</li>
                  )}
                  {r.authors.length > 0 && <li>Authors on the back cover: {r.authors.join(", ")}</li>}
                  <li>Type: {r.font.using_reference ? r.font.family : `${r.font.fallback} (in place of ${r.font.family})`}</li>
                </ul>
                {r.notes.length > 0 && <div className="mt-3 space-y-2">{r.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}</div>}
              </Card>
            )}
            <Card title="Images" actions={<Button size="sm" variant="secondary" loading={busy} icon={<Shuffle className="h-3.5 w-3.5" />}
              onClick={() => rerun({ seed: (meta.options.seed ?? 7) + 11 })}>New images</Button>}>
              {meta.images.length === 0 ? <p className="text-sm text-slate-500">No images for this document.</p> : (
                <ul className="space-y-3">
                  {meta.images.map((im) => (
                    <li key={im.key} className="flex gap-3">
                      <img src={brandDocFileUrl(id, im.file, false, v)} alt="" className="h-20 w-28 shrink-0 rounded object-cover" />
                      <div className="min-w-0 text-xs">
                        <div className="flex items-center gap-1.5 text-sm font-medium"><ImageIcon className="h-3.5 w-3.5" /> {im.section}</div>
                        {im.generated ? <Badge tone="green">created for this content</Badge> : <Badge tone="amber">brand artwork (no image model)</Badge>}
                        <p className="mt-1 line-clamp-3 text-slate-500" title={im.prompt}>{im.prompt}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Change and create again">
              <div className="space-y-3">
                <Field label="Template">
                  <select className={inputCls} value={tpl} onChange={(e) => setTpl(e.target.value)}>
                    {templates.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </Field>
                <Field label="Title"><input className={inputCls} value={title} placeholder={meta.title} onChange={(e) => setTitle(e.target.value)} /></Field>
                <Field label="Cover label"><input className={inputCls} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
                <Field label="Image pages">
                  <select className={inputCls} value={images} onChange={(e) => setImages(Number(e.target.value))}>
                    <option value={-1}>Automatic (1–3)</option>
                    {[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </Field>
                <Button className="w-full" variant="secondary" loading={busy} icon={<RefreshCw className="h-4 w-4" />} onClick={() => rerun()}>Create again</Button>
                <p className="text-xs text-slate-500">Images already created for the same text are reused, so only new ones take time.</p>
              </div>
            </Card>
          </div>
        </div>
      )}
      {error && <div className="mt-4"><Alert tone="error">{error}</Alert></div>}
    </>
  );
}
