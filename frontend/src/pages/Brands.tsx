import { Palette, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Badge, Button, Field, Modal, Spinner, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api, brandAssetUrl } from "../services/api";
import { timeAgo } from "../utils/format";

export function Brands() {
  const { data, loading } = useAsync(() => api.brands(), []);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();
  return (
    <>
      <PageHeader title="Brand Manager" subtitle="Brand profiles are the source of truth for every colour, font and layout in the generated outputs."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>Create brand</Button>} />
      {loading ? <Spinner /> : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {(data ?? []).map((b) => (
            <Link key={b.id} to={`/brands/${b.id}`} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md">
              <div className="flex items-start justify-between">
                <div className="flex h-12 w-24 items-center">
                  {b.logo ? <img src={brandAssetUrl(b.id, "assets", b.logo)} alt="" className="max-h-12 max-w-24 object-contain" /> : <Palette className="h-8 w-8 text-slate-300" />}
                </div>
                <Badge tone={b.status === "configured" ? "green" : b.status === "partial" ? "amber" : "slate"}>{b.status}</Badge>
              </div>
              <h3 className="mt-3 font-semibold">{b.name}</h3>
              <p className="mt-1 line-clamp-2 text-sm text-slate-500">{b.description || "No description"}</p>
              <p className="mt-3 text-xs text-slate-400">Updated {timeAgo(b.updated_at)}</p>
            </Link>
          ))}
        </div>
      )}
      <Modal open={creating} onClose={() => setCreating(false)} title="Create brand profile"
        footer={<><Button variant="secondary" onClick={() => setCreating(false)}>Cancel</Button>
          <Button disabled={!name.trim()} onClick={async () => { try { const b = await api.createBrand(name.trim()); nav(`/brands/${b.profile.id}`); } catch (e) { setErr((e as Error).message); } }}>Create</Button></>}>
        <Field label="Brand name"><input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <p className="mt-3 text-sm text-slate-500">The new profile starts empty. Configure it from official references, templates and guidelines.</p>
        {err && <div className="mt-3"><Alert tone="error">{err}</Alert></div>}
      </Modal>
    </>
  );
}
