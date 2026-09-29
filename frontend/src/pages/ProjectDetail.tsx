import { ArrowLeft, Download, FileJson, Film, Image as ImageIcon, Link2, MoreHorizontal, Pencil, Presentation as PresIcon, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { JobProgress } from "../components/JobProgress";
import { ImagesPanel, PlanPanel, PresentationPanel, RegenerateDialog, SourcesPanel } from "../components/OutputPanels";
import { VideoEditor } from "../components/VideoEditor";
import { Presenter } from "../components/Presenter";
import { SlideEditor } from "../components/SlideEditor";
import { Alert, Badge, Button, Card, EmptyState, Spinner, Tabs } from "../components/ui";
import { isActive, useAsync, useJob } from "../hooks/useAsync";
import { api, fileUrl } from "../services/api";
import type { ContentPlan, Job, Slide, SourceMapping } from "../types";
import { bytes, pad2, timeAgo } from "../utils/format";
import { StatusBadge } from "./Dashboard";
import { DeleteDialog, RenameDialog } from "./Projects";

type Tab = "presentation" | "images" | "video" | "sources" | "plan" | "files";

export function ProjectDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const project = useAsync(() => api.project(id), [id]);
  const [plan, setPlan] = useState<ContentPlan | null>(null);
  const [mapping, setMapping] = useState<SourceMapping | null>(null);
  const [tab, setTab] = useState<Tab>("presentation");
  const [jobId, setJobId] = useState<string | null>(null);
  const [presenting, setPresenting] = useState<number | null>(null);
  const [editing, setEditing] = useState<Slide | null>(null);
  const [regen, setRegen] = useState<Slide | null>(null);
  const [sourceFocus, setSourceFocus] = useState<number | undefined>();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [menu, setMenu] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const layouts = useAsync(() => api.layouts(id), [id]);

  const p = project.data;
  const loadPlan = useCallback(async () => {
    try { setPlan(await api.plan(id)); } catch { setPlan(null); }
    try { setMapping(await api.sources(id)); } catch { setMapping(null); }
  }, [id]);

  useEffect(() => { loadPlan(); }, [loadPlan]);
  useEffect(() => { if (p?.last_job && isActive(p.last_job)) setJobId(p.last_job.id); }, [p?.last_job]);

  const job = useJob(jobId, async () => { await project.reload(); await loadPlan(); });
  const shownJob: Job | null = job ?? (p?.last_job && !plan ? p.last_job : null);
  const busy = isActive(job);
  const version = useMemo(() => `${plan?.version ?? 0}-${p?.updated_at ?? ""}`, [plan?.version, p?.updated_at]);
  const outputs = p?.outputs ?? [];

  const run = async (fn: () => Promise<Job | { job: Job }>) => {
    setError(null);
    try {
      const r = await fn();
      setJobId("job" in r ? r.job.id : r.id);
    } catch (e) { setError((e as Error).message); }
  };

  if (project.loading && !p) return <Spinner label="Loading project…" />;
  if (!p) return <EmptyState title="Project not found" action={<Link to="/projects"><Button>Back to projects</Button></Link>} />;

  const slideImages = (plan?.slides ?? []).map((s) => fileUrl(p.id, `slides/slide_${pad2(s.slide_number)}.png`, { v: version }));
  const reviewCount = plan?.slides.filter((s) => s.needs_review).length ?? 0;

  return (
    <>
      <div className="mb-6">
        <Link to="/projects" className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"><ArrowLeft className="h-3.5 w-3.5" /> Projects</Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <h1 className="truncate text-2xl font-semibold tracking-tight">{p.name}</h1>
              <StatusBadge p={{ ...p, last_job: job ?? p.last_job }} />
            </div>
            <p className="mt-1 text-sm text-slate-500">{(p.sources?.length ? p.sources.map((x) => x.filename).join(", ") : p.document?.filename)} · brand: {p.brand_id} · updated {timeAgo(p.updated_at)}</p>
          </div>
          <div className="relative flex items-center gap-2">
            {plan && <Button icon={<PresIcon className="h-4 w-4" />} onClick={() => setPresenting(0)} disabled={!slideImages.length}>Present</Button>}
            {outputs.length > 0 && <a href={`/api/projects/${p.id}/download/all`}><Button variant="secondary" icon={<Download className="h-4 w-4" />}>Download all</Button></a>}
            <Button variant="secondary" onClick={() => setMenu(!menu)} aria-label="More"><MoreHorizontal className="h-4 w-4" /></Button>
            {menu && (
              <div className="absolute right-0 top-11 z-20 w-60 rounded-xl border border-slate-200 bg-white p-1 shadow-lg" onMouseLeave={() => setMenu(false)}>
                {[
                  { label: "Regenerate everything", icon: RefreshCw, act: () => run(() => api.generate(p.id, "full")), disabled: busy },
                  { label: "Re-render outputs (same content)", icon: RefreshCw, act: () => run(() => api.generate(p.id, "render")), disabled: busy || !plan },
                  { label: "Regenerate video", icon: Film, act: () => run(() => api.generate(p.id, "video")), disabled: busy || !plan },
                  { label: "Rename", icon: Pencil, act: () => setRenaming(true) },
                  { label: "Delete project", icon: Trash2, act: () => setDeleting(true), danger: true },
                ].map((m) => (
                  <button key={m.label} disabled={m.disabled} onClick={() => { setMenu(false); m.act(); }}
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm disabled:opacity-40 ${m.danger ? "text-red-600 hover:bg-red-50" : "hover:bg-slate-50"}`}>
                    <m.icon className="h-4 w-4" /> {m.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {error && <div className="mb-4"><Alert tone="error">{error}</Alert></div>}
      {shownJob && shownJob.id !== dismissed && (isActive(shownJob) || !plan || (job && !isActive(job) && (job.warnings.length > 0 || job.status === "failed"))) && (
        <div className="mb-6"><JobProgress job={shownJob} onCancel={() => api.cancelJob(shownJob.id)} onDismiss={plan ? () => setDismissed(shownJob.id) : undefined} /></div>
      )}

      {!plan ? (
        !shownJob && <EmptyState title="Nothing generated yet" action={<Button onClick={() => run(() => api.generate(p.id, "full"))}>Generate</Button>} />
      ) : (
        <>
          {reviewCount > 0 && (
            <div className="mb-4"><Alert tone="warning" title={`${reviewCount} slide(s) need review`}>
              Some statements have low confidence against the source. Open the slide and use <b>View sources</b> or <b>Edit content</b> to confirm them.
            </Alert></div>
          )}
          <Tabs<Tab> value={tab} onChange={setTab} tabs={[
            { id: "presentation", label: "Presentation", icon: <PresIcon className="h-4 w-4" /> },
            { id: "images", label: "Images", icon: <ImageIcon className="h-4 w-4" />, badge: <Badge>{outputs.filter((o) => o.kind === "image" && o.path.endsWith(".png")).length}</Badge> },
            { id: "video", label: "Video editor", icon: <Film className="h-4 w-4" /> },
            { id: "sources", label: "Sources", icon: <Link2 className="h-4 w-4" /> },
            { id: "plan", label: "Content plan", icon: <FileJson className="h-4 w-4" /> },
            { id: "files", label: "Files", icon: <Download className="h-4 w-4" /> },
          ]} />
          <div className="mt-6">
            {tab === "presentation" && (
              <PresentationPanel project={p} plan={plan} outputs={outputs} version={version} busy={busy} onPresent={setPresenting}
                onEdit={setEditing} onRegenerate={setRegen} onSources={(s) => { setSourceFocus(s.slide_number); setTab("sources"); }} />
            )}
            {tab === "images" && <ImagesPanel project={p} outputs={outputs} version={version} />}
            {tab === "video" && <VideoEditor project={p} outputs={outputs} version={version} busy={busy} onJob={setJobId} />}
            {tab === "sources" && <SourcesPanel mapping={mapping} plan={plan} focus={sourceFocus} />}
            {tab === "plan" && <PlanPanel project={p} plan={plan} />}
            {tab === "files" && (
              <Card title="All generated files" actions={<a href={`/api/projects/${p.id}/download/all`}><Button size="sm" icon={<Download className="h-3.5 w-3.5" />}>Download all (.zip)</Button></a>}>
                <ul className="divide-y divide-slate-100">
                  {outputs.map((o) => (
                    <li key={o.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span className="truncate font-mono text-xs text-slate-700">{o.path}</span>
                      <span className="flex shrink-0 items-center gap-3 text-xs text-slate-500">{bytes(o.size)}
                        <a className="font-medium text-slate-800 hover:underline" href={fileUrl(p.id, o.path, { download: true })}>Download</a></span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </>
      )}

      {presenting !== null && slideImages.length > 0 && (
        <Presenter images={slideImages} start={presenting} notes={(plan?.slides ?? []).map((s) => s.narration)} onClose={() => setPresenting(null)} />
      )}
      {editing && (
        <SlideEditor slide={editing} layouts={(layouts.data ?? []).map((l) => l.id)} onClose={() => setEditing(null)}
          onSave={async (edited) => { const r = await api.editSlide(p.id, editing.slide_number, edited as Record<string, unknown>); setJobId(r.job.id); await loadPlan(); }} />
      )}
      {regen && (
        <RegenerateDialog slide={regen} layouts={(layouts.data ?? []).map((l) => l.id)} onClose={() => setRegen(null)}
          onSubmit={async (layout, guidance) => { const j = await api.regenerateSlide(p.id, regen.slide_number, { layout, guidance }); setJobId(j.id); }} />
      )}
      {renaming && <RenameDialog project={p} onClose={() => setRenaming(false)} onSaved={project.reload} />}
      {deleting && <DeleteDialog project={p} onClose={() => setDeleting(false)} onDeleted={() => nav("/projects")} />}
    </>
  );
}
