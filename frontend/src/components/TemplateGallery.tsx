import { Check, LayoutTemplate } from "lucide-react";
import { useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { TemplateItem } from "../types";
import { Badge, Spinner } from "./ui";

function TemplateCard({ t, selected, onSelect }: { t: TemplateItem; selected: boolean; onSelect: () => void }) {
  const [shown, setShown] = useState(0);
  return (
    <button onClick={onSelect} aria-pressed={selected}
      className={`group overflow-hidden rounded-xl border-2 text-left transition ${selected ? "border-slate-900 ring-2 ring-slate-900/10" : "border-slate-200 hover:border-slate-400"}`}>
      <div className="relative aspect-video bg-slate-100">
        <img src={t.previews[shown]} alt={`${t.name} preview`} loading="lazy" className="h-full w-full object-cover" />
        {selected && <span className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-white"><Check className="h-4 w-4" /></span>}
      </div>
      <div className="flex gap-1 px-3 pt-2">
        {t.previews.map((p, i) => (
          <span key={p} role="presentation" onMouseEnter={() => setShown(i)} onClick={(e) => { e.stopPropagation(); setShown(i); }}
            className={`h-8 flex-1 cursor-pointer overflow-hidden rounded border ${shown === i ? "border-slate-700" : "border-slate-200"}`}>
            <img src={p} alt="" loading="lazy" className="h-full w-full object-cover" />
          </span>
        ))}
      </div>
      <div className="p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-semibold">{t.name}</span>
          <Badge tone={t.kind === "pptx" ? "blue" : "slate"}>{t.kind === "pptx" ? "Uploaded" : "Preset"}</Badge>
        </div>
        <p className="mt-1 line-clamp-2 text-xs text-slate-500">{t.description}</p>
      </div>
    </button>
  );
}

/** Pick a design preset or an uploaded PowerPoint template ("" = the brand's default look). */
export function TemplateGallery({ brandId, value, onChange }: { brandId: string; value: string; onChange: (id: string) => void }) {
  const gallery = useAsync(() => api.templateGallery(brandId), [brandId]);
  if (gallery.loading && !gallery.data) return <Spinner label="Rendering template previews…" />;
  if (gallery.error) return <p className="text-sm text-red-700">{gallery.error}</p>;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <button onClick={() => onChange("")} aria-pressed={value === ""}
        className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 p-6 text-center transition ${value === "" ? "border-slate-900 ring-2 ring-slate-900/10" : "border-slate-200 hover:border-slate-400"}`}>
        <LayoutTemplate className="h-8 w-8 text-slate-400" />
        <span className="text-sm font-semibold">Brand default</span>
        <span className="text-xs text-slate-500">The brand's own settings. For Zensar this is the Zensar Experience look.</span>
      </button>
      {(gallery.data ?? []).map((t) => <TemplateCard key={t.id} t={t} selected={value === t.id} onSelect={() => onChange(t.id)} />)}
    </div>
  );
}
