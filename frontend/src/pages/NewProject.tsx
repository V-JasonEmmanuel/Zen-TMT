import { ArrowLeft, ArrowRight, Check, FileDown, FileText, Film, FolderGit2, Github, Image, Music, Presentation, Sparkles, Trash2, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileDrop } from "../components/FileDrop";
import { MediaThumb } from "../components/MediaPicker";
import { TemplateGallery } from "../components/TemplateGallery";
import { Alert, Badge, Button, Card, Field, Spinner, Toggle, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";
import type { Contract, DocumentInfo, MediaAsset, ProjectOptions, Transition } from "../types";
import { bytes, humanize } from "../utils/format";

const STEPS = ["Sources", "Brand & template", "Instructions", "Outputs & video", "Generate"];
const EXAMPLES = [
  "Create a 10-slide technical presentation for a senior client audience. Focus on architecture, methodology and results. Do not include detailed implementation code.",
  "Create an 8-slide executive briefing summarising the key findings and recommendations for leadership.",
  "Create a 7-slide product walkthrough explaining what the demo shows, how it works, the architecture and the pipeline.",
];
const OUTPUTS = [
  { id: "pptx", label: "PowerPoint", desc: "Editable .pptx", icon: Presentation },
  { id: "pdf", label: "PDF", desc: "For sharing", icon: FileDown },
  { id: "png", label: "Visuals", desc: "Individual images", icon: Image },
  { id: "mp4", label: "Video", desc: "Motion graphics MP4", icon: Film },
];
export const TRANSITIONS: { id: Transition; label: string }[] = [
  { id: "zensar_grid", label: "Zensar grid" }, { id: "fade", label: "Fade" }, { id: "wipe", label: "Wipe" }, { id: "none", label: "Cut" },
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

const kindIcon = (d: DocumentInfo) => d.kind === "video" ? Film : d.kind === "repository" ? FolderGit2 : FileText;
const sourceOk = (d: DocumentInfo) => d.status === "ready" || !!d.deferred;

function SourceRow({ d, onRemove }: { d: DocumentInfo; onRemove: () => void }) {
  const Icon = kindIcon(d);
  const detail = d.kind === "video"
    ? `Demo video${d.duration ? ` · ${Math.round(d.duration)} s` : ""} · scenes are analysed frame by frame during generation`
    : d.kind === "repository"
      ? `Code repository${d.source_url ? ` · ${d.source_url}` : ""} · explained during generation (architecture, workflow, stack)`
      : `${d.page_count} pages${d.structure ? ` · ${d.structure.sections.length} sections · ${d.structure.tables} tables · ${d.structure.figures} figures` : ""}`;
  return (
    <li className="flex items-start gap-3 rounded-lg border border-slate-200 p-3">
      <Icon className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{d.filename}</div>
        <div className="text-xs text-slate-500">{detail} · {bytes(d.size)}</div>
        {d.status === "failed" && <div className="mt-1 text-xs text-red-700">{d.error}</div>}
        {d.warnings.map((w) => <p key={w} className="mt-1 text-xs text-amber-700">{w}</p>)}
      </div>
      {d.status === "failed" ? <Badge tone="red">Could not read</Badge> : d.deferred ? <Badge tone="blue">{humanize(d.kind)}</Badge> : <Badge tone="green">Ready</Badge>}
      <button onClick={onRemove} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600" aria-label={`Remove ${d.filename}`}><Trash2 className="h-4 w-4" /></button>
    </li>
  );
}

export function NewProject() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [sources, setSources] = useState<DocumentInfo[]>([]);
  const [uploading, setUploading] = useState<string | null>(null);
  const [github, setGithub] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [brandId, setBrandId] = useState("zensar");
  const [templateId, setTemplateId] = useState<string>("preset:zensar_experience");
  const [instruction, setInstruction] = useState("");
  const [name, setName] = useState("");
  const [formats, setFormats] = useState<string[]>(["pptx", "pdf", "png"]);
  const [narrationMode, setNarrationMode] = useState<"tts" | "upload" | "none">("tts");
  const [narrationAudio, setNarrationAudio] = useState<MediaAsset | null>(null);
  const [script, setScript] = useState("");
  const [music, setMusic] = useState<MediaAsset | null>(null);
  const [extraMedia, setExtraMedia] = useState<MediaAsset[]>([]);
  const [transition, setTransition] = useState<Transition>("zensar_grid");
  const [motion, setMotion] = useState<"none" | "subtle" | "ken_burns">("subtle");
  const [intro, setIntro] = useState(true);
  const [outro, setOutro] = useState(true);
  const [subtitles, setSubtitles] = useState(true);
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState(1);
  const [mode, setMode] = useState<"llm" | "extractive">("llm");
  const [preview, setPreview] = useState<Contract | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyMedia, setBusyMedia] = useState<string | null>(null);
  const brands = useAsync(() => api.brands(), []);
  const status = useAsync(() => api.status(), []);
  const formatsInfo = useAsync(() => api.formats(), []);
  const audioLib = useAsync(() => api.media("audio"), []);

  const voices = useMemo(() => Object.entries(status.data?.tts.engines ?? {}).flatMap(([e, vs]) => vs.map((v) => ({ engine: e, v }))), [status.data]);
  const aiReady = !!status.data?.ollama.model_ready;
  const hasVideoSource = sources.some((s) => s.kind === "video");
  useEffect(() => { if (status.data && !aiReady) setMode("extractive"); }, [status.data, aiReady]);
  useEffect(() => { if (hasVideoSource && !formats.includes("mp4")) setFormats((f) => [...f, "mp4"]); }, [hasVideoSource]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (instruction.trim().length < 10) { setPreview(null); return; }
    const t = setTimeout(() => api.parseInstruction(instruction).then(setPreview).catch(() => setPreview(null)), 400);
    return () => clearTimeout(t);
  }, [instruction]);

  const addSource = (d: DocumentInfo) => {
    setSources((prev) => [...prev.filter((x) => x.id !== d.id), d]);
    setName((n) => n || (d.title || d.filename.replace(/\.[^.]+$/, "")).slice(0, 80));
  };

  const upload = async (files: File[]) => {
    setError(null);
    for (const f of files) {
      setUploading(f.name);
      try { addSource(await api.uploadDocument(f)); } catch (e) { setError(`${f.name}: ${(e as Error).message}`); }
    }
    setUploading(null);
  };

  const importGithub = async () => {
    setError(null);
    setUploading(github);
    try { addSource(await api.importGithub(github.trim(), token.trim())); setGithub(""); setToken(""); } catch (e) { setError((e as Error).message); }
    setUploading(null);
  };

  const uploadMedia = async (files: File[], target: "music" | "narration" | "extra") => {
    setError(null);
    setBusyMedia(target);
    try {
      const assets = await api.uploadMedia(files);
      if (target === "music") { setMusic(assets[0]); audioLib.reload(); }
      else if (target === "narration") setNarrationAudio(assets[0]);
      else setExtraMedia((m) => [...m, ...assets.filter((a) => a.kind === "image" || a.kind === "video")]);
    } catch (e) { setError((e as Error).message); }
    setBusyMedia(null);
  };

  const importScript = async (files: File[]) => {
    setError(null);
    try { setScript((await api.parseScript(files[0])).script); } catch (e) { setError((e as Error).message); }
  };

  const create = async () => {
    if (!sources.length) return;
    setSubmitting(true);
    setError(null);
    const options: ProjectOptions = {
      writing_mode: mode, narration: narrationMode !== "none", narration_mode: narrationMode, subtitles, voice, speed,
      narration_asset_id: narrationMode === "upload" ? narrationAudio?.id ?? null : null, script: narrationMode === "tts" ? script : "",
      music_asset_id: music?.id ?? null, video_media: extraMedia.map((m) => m.id), transition, motion, intro, outro,
      ...(templateId ? { template_id: templateId } : {}),
    };
    try {
      const p = await api.createProject({
        name: name.trim() || sources[0].filename, document_ids: sources.map((s) => s.id), brand_id: brandId, instruction,
        output_formats: formats, options,
      });
      await api.generate(p.id);
      nav(`/projects/${p.id}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  const canNext = [
    sources.length > 0 && sources.every(sourceOk) && !uploading, !!brandId, instruction.trim().length >= 10,
    formats.length > 0 && !(formats.includes("mp4") && narrationMode === "upload" && !narrationAudio), true,
  ][step];
  const exts = formatsInfo.data?.extensions ?? [".pdf", ".docx", ".pptx", ".txt", ".md", ".html", ".mp4", ".zip"];

  return (
    <>
      <PageHeader title="New project" subtitle="Documents, demo videos and code repositories are analysed on this computer." />
      <Stepper step={step} />
      {error && <div className="mb-4"><Alert tone="error">{error}</Alert></div>}

      {step === 0 && (
        <div className="space-y-6">
          <Card title="Upload sources">
            <FileDrop multiple label={uploading ? `Adding ${uploading}…` : "Drop files here, or click to browse"} disabled={!!uploading}
              hint={`Documents, demo videos (.mp4 .mov .webm) and zipped repositories. Add as many as you need. Supported: ${exts.join(" ")}`}
              accept={exts.join(",")} onFiles={upload} />
            {uploading && <div className="mt-4"><Spinner label={`Reading ${uploading}…`} /></div>}
          </Card>
          <Card title={<span className="flex items-center gap-2"><Github className="h-4 w-4" /> Import a GitHub repository</span>}>
            <div className="grid gap-3 md:grid-cols-[1fr_16rem_auto] md:items-end">
              <Field label="Repository URL"><input className={inputCls} value={github} onChange={(e) => setGithub(e.target.value)} placeholder="https://github.com/owner/repository" /></Field>
              <Field label="Access token (private repos only)"><input type="password" autoComplete="off" className={inputCls} value={token} onChange={(e) => setToken(e.target.value)} placeholder="optional" /></Field>
              <Button onClick={importGithub} disabled={!/github\.com\/[^/\s]+\/[^/\s]+/.test(github) || !!uploading} loading={uploading === github}>Import</Button>
            </div>
            <p className="mt-2 text-xs text-slate-500">This is the only step that goes online: the repository is downloaded from github.com once. The token is used for that download only and is never stored. You can also upload a .zip of the repository instead.</p>
          </Card>
          {sources.length > 0 && (
            <Card title={`Sources (${sources.length})`}>
              <ul className="space-y-2">{sources.map((d) => <SourceRow key={d.id} d={d} onRemove={() => setSources(sources.filter((x) => x.id !== d.id))} />)}</ul>
              {sources.some((s) => s.kind === "video") && !status.data?.ollama.models.some((m) => /vl|llava|moondream|vision/i.test(m.name)) && (
                <div className="mt-3"><Alert tone="warning">No local vision model is installed, so demo videos are narrated from on-screen scenes without reading their content. Install one with <code>ollama pull qwen2.5vl:3b</code> for frame-by-frame understanding.</Alert></div>
              )}
            </Card>
          )}
        </div>
      )}

      {step === 1 && (
        <div className="space-y-6">
          <Card title="Brand">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(brands.data ?? []).map((b) => (
                <button key={b.id} onClick={() => { setBrandId(b.id); setTemplateId(b.id === "zensar" ? "preset:zensar_experience" : ""); }}
                  className={`rounded-xl border-2 p-4 text-left transition ${brandId === b.id ? "border-slate-900 bg-slate-50" : "border-slate-200 hover:border-slate-300"}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-semibold">{b.name}</span>
                    <Badge tone={b.status === "configured" ? "green" : b.status === "partial" ? "amber" : "slate"}>{b.status}</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-slate-500">{b.description}</p>
                </button>
              ))}
            </div>
            {brands.data && brands.data.find((b) => b.id === brandId)?.status !== "configured" && (
              <div className="mt-4"><Alert tone="warning" title="This brand is not fully configured">
                Anything not yet configured uses neutral placeholder styling. <Link to={`/brands/${brandId}`} className="font-medium underline">Configure the brand</Link> from official references for on-brand results.
              </Alert></div>
            )}
          </Card>
          <Card title="Presentation template" actions={<Link to="/templates" className="text-xs font-medium text-slate-600 hover:underline">Manage templates</Link>}>
            <TemplateGallery brandId={brandId} value={templateId} onChange={setTemplateId} />
          </Card>
        </div>
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
              <p className="mt-2 text-xs text-slate-500">Only content relevant to this focus is used, and every statement is checked against the sources.</p>
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
            <>
              <Card title="Video narration">
                <div className="mb-4 flex flex-wrap gap-2">
                  {([["tts", "Offline voice"], ["upload", "My own recording"], ["none", "No narration"]] as const).map(([id, label]) => (
                    <button key={id} onClick={() => setNarrationMode(id)}
                      className={`rounded-lg border-2 px-3 py-2 text-sm ${narrationMode === id ? "border-slate-900 bg-slate-50 font-semibold" : "border-slate-200"}`}>{label}</button>
                  ))}
                </div>
                {narrationMode === "tts" && (
                  <div className="space-y-4">
                    <div className="grid gap-5 md:grid-cols-3">
                      <Field label="Voice">
                        <select className={inputCls} value={voice} onChange={(e) => setVoice(e.target.value)}>
                          <option value="">Default voice</option>
                          {voices.map(({ engine, v }) => <option key={engine + v} value={v}>{v} ({engine})</option>)}
                        </select>
                      </Field>
                      <Field label={`Speed · ${speed.toFixed(2)}×`}>
                        <input type="range" min={0.7} max={1.4} step={0.05} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-full" />
                      </Field>
                      <div className="pt-6"><Toggle checked={subtitles} onChange={setSubtitles} label="Subtitles" /></div>
                    </div>
                    <Field label="Script (optional)" hint={<>Leave empty to narrate the generated slides. Mark sections with <code>## Slide 3</code> (or separate them with <code>---</code>) to control what is said on each slide; unmarked text is spread across the video.</>}>
                      <textarea className={`${inputCls} min-h-28 font-mono text-xs`} value={script} onChange={(e) => setScript(e.target.value)} maxLength={100000}
                        placeholder={"## Slide 1\nWelcome to InvoiceFlow...\n\n## Slide 2\n..."} />
                    </Field>
                    <FileDrop label="Import a script file" hint=".txt .md .docx .srt .vtt" accept=".txt,.md,.docx,.srt,.vtt" onFiles={importScript} />
                    {!status.data?.tts.available && <p className="text-xs text-amber-700">No offline voice is installed, so the video will be generated without spoken narration.</p>}
                  </div>
                )}
                {narrationMode === "upload" && (
                  <div className="space-y-3">
                    {narrationAudio ? (
                      <div className="flex items-center gap-3 rounded-lg border border-slate-200 p-3 text-sm">
                        <Music className="h-4 w-4 text-slate-500" /><span className="flex-1 truncate">{narrationAudio.filename}</span>
                        {narrationAudio.duration ? <Badge>{Math.round(narrationAudio.duration)} s</Badge> : null}
                        <audio src={narrationAudio.url} controls className="h-8" />
                        <button onClick={() => setNarrationAudio(null)} className="text-slate-400 hover:text-red-600" aria-label="Remove recording"><Trash2 className="h-4 w-4" /></button>
                      </div>
                    ) : (
                      <FileDrop label={busyMedia === "narration" ? "Uploading…" : "Upload your narration (audio or video with sound)"} hint=".mp3 .wav .m4a .aac .ogg .flac"
                        accept=".mp3,.wav,.m4a,.aac,.ogg,.flac" disabled={!!busyMedia} onFiles={(f) => uploadMedia(f, "narration")} />
                    )}
                    <p className="text-xs text-slate-500">Your recording plays across the whole video. You can also attach recordings to individual clips in the video editor.</p>
                    <Toggle checked={subtitles} onChange={setSubtitles} label="Subtitles (from the slide narration text)" />
                  </div>
                )}
              </Card>
              <Card title="Music & media">
                <div className="grid gap-6 lg:grid-cols-2">
                  <div className="space-y-3">
                    <Field label="Background music">
                      <select className={inputCls} value={music?.id ?? ""} onChange={(e) => setMusic((audioLib.data ?? []).find((a) => a.id === e.target.value) ?? null)}>
                        <option value="">No music</option>
                        {(audioLib.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.filename}{a.duration ? ` · ${Math.round(a.duration)} s` : ""}</option>)}
                      </select>
                    </Field>
                    <FileDrop label={busyMedia === "music" ? "Uploading…" : "Upload music"} hint="Loops to the video length, fades in/out and dips under narration"
                      accept=".mp3,.wav,.m4a,.aac,.ogg,.flac" disabled={!!busyMedia} onFiles={(f) => uploadMedia(f, "music")} />
                    {music && <audio src={music.url} controls className="w-full" />}
                  </div>
                  <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Images & videos to include</div>
                    <FileDrop multiple label={busyMedia === "extra" ? "Uploading…" : "Add images or video clips"} hint="Added before the closing slide; reorder, trim and crop them in the video editor"
                      accept=".png,.jpg,.jpeg,.webp,.gif,.mp4,.mov,.webm,.mkv,.avi,.m4v" disabled={!!busyMedia} onFiles={(f) => uploadMedia(f, "extra")} />
                    {extraMedia.length > 0 && (
                      <div className="grid grid-cols-3 gap-2">
                        {extraMedia.map((m) => (
                          <div key={m.id} className="group relative">
                            <MediaThumb asset={m} />
                            <button onClick={() => setExtraMedia(extraMedia.filter((x) => x.id !== m.id))} aria-label={`Remove ${m.filename}`}
                              className="absolute right-1 top-1 rounded bg-white/90 p-1 text-slate-600 opacity-0 shadow group-hover:opacity-100"><Trash2 className="h-3.5 w-3.5" /></button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
              <Card title="Motion graphics">
                <div className="grid gap-5 md:grid-cols-4">
                  <Field label="Transition">
                    <select className={inputCls} value={transition} onChange={(e) => setTransition(e.target.value as Transition)}>
                      {TRANSITIONS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Slide animation">
                    <select className={inputCls} value={motion} onChange={(e) => setMotion(e.target.value as typeof motion)}>
                      <option value="subtle">Animated builds</option><option value="ken_burns">Builds + slow zoom</option><option value="none">Static</option>
                    </select>
                  </Field>
                  <div className="pt-6"><Toggle checked={intro} onChange={setIntro} label="Animated brand intro" /></div>
                  <div className="pt-6"><Toggle checked={outro} onChange={setOutro} label="Closing card" /></div>
                </div>
                <p className="mt-3 text-xs text-slate-500">Titles, bullets and diagrams build in, numbers count up and charts grow. Everything is editable later in the video editor.</p>
              </Card>
            </>
          )}
          <Card title="Writing">
            <div className="grid gap-3 md:grid-cols-2">
              <button onClick={() => aiReady && setMode("llm")} disabled={!aiReady}
                className={`rounded-xl border-2 p-4 text-left ${mode === "llm" ? "border-slate-900 bg-slate-50" : "border-slate-200"} disabled:opacity-50`}>
                <div className="flex items-center gap-2 text-sm font-semibold"><Wand2 className="h-4 w-4" /> Local AI writing (recommended)</div>
                <p className="mt-1 text-xs text-slate-500">Concise, audience-aware wording from the local model. Every statement is verified against the sources. Takes a few minutes.</p>
                {!aiReady && <p className="mt-1 text-xs text-amber-700">Local model not available - <Link className="underline" to="/settings">configure it in Settings</Link>.</p>}
              </button>
              <button onClick={() => setMode("extractive")}
                className={`rounded-xl border-2 p-4 text-left ${mode === "extractive" ? "border-slate-900 bg-slate-50" : "border-slate-200"}`}>
                <div className="flex items-center gap-2 text-sm font-semibold"><FileText className="h-4 w-4" /> Fast extractive</div>
                <p className="mt-1 text-xs text-slate-500">Uses the most relevant sentences directly from the sources. Very fast, no AI model needed.</p>
              </button>
            </div>
          </Card>
        </div>
      )}

      {step === 4 && (
        <Card title="Ready to generate">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-xs uppercase text-slate-500">Project</dt><dd className="font-medium">{name}</dd></div>
            <div><dt className="text-xs uppercase text-slate-500">Sources</dt><dd>{sources.map((s) => s.filename).join(", ")}</dd></div>
            <div><dt className="text-xs uppercase text-slate-500">Brand · template</dt><dd>{brands.data?.find((b) => b.id === brandId)?.name} · {templateId ? templateId.replace("preset:", "").replace(/_/g, " ") : "brand default"}</dd></div>
            <div><dt className="text-xs uppercase text-slate-500">Outputs</dt><dd className="uppercase">{formats.join(" · ")}</dd></div>
            {formats.includes("mp4") && (
              <div className="sm:col-span-2"><dt className="text-xs uppercase text-slate-500">Video</dt>
                <dd>{narrationMode === "tts" ? (script ? "Offline voice reading your script" : "Offline voice narration") : narrationMode === "upload" ? `Your recording (${narrationAudio?.filename})` : "No narration"}
                  {music ? ` · music: ${music.filename}` : ""}{extraMedia.length ? ` · ${extraMedia.length} extra media` : ""} · {TRANSITIONS.find((t) => t.id === transition)?.label} transitions{intro ? " · intro" : ""}{outro ? " · outro" : ""}</dd></div>
            )}
            <div className="sm:col-span-2"><dt className="text-xs uppercase text-slate-500">Instructions</dt><dd className="text-slate-700">{instruction}</dd></div>
          </dl>
          {sources.some((s) => s.deferred) && <p className="mt-4 text-xs text-slate-500">Videos and repositories are analysed at the start of generation; a demo video takes about 5 seconds of analysis per second of footage.</p>}
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
