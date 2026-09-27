import { CheckCircle2, FileText, FolderOpen, Palette, Plus, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api, fileUrl } from "../services/api";
import type { Project } from "../types";
import { bytes, timeAgo } from "../utils/format";
import { Badge, Button, Card, EmptyState, Spinner } from "../components/ui";

export function StatusBadge({ p }: { p: Project }) {
  const s = p.last_job?.status;
  if (s === "running" || s === "queued") return <Badge tone="blue">Generating…</Badge>;
  if (p.status === "failed" || s === "failed") return <Badge tone="red">Failed</Badge>;
  if (p.status === "ready") return <Badge tone={s === "completed_with_warnings" ? "amber" : "green"}>{s === "completed_with_warnings" ? "Ready · notes" : "Ready"}</Badge>;
  return <Badge>Draft</Badge>;
}

export function ProjectCard({ p }: { p: Project }) {
  return (
    <Link to={`/projects/${p.id}`} className="group overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition hover:shadow-md">
      <div className="aspect-video bg-slate-100">
        {p.thumbnail ? (
          <img src={fileUrl(p.id, p.thumbnail, { v: p.updated_at })} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="flex h-full items-center justify-center text-slate-300"><FolderOpen className="h-10 w-10" /></div>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="line-clamp-1 text-sm font-semibold text-slate-900 group-hover:underline">{p.name}</h3>
          <StatusBadge p={p} />
        </div>
        <p className="mt-1 line-clamp-1 text-xs text-slate-500">{p.document?.filename ?? "No document"} · {timeAgo(p.updated_at)}</p>
      </div>
    </Link>
  );
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-slate-300" />}
      <span className={ok ? "text-slate-700" : "text-slate-400"}>{label}</span>
    </li>
  );
}

export function Dashboard() {
  const projects = useAsync(() => api.projects(), []);
  const docs = useAsync(() => api.documents(), []);
  const brands = useAsync(() => api.brands(), []);
  const status = useAsync(() => api.status(), []);
  const list = projects.data ?? [];

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Turn documents into on-brand presentations, visuals and videos - entirely on this computer."
        actions={<Link to="/new"><Button icon={<Plus className="h-4 w-4" />}>New project</Button></Link>} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title="Recent projects" actions={<Link to="/projects" className="text-xs font-medium text-slate-600 hover:underline">View all</Link>}>
            {projects.loading ? <Spinner label="Loading…" /> : list.length === 0 ? (
              <EmptyState icon={<FolderOpen className="h-8 w-8" />} title="No projects yet" action={<Link to="/new"><Button>Create your first project</Button></Link>}>
                Upload a report or research paper, describe the presentation you need, and generate it in the Zensar style.
              </EmptyState>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{list.slice(0, 6).map((p) => <ProjectCard key={p.id} p={p} />)}</div>
            )}
          </Card>
          <Card title="Recent documents">
            {(docs.data ?? []).length === 0 ? <p className="text-sm text-slate-500">No documents uploaded yet.</p> : (
              <ul className="divide-y divide-slate-100">
                {(docs.data ?? []).slice(0, 6).map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <span className="flex min-w-0 items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-slate-400" /><span className="truncate">{d.filename}</span></span>
                    <span className="shrink-0 text-xs text-slate-500">{d.page_count} pages · {bytes(d.size)} · {timeAgo(d.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="space-y-6">
          <Card title="System">
            {!status.data ? <Spinner /> : (
              <ul className="space-y-2">
                <Check ok={status.data.ollama.running} label="Local AI service (Ollama)" />
                <Check ok={status.data.ollama.model_ready} label={status.data.ollama.selected ? `Model: ${status.data.ollama.selected}` : "No model selected"} />
                <Check ok={status.data.embeddings.onnx_ready} label="Document understanding model" />
                <Check ok={status.data.ffmpeg.available} label="Video engine" />
                <Check ok={status.data.tts.available} label="Offline narration voices" />
                <Check ok={status.data.offline_guard} label="Offline protection" />
              </ul>
            )}
            <Link to="/settings" className="mt-4 inline-block text-xs font-medium text-slate-600 hover:underline">Open settings</Link>
          </Card>
          <Card title="Brand profiles" actions={<Link to="/brands" className="text-xs font-medium text-slate-600 hover:underline">Manage</Link>}>
            <ul className="space-y-2">
              {(brands.data ?? []).map((b) => (
                <li key={b.id}>
                  <Link to={`/brands/${b.id}`} className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50">
                    <span className="flex items-center gap-2">
                      <span className="h-4 w-4 rounded border border-slate-200" style={{ background: b.primary ?? "repeating-linear-gradient(45deg,#e2e8f0 0 3px,#fff 3px 6px)" }} />
                      {b.name}
                    </span>
                    <Badge tone={b.status === "configured" ? "green" : b.status === "partial" ? "amber" : "slate"}>{b.status}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
            {brands.data?.some((b) => b.status !== "configured") && (
              <p className="mt-3 flex items-start gap-2 text-xs text-slate-500"><Palette className="mt-0.5 h-3.5 w-3.5 shrink-0" />Add the official references, template, colours and fonts so outputs follow the brand exactly.</p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
