import { ArrowLeft, Eye, FileUp, ImagePlus, RotateCcw, Save, ScanSearch, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { FileDrop } from "../components/FileDrop";
import { Alert, Badge, Button, Card, Field, Spinner, Tabs, Toggle, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, brandAssetUrl } from "../services/api";
import type { BrandProfile, BrandView, Provenance, Suggestion } from "../types";
import { humanize } from "../utils/format";

type Tab = "overview" | "colors" | "typography" | "logo" | "layout" | "references" | "template";
const COLOR_ROLES: [string, string][] = [
  ["primary", "Primary"], ["secondary", "Secondary"], ["accent", "Accent"], ["background", "Background"],
  ["surface", "Surface (cards, panels)"], ["text_primary", "Text"], ["text_secondary", "Secondary text"],
];
const ROLE_OPTIONS = ["primary", "secondary", "accent", "surface", "background", "text_primary", "text_secondary"];

function ProvBadge({ p }: { p?: Provenance }) {
  if (!p) return <Badge>not set</Badge>;
  const src = { manual: "manual", pptx_template: "from template", reference_image: "from reference", default: "default" }[p.source];
  return <Badge tone={p.source === "manual" ? "green" : p.confidence >= 0.7 ? "blue" : "amber"} title={p.note}>{src}{p.source !== "manual" ? ` · ${Math.round(p.confidence * 100)}%` : ""}</Badge>;
}

function num(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function SuggestionTable({ items, onApply }: { items: Suggestion[]; onApply: (s: Suggestion[]) => Promise<void> }) {
  const [sel, setSel] = useState<Set<number>>(() => new Set(items.map((s, i) => (s.confidence >= 0.7 ? i : -1)).filter((i) => i >= 0)));
  const [busy, setBusy] = useState(false);
  if (!items.length) return <p className="text-sm text-slate-500">No suggestions could be extracted.</p>;
  return (
    <div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-slate-500"><tr><th className="w-8" /><th className="py-2">Setting</th><th>Suggested value</th><th>Confidence</th><th>Why</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((s, i) => (
            <tr key={i}>
              <td><input type="checkbox" checked={sel.has(i)} onChange={() => { const n = new Set(sel); n.has(i) ? n.delete(i) : n.add(i); setSel(n); }} /></td>
              <td className="py-2 font-mono text-xs">{s.path}</td>
              <td>
                <span className="flex items-center gap-2">
                  {typeof s.value === "string" && s.value.startsWith("#") && <span className="h-4 w-4 rounded border border-slate-300" style={{ background: s.value }} />}
                  {Array.isArray(s.value) ? (s.value as string[]).map((c) => <span key={c} className="h-4 w-4 rounded border border-slate-300" style={{ background: c }} title={c} />) : String(s.value)}
                </span>
              </td>
              <td><Badge tone={s.confidence >= 0.7 ? "green" : s.confidence >= 0.45 ? "amber" : "red"}>{Math.round(s.confidence * 100)}%</Badge></td>
              <td className="text-xs text-slate-500">{s.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-slate-500">High-confidence values are pre-selected. Low-confidence values are guesses from pixels or theme slots - only apply them if they match the official brand guidelines.</p>
      <div className="mt-3 flex justify-end">
        <Button loading={busy} disabled={!sel.size} onClick={async () => { setBusy(true); try { await onApply(items.filter((_, i) => sel.has(i))); } finally { setBusy(false); } }}>Apply {sel.size} selected</Button>
      </div>
    </div>
  );
}

export function BrandEditor() {
  const { id = "" } = useParams();
  const view = useAsync(() => api.brand(id), [id]);
  const fonts = useAsync(() => api.fonts(), []);
  const [tab, setTab] = useState<Tab>("overview");
  const [draft, setDraft] = useState<BrandProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [preview, setPreview] = useState<{ images: string[]; t: number } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [refSuggestions, setRefSuggestions] = useState<Suggestion[] | null>(null);
  const [tplResult, setTplResult] = useState<(Record<string, unknown> & { suggestions: Suggestion[] }) | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (view.data) setDraft(structuredClone(view.data.profile)); }, [view.data]);
  const dirty = useMemo(() => !!draft && !!view.data && JSON.stringify(draft) !== JSON.stringify(view.data.profile), [draft, view.data]);

  const applyView = (v: BrandView) => { view.setData(v); setDraft(structuredClone(v.profile)); };
  const act = async (fn: () => Promise<BrandView | void>, ok?: string) => {
    setMsg(null); setBusy(true);
    try { const v = await fn(); if (v) applyView(v); if (ok) setMsg({ tone: "success", text: ok }); }
    catch (e) { setMsg({ tone: "error", text: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const save = async () => { setSaving(true); await act(() => api.saveBrand(id, draft), "Brand saved."); setSaving(false); };
  const upd = (fn: (d: BrandProfile) => void) => setDraft((d) => { if (!d) return d; const n = structuredClone(d); fn(n); return n; });

  if (!view.data || !draft) return view.error ? <Alert tone="error">{view.error}</Alert> : <Spinner label="Loading brand…" />;
  const v = view.data;
  const prov = v.profile.provenance;
  const families = fonts.data?.families ?? [];

  return (
    <>
      <Link to="/brands" className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"><ArrowLeft className="h-3.5 w-3.5" /> Brand Manager</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{draft.name}</h1>
            <Badge tone={v.status === "configured" ? "green" : v.status === "partial" ? "amber" : "slate"}>{v.status}</Badge>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">{draft.description}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={<Eye className="h-4 w-4" />} loading={previewing}
            onClick={async () => { setPreviewing(true); try { const r = await api.brandPreview(id); setPreview({ images: r.images, t: Date.now() }); setTab("overview"); } finally { setPreviewing(false); } }}>Preview</Button>
          <Button icon={<Save className="h-4 w-4" />} onClick={save} loading={saving} disabled={!dirty}>Save</Button>
        </div>
      </div>
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      {dirty && <div className="mb-4"><Alert tone="info">You have unsaved changes.</Alert></div>}

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" }, { id: "colors", label: "Colours" }, { id: "typography", label: "Typography" },
        { id: "logo", label: "Logo" }, { id: "layout", label: "Layout & components" }, { id: "references", label: "Reference images" },
        { id: "template", label: "PowerPoint template" },
      ]} />
      <div className="mt-6 space-y-6">
        {tab === "overview" && (
          <>
            {v.fallbacks.length > 0 ? (
              <Alert tone="warning" title="Not fully configured">
                These values are not set yet, so outputs use neutral placeholders for them: {v.fallbacks.map((f) => f.split(" (")[0]).join(", ")}.
                Set them from the official references - start with the <b>PowerPoint template</b> tab if you have one.
              </Alert>
            ) : <Alert tone="success">All core brand values are configured.</Alert>}
            <Card title="Resolved design tokens (what the renderer uses)">
              <div className="flex flex-wrap gap-4">
                {Object.entries(v.resolved.colors).map(([role, c]) => (
                  <div key={role} className="text-center">
                    <div className="h-12 w-16 rounded-lg border border-slate-200" style={{ background: c }} />
                    <div className="mt-1 text-xs text-slate-600">{humanize(role)}</div>
                    <div className="font-mono text-[10px] text-slate-400">{c}</div>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-sm text-slate-600">Headings: <b>{v.resolved.heading_font}</b> · Body: <b>{v.resolved.body_font}</b> · Slide: {v.resolved.slide_size[0]}×{v.resolved.slide_size[1]} in</p>
            </Card>
            {preview && (
              <Card title="Preview (placeholder text)">
                <div className="grid gap-4 md:grid-cols-2">
                  {preview.images.map((n) => <img key={n} src={`/api/brands/${id}/preview/${n}?t=${preview.t}`} alt="" className="w-full rounded-lg border border-slate-200" />)}
                </div>
              </Card>
            )}
            <div className="flex justify-end">
              <Button variant="ghost" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => { if (confirm("Clear all configured values for this brand?")) act(() => api.resetBrand(id), "Brand values cleared."); }}>Reset all values</Button>
            </div>
          </>
        )}

        {tab === "colors" && (
          <Card title="Colour roles">
            <div className="grid gap-5 md:grid-cols-2">
              {COLOR_ROLES.map(([role, label]) => {
                const val = (draft.colors[role] as string | null) ?? "";
                return (
                  <div key={role} className="flex items-center gap-3">
                    <input type="color" value={val || "#ffffff"} onChange={(e) => upd((d) => { d.colors[role] = e.target.value.toUpperCase(); })}
                      className="h-10 w-12 cursor-pointer rounded border border-slate-300" />
                    <div className="flex-1">
                      <div className="flex items-center justify-between"><span className="text-sm font-medium">{label}</span><ProvBadge p={prov[`colors.${role}`]} /></div>
                      <div className="mt-1 flex gap-2">
                        <input className={`${inputCls} font-mono`} placeholder="not set" value={val} onChange={(e) => upd((d) => { d.colors[role] = e.target.value || null; })} />
                        {val && <Button size="sm" variant="ghost" onClick={() => upd((d) => { d.colors[role] = null; })}>Clear</Button>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-6">
              <Field label="Additional brand colours (charts)" hint="Comma-separated #RRGGBB values, in order of use.">
                <input className={`${inputCls} font-mono`} value={draft.colors.palette.join(", ")}
                  onChange={(e) => upd((d) => { d.colors.palette = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); })} />
              </Field>
            </div>
          </Card>
        )}

        {tab === "typography" && (
          <Card title="Typography">
            <div className="grid gap-5 md:grid-cols-3">
              {(["heading", "body", "caption"] as const).map((k) => (
                <div key={k}>
                  <Field label={`${humanize(k)} font`} hint={<ProvBadge p={prov[`typography.${k}.family`]} />}>
                    <input className={inputCls} list="font-families" placeholder="not set" value={draft.typography[k].family ?? ""}
                      onChange={(e) => upd((d) => { d.typography[k].family = e.target.value || null; })} />
                  </Field>
                  {draft.typography[k].family && !families.some((f) => f.toLowerCase() === draft.typography[k].family!.toLowerCase()) && (
                    <p className="mt-1 text-xs text-amber-700">Not installed on this computer - upload the font file below for accurate previews.</p>
                  )}
                </div>
              ))}
              <datalist id="font-families">{families.map((f) => <option key={f} value={f} />)}</datalist>
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-4">
              {["title", "subtitle", "heading", "body", "caption", "kpi", "cover_title"].map((k) => (
                <Field key={k} label={`${humanize(k)} size (pt)`}>
                  <input type="number" min={6} max={120} className={inputCls} placeholder="default" value={num(draft.typography.sizes[k])}
                    onChange={(e) => upd((d) => { d.typography.sizes[k] = e.target.value ? Number(e.target.value) : null; })} />
                </Field>
              ))}
              <Field label="Heading colour role">
                <select className={inputCls} value={draft.typography.heading.color_role ?? ""} onChange={(e) => upd((d) => { d.typography.heading.color_role = e.target.value || null; })}>
                  <option value="">Default (text)</option>{ROLE_OPTIONS.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
                </select>
              </Field>
            </div>
            <div className="mt-5 max-w-md">
              <FileDrop label="Upload a brand font (.ttf / .otf)" accept=".ttf,.otf" onFiles={(f) => act(async () => { await api.uploadFont(id, f[0]); await fonts.reload(); }, "Font installed for this brand.")} />
            </div>
          </Card>
        )}

        {tab === "logo" && (
          <Card title="Logo">
            <div className="grid gap-6 md:grid-cols-2">
              {(["default", "dark"] as const).map((variant) => {
                const file = variant === "dark" ? draft.logo.file_on_dark : draft.logo.file;
                return (
                  <div key={variant}>
                    <div className="mb-2 text-sm font-medium">{variant === "dark" ? "Logo for dark backgrounds (optional)" : "Logo"}</div>
                    <div className={`mb-3 flex h-28 items-center justify-center rounded-lg border border-slate-200 ${variant === "dark" ? "bg-slate-800" : "bg-white"}`}>
                      {file ? <img src={`${brandAssetUrl(id, "assets", file)}?v=${v.profile.updated_at}`} alt="logo" className="max-h-20 max-w-[80%] object-contain" /> : <span className="text-xs text-slate-400">No logo</span>}
                    </div>
                    <FileDrop label="Upload logo (PNG with transparency recommended)" accept="image/*" onFiles={(f) => act(() => api.uploadLogo(id, f[0], variant), "Logo uploaded.")} />
                  </div>
                );
              })}
            </div>
            <div className="mt-6 grid gap-4 md:grid-cols-3">
              <Field label="Position">
                <select className={inputCls} value={draft.logo.position} onChange={(e) => upd((d) => { d.logo.position = e.target.value; })}>
                  {["top_right", "top_left", "bottom_right", "bottom_left", "none"].map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
                </select>
              </Field>
              <Field label="Width (inches)"><input type="number" step={0.1} min={0.3} max={4} className={inputCls} placeholder="auto" value={num(draft.logo.width_in)} onChange={(e) => upd((d) => { d.logo.width_in = e.target.value ? Number(e.target.value) : null; })} /></Field>
              <Field label="Show on">
                <select className={inputCls} value={draft.logo.show_on} onChange={(e) => upd((d) => { d.logo.show_on = e.target.value; })}>
                  {["all", "cover", "content", "none"].map((p) => <option key={p} value={p}>{humanize(p)} slides</option>)}
                </select>
              </Field>
            </div>
          </Card>
        )}

        {tab === "layout" && (
          <>
            <Card title="Slide geometry">
              <div className="grid gap-4 md:grid-cols-4">
                {[["slide_width_in", "Slide width (in)"], ["slide_height_in", "Slide height (in)"], ["margin_x_in", "Side margin (in)"], ["margin_y_in", "Top margin (in)"],
                  ["gutter_in", "Gutter (in)"], ["content_top_in", "Content top (in)"], ["footer_height_in", "Footer height (in)"]].map(([k, label]) => (
                  <Field key={k} label={label}><input type="number" step={0.05} className={inputCls} placeholder="default" value={num(draft.layout[k])}
                    onChange={(e) => upd((d) => { d.layout[k] = e.target.value ? Number(e.target.value) : null; })} /></Field>
                ))}
                <Field label="Title alignment">
                  <select className={inputCls} value={String(draft.layout.title_align ?? "")} onChange={(e) => upd((d) => { d.layout.title_align = e.target.value || null; })}>
                    <option value="">Default (left)</option><option value="left">Left</option><option value="center">Centre</option>
                  </select>
                </Field>
                <Field label="Cover style">
                  <select className={inputCls} value={String(draft.layout.cover_style ?? "")} onChange={(e) => upd((d) => { d.layout.cover_style = e.target.value || null; })}>
                    <option value="">Default (light)</option><option value="light">Light background</option><option value="solid_primary">Solid primary colour</option><option value="template">Template background</option>
                  </select>
                </Field>
              </div>
            </Card>
            <Card title="Components">
              <div className="grid gap-4 md:grid-cols-4">
                {[["card_fill_role", "Card fill"], ["card_border_role", "Card border"], ["accent_bar_role", "Accent bar colour"], ["bullet_color_role", "Bullet colour"],
                  ["table_header_fill_role", "Table header fill"], ["table_band_fill_role", "Table banding"]].map(([k, label]) => (
                  <Field key={k} label={label}>
                    <select className={inputCls} value={String(draft.components[k] ?? "")} onChange={(e) => upd((d) => { d.components[k] = e.target.value || null; })}>
                      <option value="">Default</option>{ROLE_OPTIONS.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
                    </select>
                  </Field>
                ))}
                <Field label="Bullet style">
                  <select className={inputCls} value={String(draft.components.bullet_style ?? "")} onChange={(e) => upd((d) => { d.components.bullet_style = e.target.value || null; })}>
                    <option value="">Default (dot)</option>{["dot", "square", "dash", "number"].map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
                  </select>
                </Field>
                <Field label="Shape style">
                  <select className={inputCls} value={String(draft.components.shape_style ?? "")} onChange={(e) => upd((d) => { d.components.shape_style = e.target.value || null; })}>
                    <option value="">Default (rounded)</option><option value="rounded">Rounded</option><option value="square">Square</option>
                  </select>
                </Field>
                <Field label="Card corner radius (in)"><input type="number" step={0.02} min={0} className={inputCls} placeholder="default" value={num(draft.components.card_radius_in)}
                  onChange={(e) => upd((d) => { d.components.card_radius_in = e.target.value ? Number(e.target.value) : null; })} /></Field>
              </div>
              <div className="mt-5 flex flex-wrap gap-6">
                <Toggle checked={draft.components.accent_bar !== false} onChange={(x) => upd((d) => { d.components.accent_bar = x; })} label="Accent bars" />
                <Toggle checked={!!draft.components.chart_gridlines} onChange={(x) => upd((d) => { d.components.chart_gridlines = x; })} label="Chart gridlines" />
                <Toggle checked={draft.components.chart_data_labels !== false} onChange={(x) => upd((d) => { d.components.chart_data_labels = x; })} label="Chart data labels" />
              </div>
            </Card>
            <Card title="Footer">
              <div className="grid gap-4 md:grid-cols-3">
                <Field label="Footer text" hint="e.g. a classification label from the brand guidelines"><input className={inputCls} value={draft.footer.text} onChange={(e) => upd((d) => { d.footer.text = e.target.value; })} /></Field>
                <Toggle checked={draft.footer.show_page_numbers} onChange={(x) => upd((d) => { d.footer.show_page_numbers = x; })} label="Page numbers" />
                <Toggle checked={draft.footer.show_sources} onChange={(x) => upd((d) => { d.footer.show_sources = x; })} label="Source references on slides" />
              </div>
            </Card>
          </>
        )}

        {tab === "references" && (
          <>
            <Card title="Reference images" actions={v.reference_images.length > 0 && (
              <Button size="sm" icon={<ScanSearch className="h-3.5 w-3.5" />} loading={busy}
                onClick={() => act(async () => { const r = await api.analyzeReferences(id); setRefSuggestions(r.suggestions); })}>Analyse</Button>)}>
              <FileDrop multiple accept="image/*" label="Upload slide screenshots, visual examples or colour references" hint="PNG / JPG · analysed locally"
                onFiles={(f) => act(() => api.uploadReferences(id, f), `${f.length} reference image(s) added.`)} />
              <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {v.reference_images.map((n) => (
                  <div key={n} className="group relative overflow-hidden rounded-lg border border-slate-200">
                    <img src={brandAssetUrl(id, "references", n)} alt={n} className="aspect-video w-full object-cover" />
                    <button className="absolute right-1 top-1 rounded bg-white/90 p-1 text-slate-500 opacity-0 hover:text-red-600 group-hover:opacity-100"
                      onClick={() => act(() => api.deleteReference(id, n))} title="Remove"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                ))}
              </div>
              {v.reference_images.length === 0 && <p className="mt-4 flex items-center gap-2 text-sm text-slate-500"><ImagePlus className="h-4 w-4" /> No reference images yet.</p>}
            </Card>
            {refSuggestions && (
              <Card title="Suggested values from reference images">
                <SuggestionTable items={refSuggestions} onApply={(items) => act(() => api.applySuggestions(id, items), `${items.length} value(s) applied.`)} />
              </Card>
            )}
          </>
        )}

        {tab === "template" && (
          <>
            <Card title="PowerPoint template">
              <p className="mb-4 text-sm text-slate-600">Upload the official .pptx/.potx. Its theme colours, fonts, slide size, margins and master logo are read locally.
                When “use as base” is on, generated decks are built on this template so its masters and backgrounds carry through.</p>
              <FileDrop accept=".pptx,.potx" label="Upload template (.pptx / .potx)" disabled={busy}
                onFiles={(f) => act(async () => { const r = await api.uploadTemplate(id, f[0]); setTplResult(r.analysis); return r.brand; }, "Template analysed.")} />
              {draft.template.file && (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 p-3 text-sm">
                  <span className="flex items-center gap-2"><FileUp className="h-4 w-4 text-slate-500" /> {draft.template.file}</span>
                  <Toggle checked={draft.template.use_as_base} onChange={(x) => upd((d) => { d.template.use_as_base = x; })} label="Use as base for generated decks" />
                </div>
              )}
            </Card>
            {tplResult && (
              <>
                <Card title="What was found">
                  <div className="grid gap-4 text-sm md:grid-cols-3">
                    <div><div className="text-xs uppercase text-slate-500">Slide size</div>{JSON.stringify((tplResult.slide_size as { width_in: number; height_in: number }) ?? {}).replace(/[{}"]/g, " ")}</div>
                    <div><div className="text-xs uppercase text-slate-500">Theme fonts</div>{Object.values((tplResult.theme_fonts as Record<string, string>) ?? {}).join(" / ") || "-"}</div>
                    <div><div className="text-xs uppercase text-slate-500">Layouts</div>{((tplResult.layouts as unknown[]) ?? []).length}</div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {Object.entries((tplResult.theme_colors as Record<string, string>) ?? {}).map(([k, c]) => (
                      <div key={k} className="text-center"><div className="h-8 w-12 rounded border border-slate-200" style={{ background: c }} /><div className="mt-0.5 text-[10px] text-slate-500">{k}</div></div>
                    ))}
                  </div>
                </Card>
                <Card title="Suggested brand values">
                  <SuggestionTable items={tplResult.suggestions} onApply={(items) => act(() => api.applySuggestions(id, items), `${items.length} value(s) applied from the template.`)} />
                </Card>
              </>
            )}
            {!tplResult && !draft.template.file && <p className="flex items-center gap-2 text-sm text-slate-500"><Upload className="h-4 w-4" /> No template uploaded.</p>}
          </>
        )}
      </div>
    </>
  );
}
