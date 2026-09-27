import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { Claim, Column, KPI, Slide, Step } from "../types";
import { LAYOUT_LABELS } from "../utils/format";
import { Alert, Button, ConfidenceBadge, Field, Modal, inputCls } from "./ui";

const ACCENT_ROLES = ["accent", "primary", "secondary"];

function ClaimList({ items, onChange, label }: { items: Claim[]; onChange: (c: Claim[]) => void; label: string }) {
  return (
    <Field label={label}>
      <div className="space-y-2">
        {items.map((c, i) => (
          <div key={i} className="flex items-start gap-2">
            <textarea className={`${inputCls} min-h-[2.5rem]`} rows={2} value={c.text}
              onChange={(e) => onChange(items.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
            <div className="flex flex-col items-end gap-1 pt-1">
              <ConfidenceBadge status={c.status} confidence={c.confidence} />
              <button className="rounded p-1 text-slate-400 hover:text-red-600" onClick={() => onChange(items.filter((_, j) => j !== i))} title="Remove"><Trash2 className="h-4 w-4" /></button>
            </div>
          </div>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />}
          onClick={() => onChange([...items, { text: "", sources: [], confidence: 0, status: "user_edited" }])}>Add point</Button>
      </div>
    </Field>
  );
}

/** Human review: edits keep existing source links; new/changed text is re-checked and marked as edited. */
export function SlideEditor({ slide, layouts, onClose, onSave }: {
  slide: Slide; layouts: string[]; onClose: () => void; onSave: (edited: Partial<Slide>) => Promise<void>;
}) {
  const [s, setS] = useState<Slide>(() => JSON.parse(JSON.stringify(slide)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = <K extends keyof Slide>(k: K, v: Slide[K]) => setS((x) => ({ ...x, [k]: v }));

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const clean = (c: Claim[]) => c.filter((x) => x.text.trim());
      await onSave({
        title: s.title, subtitle: s.subtitle, layout: s.layout, narration: s.narration, accent_role: s.accent_role,
        key_points: clean(s.key_points), columns: s.columns.map((c) => ({ ...c, points: clean(c.points) })),
        steps: s.steps.filter((x) => x.title.trim() || x.description.trim()), kpis: s.kpis.filter((k) => k.value.trim()),
        quote: s.quote && s.quote.text.trim() ? s.quote : null,
      });
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open wide onClose={onClose} title={`Edit slide ${slide.slide_number}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={save} loading={busy}>Save & update outputs</Button></>}>
      <div className="space-y-5">
        <Alert tone="info">Source references are kept. Text you change is re-checked against the document and marked as edited in the source mapping.</Alert>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="md:col-span-2"><Field label="Title"><input className={inputCls} value={s.title} onChange={(e) => set("title", e.target.value)} /></Field></div>
          <Field label="Layout">
            <select className={inputCls} value={s.layout} onChange={(e) => set("layout", e.target.value)}>
              {layouts.map((l) => <option key={l} value={l}>{LAYOUT_LABELS[l] ?? l}</option>)}
            </select>
          </Field>
        </div>
        {(s.layout === "cover" || s.layout === "section_divider" || s.subtitle) && (
          <Field label="Subtitle"><input className={inputCls} value={s.subtitle} onChange={(e) => set("subtitle", e.target.value)} /></Field>
        )}
        {(s.key_points.length > 0 || ["executive_summary", "key_findings", "conclusion", "text_image", "image_text", "chart", "table", "architecture", "kpi", "research_results"].includes(s.layout)) &&
          s.layout !== "references" && <ClaimList label="Key points" items={s.key_points} onChange={(v) => set("key_points", v)} />}

        {s.columns.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {s.columns.map((c: Column, ci) => (
              <div key={ci} className="rounded-lg border border-slate-200 p-3">
                <Field label={`Column ${ci + 1} heading`}>
                  <input className={inputCls} value={c.heading} onChange={(e) => set("columns", s.columns.map((x, j) => (j === ci ? { ...x, heading: e.target.value } : x)))} />
                </Field>
                <div className="mt-3"><ClaimList label="Points" items={c.points} onChange={(v) => set("columns", s.columns.map((x, j) => (j === ci ? { ...x, points: v } : x)))} /></div>
              </div>
            ))}
          </div>
        )}

        {(s.steps.length > 0 || ["process", "workflow", "timeline", "research_methodology"].includes(s.layout)) && (
          <Field label="Steps">
            <div className="space-y-2">
              {s.steps.map((st: Step, i) => (
                <div key={i} className="grid grid-cols-[10rem_1fr_auto] items-start gap-2">
                  <input className={inputCls} value={st.title} onChange={(e) => set("steps", s.steps.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                  <textarea className={inputCls} rows={2} value={st.description} onChange={(e) => set("steps", s.steps.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
                  <div className="flex flex-col items-end gap-1 pt-1">
                    <ConfidenceBadge status={st.status} confidence={st.confidence} />
                    <button className="rounded p-1 text-slate-400 hover:text-red-600" onClick={() => set("steps", s.steps.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
              ))}
              <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />}
                onClick={() => set("steps", [...s.steps, { title: "", description: "", sources: [], confidence: 0, status: "user_edited" }])}>Add step</Button>
            </div>
          </Field>
        )}

        {(s.kpis.length > 0 || s.layout === "kpi") && (
          <Field label="Metrics (copy values exactly from the source)">
            <div className="space-y-2">
              {s.kpis.map((k: KPI, i) => (
                <div key={i} className="grid grid-cols-[8rem_1fr_auto] items-center gap-2">
                  <input className={inputCls} value={k.value} onChange={(e) => set("kpis", s.kpis.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                  <input className={inputCls} value={k.label} onChange={(e) => set("kpis", s.kpis.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                  <div className="flex items-center gap-1"><ConfidenceBadge status={k.status} confidence={k.confidence} />
                    <button className="rounded p-1 text-slate-400 hover:text-red-600" onClick={() => set("kpis", s.kpis.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button></div>
                </div>
              ))}
              <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />}
                onClick={() => set("kpis", [...s.kpis, { value: "", label: "", sources: [], confidence: 0, status: "user_edited" }])}>Add metric</Button>
            </div>
          </Field>
        )}

        {(s.quote || s.layout === "quote") && (
          <Field label="Quote">
            <textarea className={inputCls} rows={2} value={s.quote?.text ?? ""}
              onChange={(e) => set("quote", { ...(s.quote ?? { sources: [], confidence: 0, status: "user_edited" }), text: e.target.value })} />
          </Field>
        )}

        <div className="grid gap-4 md:grid-cols-3">
          <div className="md:col-span-2">
            <Field label="Narration (video voice-over)"><textarea className={inputCls} rows={4} value={s.narration} onChange={(e) => set("narration", e.target.value)} /></Field>
          </div>
          <Field label="Accent colour" hint="Chosen from the brand palette only.">
            <select className={inputCls} value={s.accent_role} onChange={(e) => set("accent_role", e.target.value)}>
              {ACCENT_ROLES.map((r) => <option key={r} value={r}>Brand {r}</option>)}
            </select>
          </Field>
        </div>
        {err && <Alert tone="error">{err}</Alert>}
      </div>
    </Modal>
  );
}
