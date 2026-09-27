import { ArrowLeft, ArrowRight, Check, FileText, Film, Image, Presentation, FileDown, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileDrop } from "../components/FileDrop";
import { Alert, Badge, Button, Card, Field, Spinner, Toggle, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";
import type { Contract, DocumentInfo } from "../types";
import { bytes, humanize } from "../utils/format";

const STEPS = ["Upload document", "Select brand", "Instructions", "Outputs", "Generate"];
const EXAMPLES = [
  "Create a 10-slide technical presentation for a senior client audience. Focus on architecture, methodology and results. Do not include detailed implementation code.",
  "Create an 8-slide executive briefing summarising the key findings and recommendations for leadership.",
  "Create a 12-slide research presentation covering the background, methodology, results and limitations.",
];
const OUTPUTS = [
  { id: "pptx", label: "PowerPoint", desc: "Editable .pptx", icon: Presentation },
  { id: "pdf", label: "PDF", desc: "For sharing", icon: FileDown },
  { id: "png", label: "Visuals", desc: "Individual images", icon: Image },
  { id: "mp4", label: "Video", desc: "Narrated MP4", icon: Film },
];

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-8 flex flex-wrap items-center gap-2">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${i < step ? "bg-emerald-600 text-white" : i === step ? "bg-slate-900 text-white" : "bg-slate-200 text-slate-500"}`}>
            {i < step ? <Check className="h-4 w-4" /> : i + 1}
          </span>
          <span className={`text-sm ${i === step ? "font-semibold text-slate-900" : "text-slate-500"}`}>{s}</span>
          {i < STEPS.length - 1 && <span className="mx-2 h-px w-8 bg-slate-300" />}
        </li>
      ))}
    </ol>
  );
}

