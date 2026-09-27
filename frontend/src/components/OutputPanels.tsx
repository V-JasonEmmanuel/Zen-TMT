import { AlertTriangle, ChevronLeft, ChevronRight, Download, Expand, FileJson, Film, Image as ImageIcon, Link2, Maximize2, Pencil, RefreshCw, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fileUrl } from "../services/api";
import type { ContentPlan, OutputFile, Project, Slide, SourceMapping } from "../types";
import { LAYOUT_LABELS, bytes, humanize, pad2 } from "../utils/format";
import { Alert, Badge, Button, ConfidenceBadge, EmptyState, Modal, inputCls } from "./ui";

// ------------------------------------------------------------------ presentation
export function PresentationPanel({ project, plan, outputs, version, busy, onPresent, onEdit, onRegenerate, onSources }: {
  project: Project; plan: ContentPlan; outputs: OutputFile[]; version: string; busy: boolean;
  onPresent: (i: number) => void; onEdit: (s: Slide) => void; onRegenerate: (s: Slide) => void; onSources: (s: Slide) => void;
}) {
  const [i, setI] = useState(0);
  const slides = plan.slides;
  const cur = slides[Math.min(i, slides.length - 1)];
  const img = (n: number) => fileUrl(project.id, `slides/slide_${pad2(n)}.png`, { v: version });
  const has = (k: string) => outputs.some((o) => o.kind === k);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,select")) return;
      if (e.key === "ArrowRight") setI((x) => Math.min(slides.length - 1, x + 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [slides.length]);

  if (!has("slide_image")) return <EmptyState title="Slide previews are not available yet" />;
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0">
        <div className="group relative overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <img src={img(cur.slide_number)} alt={`Slide ${cur.slide_number}`} className="aspect-video w-full object-contain" />
          <button onClick={() => onPresent(i)} className="absolute right-3 top-3 rounded-lg bg-slate-900/70 p-2 text-white opacity-0 transition group-hover:opacity-100" title="Present from this slide">
            <Maximize2 className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => setI(Math.max(0, i - 1))} disabled={i === 0} aria-label="Previous"><ChevronLeft className="h-4 w-4" /></Button>
            <span className="text-sm tabular-nums text-slate-600">Slide {i + 1} of {slides.length}</span>
            <Button variant="secondary" size="sm" onClick={() => setI(Math.min(slides.length - 1, i + 1))} disabled={i === slides.length - 1} aria-label="Next"><ChevronRight className="h-4 w-4" /></Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={<Expand className="h-3.5 w-3.5" />} onClick={() => onPresent(0)}>Present</Button>
            {has("pptx") && <a href={fileUrl(project.id, "presentation/presentation.pptx", { download: true })}><Button size="sm" variant="secondary" icon={<Download className="h-3.5 w-3.5" />}>PPTX</Button></a>}
            {has("pdf") && <a href={fileUrl(project.id, "presentation/presentation.pdf", { download: true })}><Button size="sm" variant="secondary" icon={<Download className="h-3.5 w-3.5" />}>PDF</Button></a>}
          </div>
        </div>
        <div className="scrollbar-thin mt-4 flex gap-3 overflow-x-auto pb-2">
          {slides.map((s, j) => (
            <button key={s.slide_number} onClick={() => setI(j)}
              className={`relative w-36 shrink-0 overflow-hidden rounded-lg border-2 bg-white ${j === i ? "border-slate-900" : "border-transparent hover:border-slate-300"}`}>
              <img src={img(s.slide_number)} alt="" className="aspect-video w-full object-cover" loading="lazy" />
              <span className="absolute left-1 top-1 rounded bg-slate-900/70 px-1.5 text-[10px] text-white">{s.slide_number}</span>
              {s.needs_review && <AlertTriangle className="absolute right-1 top-1 h-4 w-4 text-amber-500" />}
            </button>
          ))}
        </div>
      </div>

      <aside className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Slide {cur.slide_number}</div>
          <div className="mt-1 font-semibold">{cur.title}</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge>{LAYOUT_LABELS[cur.layout] ?? cur.layout}</Badge>
            {cur.needs_review && <Badge tone="amber">Needs review</Badge>}
            {cur.edited && <Badge tone="blue">Edited</Badge>}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Button size="sm" variant="secondary" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => onEdit(cur)} disabled={busy}>Edit content</Button>
            <Button size="sm" variant="secondary" icon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => onRegenerate(cur)} disabled={busy || cur.layout === "cover" || cur.layout === "references"}>Regenerate</Button>
            <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => onRegenerate({ ...cur, layout: "__choose__" })} disabled={busy || cur.layout === "cover"}>Change layout</Button>
            <Button size="sm" variant="secondary" icon={<Link2 className="h-3.5 w-3.5" />} onClick={() => onSources(cur)}>View sources</Button>
          </div>
        </div>
        {cur.warnings.length > 0 && <Alert tone="warning">{cur.warnings.join(" ")}</Alert>}
        {cur.narration && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Narration</div>
            <p className="text-slate-700">{cur.narration}</p>
          </div>
        )}
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Sources on this slide</div>
          {cur.sources.length === 0 ? <p className="text-slate-500">No document content on this slide.</p> : (
            <ul className="space-y-1">{cur.sources.slice(0, 6).map((r) => (
              <li key={r.chunk_id} className="text-xs text-slate-600">p.{r.page}{r.page_end && r.page_end !== r.page ? `–${r.page_end}` : ""} · {r.section}{r.table ? ` · Table ${r.table}` : ""}</li>
            ))}</ul>
          )}
        </div>
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ images
export function ImagesPanel({ project, outputs, version }: { project: Project; outputs: OutputFile[]; version: string }) {
  const pngs = outputs.filter((o) => o.kind === "image" && o.path.endsWith(".png"));
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    if (open === null) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
      if (e.key === "ArrowRight") setOpen((x) => (x === null ? x : Math.min(pngs.length - 1, x + 1)));
      if (e.key === "ArrowLeft") setOpen((x) => (x === null ? x : Math.max(0, x - 1)));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, pngs.length]);

  if (!pngs.length) return <EmptyState icon={<ImageIcon className="h-8 w-8" />} title="No visuals yet">Enable “Visuals” in the project outputs and regenerate.</EmptyState>;
  const svgFor = (p: string) => p.replace(/\.png$/, ".svg");
  return (
    <>
      <div className="mb-4 flex justify-end">
        <a href={`/api/projects/${project.id}/download/images`}><Button variant="secondary" size="sm" icon={<Download className="h-3.5 w-3.5" />}>Download all images</Button></a>
      </div>
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {pngs.map((o, i) => (
          <figure key={o.path} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <button className="block w-full" onClick={() => setOpen(i)} title="Open full screen">
              <img src={fileUrl(project.id, o.path, { v: version })} alt={o.path} className="aspect-video w-full object-contain" loading="lazy" />
            </button>
            <figcaption className="flex items-center justify-between gap-2 border-t border-slate-100 px-3 py-2 text-xs">
              <span className="text-slate-600">Visual {o.path.match(/\d+/)?.[0]} · {bytes(o.size)}</span>
              <span className="flex gap-1">
                <a className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-50" href={fileUrl(project.id, o.path, { download: true })}>PNG</a>
                <a className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-50" href={fileUrl(project.id, o.path, { download: true, format: "jpg" })}>JPG</a>
                {outputs.some((x) => x.path === svgFor(o.path)) && <a className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-50" href={fileUrl(project.id, svgFor(o.path), { download: true })}>SVG</a>}
              </span>
            </figcaption>
          </figure>
        ))}
      </div>
      {open !== null && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 p-6" onClick={() => setOpen(null)}>
          <img src={fileUrl(project.id, pngs[open].path, { v: version })} alt="" className="max-h-full max-w-full object-contain" onClick={(e) => e.stopPropagation()} />
          <button className="absolute right-5 top-5 rounded-full bg-white/10 p-2 text-white hover:bg-white/20" onClick={() => setOpen(null)} aria-label="Close"><X className="h-5 w-5" /></button>
          <button className="absolute left-5 rounded-full bg-white/10 p-3 text-white hover:bg-white/20" onClick={(e) => { e.stopPropagation(); setOpen(Math.max(0, open - 1)); }} aria-label="Previous"><ChevronLeft className="h-6 w-6" /></button>
          <button className="absolute right-5 rounded-full bg-white/10 p-3 text-white hover:bg-white/20" onClick={(e) => { e.stopPropagation(); setOpen(Math.min(pngs.length - 1, open + 1)); }} aria-label="Next"><ChevronRight className="h-6 w-6" /></button>
          <a href={fileUrl(project.id, pngs[open].path, { download: true })} onClick={(e) => e.stopPropagation()}
            className="absolute bottom-5 right-5 flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-medium text-slate-900"><Download className="h-4 w-4" /> Download</a>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ video
export function VideoPanel({ project, outputs, version, busy, onGenerate }: { project: Project; outputs: OutputFile[]; version: string; busy: boolean; onGenerate: () => void }) {
  const video = outputs.find((o) => o.kind === "video");
  const vtt = outputs.find((o) => o.path.endsWith(".vtt"));
  if (!video) {
    return (
      <EmptyState icon={<Film className="h-8 w-8" />} title="No video yet"
        action={<Button onClick={onGenerate} loading={busy} icon={<Film className="h-4 w-4" />}>Generate video</Button>}>
        Create a narrated, presentation-style MP4 from the current slides. This runs locally and can take a few minutes.
      </EmptyState>
    );
  }
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl bg-black shadow-sm">
        <video key={version} controls preload="metadata" className="aspect-video w-full" crossOrigin="anonymous">
          <source src={fileUrl(project.id, video.path, { v: version })} type="video/mp4" />
          {vtt && <track kind="subtitles" srcLang="en" label="English" src={fileUrl(project.id, vtt.path, { v: version })} default />}
        </video>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-slate-500">Use the player controls to play, pause, seek, change volume, toggle subtitles (CC) and go full screen.</p>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onGenerate} loading={busy}>Regenerate video</Button>
          <a href={fileUrl(project.id, video.path, { download: true })}><Button size="sm" icon={<Download className="h-3.5 w-3.5" />}>Download MP4 · {bytes(video.size)}</Button></a>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ sources
export function SourcesPanel({ mapping, plan, focus }: { mapping: SourceMapping | null; plan: ContentPlan; focus?: number }) {
  const [slide, setSlide] = useState<number | "all">(focus ?? "all");
  useEffect(() => { if (focus) setSlide(focus); }, [focus]);
  if (!mapping) return <EmptyState title="No source mapping yet" />;
  const nums = plan.slides.map((s) => s.slide_number).filter((n) => slide === "all" || n === slide);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-600">Every statement is linked to the page and section of <b>{mapping.document.name}</b> it came from.</p>
        <select className={`${inputCls} w-48`} value={String(slide)} onChange={(e) => setSlide(e.target.value === "all" ? "all" : Number(e.target.value))}>
          <option value="all">All slides</option>
          {plan.slides.map((s) => <option key={s.slide_number} value={s.slide_number}>Slide {s.slide_number}: {s.title.slice(0, 30)}</option>)}
        </select>
      </div>
      <div className="space-y-4">
        {nums.map((n) => {
          const s = plan.slides.find((x) => x.slide_number === n)!;
          const claims = mapping.claims[`slide_${n}`] ?? [];
          const refs = mapping.slides[`slide_${n}`] ?? [];
          return (
            <div key={n} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
                <div className="text-sm font-semibold">Slide {n} · {s.title}</div>
                <div className="flex flex-wrap gap-1">{refs.slice(0, 5).map((r) => <Badge key={r.chunk_id}>p.{r.page} {r.section.replace(/^\d+(\.\d+)*\s+/, "")}</Badge>)}</div>
              </div>
              {claims.length === 0 ? <p className="px-4 py-3 text-sm text-slate-500">Structural slide - no factual statements.</p> : (
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-slate-100">
                    {claims.map((c, i) => (
                      <tr key={i}>
                        <td className="px-4 py-2 text-slate-700">{c.claim}</td>
                        <td className="w-48 px-4 py-2 text-xs text-slate-500">{c.page ? `Page ${c.page}` : "-"}{c.section ? ` · ${c.section.replace(/^\d+(\.\d+)*\s+/, "")}` : ""}</td>
                        <td className="w-28 px-4 py-2 text-right"><ConfidenceBadge status={c.status} confidence={c.confidence} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ plan
export function PlanPanel({ project, plan }: { project: Project; plan: ContentPlan }) {
  const text = useMemo(() => JSON.stringify(plan, null, 2), [plan]);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        {[["Plan version", `v${plan.version}`], ["Slides", plan.slides.length], ["Writing", String(plan.generator.writing_mode ?? "-")],
          ["Model", String(plan.generator.llm ?? "none (extractive)")]].map(([k, v]) => (
          <div key={String(k)} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs uppercase text-slate-500">{k}</div><div className="mt-1 font-semibold">{v}</div></div>
        ))}
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Content contract</div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="blue">{plan.contract.slide_count} slides</Badge><Badge>{humanize(plan.contract.audience)}</Badge><Badge>{humanize(plan.contract.purpose)}</Badge>
          {plan.contract.include.map((t) => <Badge key={t} tone="green">Focus: {humanize(t)}</Badge>)}
          {plan.contract.exclude.map((t) => <Badge key={t} tone="red">Exclude: {humanize(t)}</Badge>)}
        </div>
      </div>
      <div className="flex justify-end">
        <a href={fileUrl(project.id, "content/content_plan.json", { download: true })}><Button variant="secondary" size="sm" icon={<FileJson className="h-3.5 w-3.5" />}>Download content_plan.json</Button></a>
      </div>
      <pre className="scrollbar-thin max-h-[36rem] overflow-auto rounded-xl bg-slate-900 p-4 font-mono text-xs leading-relaxed text-slate-100">{text}</pre>
    </div>
  );
}

// ------------------------------------------------------------------ regenerate dialog
export function RegenerateDialog({ slide, layouts, onClose, onSubmit }: {
  slide: Slide; layouts: string[]; onClose: () => void; onSubmit: (layout: string | null, guidance: string) => Promise<void>;
}) {
  const choose = slide.layout === "__choose__";
  const [layout, setLayout] = useState<string>(choose ? "" : "");
  const [guidance, setGuidance] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onClose={onClose} title={choose ? `Change layout · slide ${slide.slide_number}` : `Regenerate slide ${slide.slide_number}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={choose && !layout} onClick={async () => { setBusy(true); try { await onSubmit(layout || null, guidance); onClose(); } finally { setBusy(false); } }}>
          {choose ? "Apply layout" : "Regenerate"}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-slate-600">Only this slide is rewritten, using the same source passages. Other slides are not changed.</p>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Layout</span>
          <select className={inputCls} value={layout} onChange={(e) => setLayout(e.target.value)}>
            <option value="">{choose ? "Choose a layout…" : "Keep current layout"}</option>
            {layouts.filter((l) => l !== "cover" && l !== "references").map((l) => <option key={l} value={l}>{LAYOUT_LABELS[l] ?? l}</option>)}
          </select>
        </label>
        {!choose && (
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Guidance (optional)</span>
            <textarea className={inputCls} rows={3} maxLength={600} value={guidance} onChange={(e) => setGuidance(e.target.value)} placeholder="e.g. Make it shorter and emphasise the accuracy improvement." />
          </label>
        )}
      </div>
    </Modal>
  );
}
