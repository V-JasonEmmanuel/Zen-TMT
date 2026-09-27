import { FolderOpen, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";
import type { Project } from "../types";
import { timeAgo } from "../utils/format";
import { Alert, Button, EmptyState, Modal, Spinner, inputCls } from "../components/ui";
import { StatusBadge } from "./Dashboard";

export function RenameDialog({ project, onClose, onSaved }: { project: Project | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(project?.name ?? "");
  const [err, setErr] = useState<string | null>(null);
  if (!project) return null;
  return (
    <Modal open onClose={onClose} title="Rename project"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={async () => { try { await api.updateProject(project.id, { name }); onSaved(); onClose(); } catch (e) { setErr((e as Error).message); } }}
          disabled={!name.trim()}>Save</Button></>}>
      <input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
      {err && <div className="mt-3"><Alert tone="error">{err}</Alert></div>}
    </Modal>
  );
}

export function DeleteDialog({ project, onClose, onDeleted }: { project: Project | null; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!project) return null;
  return (
    <Modal open onClose={onClose} title="Delete project"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="danger" loading={busy} onClick={async () => {
          setBusy(true);
          try { await api.deleteProject(project.id); onDeleted(); onClose(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
        }}>Delete permanently</Button></>}>
      <p className="text-sm text-slate-600">This deletes <b>{project.name}</b> and all of its generated files (presentation, images, video, source mapping). The uploaded document is kept.</p>
      {err && <div className="mt-3"><Alert tone="error">{err}</Alert></div>}
    </Modal>
  );
}

export function Projects() {
  const { data, loading, reload } = useAsync(() => api.projects(), []);
  const [renaming, setRenaming] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const nav = useNavigate();
  return (
    <>
      <PageHeader title="Projects" subtitle="Open a project to present, review, edit or download its outputs."
        actions={<Link to="/new"><Button icon={<Plus className="h-4 w-4" />}>New project</Button></Link>} />
      {loading ? <Spinner label="Loading projects…" /> : !data?.length ? (
        <EmptyState icon={<FolderOpen className="h-8 w-8" />} title="No projects yet" action={<Link to="/new"><Button>New project</Button></Link>} />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-3">Project</th><th className="px-4 py-3">Document</th><th className="px-4 py-3">Outputs</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Updated</th><th /></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((p) => (
                <tr key={p.id} className="cursor-pointer hover:bg-slate-50" onClick={() => nav(`/projects/${p.id}`)}>
                  <td className="px-4 py-3 font-medium text-slate-900">{p.name}</td>
                  <td className="max-w-[16rem] truncate px-4 py-3 text-slate-600">{p.document?.filename}</td>
                  <td className="px-4 py-3 text-xs uppercase text-slate-500">{p.output_formats.join(" · ")}</td>
                  <td className="px-4 py-3"><StatusBadge p={p} /></td>
                  <td className="px-4 py-3 text-slate-500">{timeAgo(p.updated_at)}</td>
                  <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <button className="rounded p-1.5 text-slate-500 hover:bg-slate-100" title="Rename" onClick={() => setRenaming(p)}><Pencil className="h-4 w-4" /></button>
                    <button className="rounded p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600" title="Delete" onClick={() => setDeleting(p)}><Trash2 className="h-4 w-4" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {renaming && <RenameDialog project={renaming} onClose={() => setRenaming(null)} onSaved={reload} />}
      {deleting && <DeleteDialog project={deleting} onClose={() => setDeleting(null)} onDeleted={reload} />}
    </>
  );
}