export function NewProject() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [doc, setDoc] = useState<DocumentInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [brandId, setBrandId] = useState("zensar");
  const [instruction, setInstruction] = useState("");
  const [name, setName] = useState("");
  const [formats, setFormats] = useState<string[]>(["pptx", "pdf", "png"]);
  const [narration, setNarration] = useState(true);
  const [subtitles, setSubtitles] = useState(true);
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState(1);
  const [mode, setMode] = useState<"llm" | "extractive">("llm");
  const [preview, setPreview] = useState<Contract | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const brands = useAsync(() => api.brands(), []);
  const status = useAsync(() => api.status(), []);
  const formatsInfo = useAsync(() => api.formats(), []);

  const voices = useMemo(() => Object.entries(status.data?.tts.engines ?? {}).flatMap(([e, vs]) => vs.map((v) => ({ engine: e, v }))), [status.data]);
  const aiReady = !!status.data?.ollama.model_ready;
  useEffect(() => { if (status.data && !aiReady) setMode("extractive"); }, [status.data, aiReady]);

  useEffect(() => {
    if (instruction.trim().length < 10) { setPreview(null); return; }
    const t = setTimeout(() => api.parseInstruction(instruction).then(setPreview).catch(() => setPreview(null)), 400);
    return () => clearTimeout(t);
  }, [instruction]);

  const upload = async (files: File[]) => {
    setError(null);
    setUploading(true);
    try {
      const d = await api.uploadDocument(files[0]);
      setDoc(d);
      if (!name) setName((d.title || d.filename.replace(/\.[^.]+$/, "")).slice(0, 80));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const create = async () => {
    if (!doc) return;
    setSubmitting(true);
    setError(null);
    try {
      const p = await api.createProject({
        name: name.trim() || doc.filename, document_id: doc.id, brand_id: brandId, instruction, output_formats: formats,
        options: { writing_mode: mode, narration, subtitles, voice, speed },
      });
      await api.generate(p.id);
      nav(`/projects/${p.id}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  const canNext = [doc?.status === "ready", !!brandId, instruction.trim().length >= 10, formats.length > 0, true][step];

  return (
    <>
      <PageHeader title="New project" subtitle="Five short steps. Your document never leaves this computer." />
      <Stepper step={step} />
      {error && <div className="mb-4"><Alert tone="error">{error}</Alert></div>}

      {step === 0 && (
        <Card>
          <FileDrop label={uploading ? "Reading document…" : "Drop a document here, or click to browse"} disabled={uploading}
            hint={`Supported: ${(formatsInfo.data?.extensions ?? [".pdf", ".docx", ".pptx", ".txt", ".md", ".html"]).join(" ")}`}
            accept={(formatsInfo.data?.extensions ?? []).join(",")} onFiles={upload} />
          {uploading && <div className="mt-4"><Spinner label="Extracting text, tables and structure…" /></div>}
          {doc && (
            <div className="mt-5 rounded-lg border border-slate-200 p-4">
              <div className="flex items-start gap-3">
                <FileText className="mt-0.5 h-5 w-5 text-slate-400" />
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{doc.filename}</div>
                  <div className="text-xs text-slate-500">{doc.page_count} pages · {bytes(doc.size)}{doc.structure ? ` · ${doc.structure.sections.length} sections · ${doc.structure.tables} tables · ${doc.structure.figures} figures` : ""}</div>
                </div>
                {doc.status === "ready" ? <Badge tone="green">Ready</Badge> : <Badge tone="red">Could not read</Badge>}
              </div>
              {doc.status === "failed" && <div className="mt-3"><Alert tone="error">{doc.error}</Alert></div>}
              {doc.structure && doc.structure.detected_types.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <span className="text-xs text-slate-500">Detected:</span>
                  {doc.structure.detected_types.map((t) => <Badge key={t}>{humanize(t)}</Badge>)}
                </div>
              )}
              {doc.warnings.map((w) => <p key={w} className="mt-2 text-xs text-amber-700">{w}</p>)}
            </div>
          )}
        </Card>
      )}

      {step === 1 && (
        <Card>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(brands.data ?? []).map((b) => (
              <button key={b.id} onClick={() => setBrandId(b.id)}
                className={`rounded-xl border-2 p-4 text-left transition ${brandId === b.id ? "border-slate-900 bg-slate-50" : "border-slate-200 hover:border-slate-300"}`}>
                <div className="flex items-center justify-between">
                  <span className="font-semibold">{b.name}</span>
                  <Badge tone={b.status === "configured" ? "green" : b.status === "partial" ? "amber" : "slate"}>{b.status}</Badge>
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-slate-500">{b.description}</p>
              </button>
            ))}
          </div>
          {brands.data?.find((b) => b.id === brandId)?.status !== "configured" && (
            <div className="mt-4"><Alert tone="warning" title="This brand is not fully configured">
              Outputs will use neutral placeholder styling for anything not yet configured. <Link to={`/brands/${brandId}`} className="font-medium underline">Configure the brand</Link> from the official references first for on-brand results.
            </Alert></div>
          )}
        </Card>
      )}

      {step === 2 && (
        <Card>
          <Field label="What should the presentation cover?" hint="Mention the number of slides, the audience, what to focus on and what to leave out.">
            <textarea className={`${inputCls} min-h-32`} value={instruction} onChange={(e) => setInstruction(e.target.value)} maxLength={4000}
              placeholder="e.g. Create a 10-slide technical presentation for a client audience focusing on methodology and results." />
          </Field>
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button key={ex} onClick={() => setInstruction(ex)} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50">
                <Sparkles className="mr-1 inline h-3 w-3" />{ex.slice(0, 60)}…
              </button>
            ))}
          </div>
          {preview && (
            <div className="mt-5 rounded-lg bg-slate-50 p-4 text-sm">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">How this will be interpreted</div>
              <div className="flex flex-wrap gap-2">
                <Badge tone="blue">{preview.slide_count} slides</Badge>
                <Badge>Audience: {humanize(preview.audience)}</Badge>
                <Badge>{humanize(preview.purpose)}</Badge>
                <Badge>Detail: {preview.detail_level}</Badge>
                {preview.include.map((t) => <Badge key={t} tone="green">Focus: {humanize(t)}</Badge>)}
                {preview.exclude.map((t) => <Badge key={t} tone="red">Exclude: {humanize(t)}</Badge>)}
              </div>
              <p className="mt-2 text-xs text-slate-500">Only content relevant to this focus is used, and every statement is checked against the document.</p>
            </div>
          )}
          <div className="mt-5">
            <Field label="Project name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
          </div>
        </Card>
      )}

      {step === 3 && (
        <div className="space-y-6">
          <Card title="Outputs">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {OUTPUTS.map(({ id, label, desc, icon: Icon }) => {
                const on = formats.includes(id);
                return (
                  <button key={id} onClick={() => setFormats(on ? formats.filter((f) => f !== id) : [...formats, id])}
                    className={`flex items-center gap-3 rounded-xl border-2 p-4 text-left transition ${on ? "border-slate-900 bg-slate-50" : "border-slate-200 hover:border-slate-300"}`}>
                    <Icon className="h-6 w-6 text-slate-600" />
                    <div><div className="text-sm font-semibold">{label}</div><div className="text-xs text-slate-500">{desc}</div></div>
                  </button>
                );
              })}
            </div>
          </Card>
          {formats.includes("mp4") && (
            <Card title="Video narration">
              <div className="grid gap-5 md:grid-cols-3">
                <Toggle checked={narration} onChange={setNarration} label="Generate narration" disabled={!status.data?.tts.available} />
                <Field label="Voice">
                  <select className={inputCls} value={voice} onChange={(e) => setVoice(e.target.value)} disabled={!narration}>
                    <option value="">Default voice</option>
                    {voices.map(({ engine, v }) => <option key={engine + v} value={v}>{v} ({engine})</option>)}
                  </select>
                </Field>
                <Field label={`Speed · ${speed.toFixed(2)}×`}>
                  <input type="range" min={0.7} max={1.4} step={0.05} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-full" disabled={!narration} />
                </Field>
                <Toggle checked={subtitles} onChange={setSubtitles} label="Subtitles" disabled={!narration} />
              </div>
              {!status.data?.tts.available && <p className="mt-3 text-xs text-amber-700">No offline voice is installed, so the video will be generated without narration.</p>}
            </Card>
          )}
          <Card title="Writing">
            <div className="grid gap-3 md:grid-cols-2">
              <button onClick={() => aiReady && setMode("llm")} disabled={!aiReady}
                className={`rounded-xl border-2 p-4 text-left ${mode === "llm" ? "border-slate-900 bg-slate-50" : "border-slate-200"} disabled:opacity-50`}>
                <div className="flex items-center gap-2 text-sm font-semibold"><Wand2 className="h-4 w-4" /> Local AI writing (recommended)</div>
                <p className="mt-1 text-xs text-slate-500">Concise, audience-aware wording from the local model. Every statement is verified against the source. Takes a few minutes.</p>
                {!aiReady && <p className="mt-1 text-xs text-amber-700">Local model not available - <Link className="underline" to="/settings">configure it in Settings</Link>.</p>}
              </button>
              <button onClick={() => setMode("extractive")}
                className={`rounded-xl border-2 p-4 text-left ${mode === "extractive" ? "border-slate-900 bg-slate-50" : "border-slate-200"}`}>
                <div className="flex items-center gap-2 text-sm font-semibold"><FileText className="h-4 w-4" /> Fast extractive</div>
                <p className="mt-1 text-xs text-slate-500">Uses the most relevant sentences directly from the document. Very fast, no AI model needed.</p>
              </button>
            </div>
          </Card>
        </div>
      )}

      {step === 4 && doc && (
        <Card title="Ready to generate">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-xs uppercase text-slate-500">Project</dt><dd className="font-medium">{name}</dd></div>
            <div><dt className="text-xs uppercase text-slate-500">Document</dt><dd>{doc.filename}</dd></div>
            <div><dt className="text-xs uppercase text-slate-500">Brand</dt><dd>{brands.data?.find((b) => b.id === brandId)?.name}</dd></div>
            <div><dt className="text-xs uppercase text-slate-500">Outputs</dt><dd className="uppercase">{formats.join(" · ")}</dd></div>
            <div className="sm:col-span-2"><dt className="text-xs uppercase text-slate-500">Instructions</dt><dd className="text-slate-700">{instruction}</dd></div>
          </dl>
        </Card>
      )}

      <div className="mt-6 flex justify-between">
        <Button variant="secondary" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep(step - 1)} disabled={step === 0}>Back</Button>
        {step < 4 ? (
          <Button onClick={() => setStep(step + 1)} disabled={!canNext}>Next <ArrowRight className="h-4 w-4" /></Button>
        ) : (
          <Button onClick={create} loading={submitting} icon={<Sparkles className="h-4 w-4" />}>Generate</Button>
        )}
      </div>
    </>
  );
}
