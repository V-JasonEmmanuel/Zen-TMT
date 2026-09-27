import { CheckCircle2, Cpu, HardDrive, Mic, Save, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Field, Spinner, Toggle, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";
import type { RuntimeSettings } from "../types";

function Row({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <li className="flex items-start gap-2 py-1.5 text-sm">
      {ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : <XCircle className="mt-0.5 h-4 w-4 text-red-500" />}
      <div><div className="font-medium">{label}</div>{detail && <div className="text-xs text-slate-500">{detail}</div>}</div>
    </li>
  );
}

export function ModelPicker({ value, onChange }: { value: string; onChange: (m: string) => void }) {
  const status = useAsync(() => api.status(), []);
  const models = status.data?.ollama.models ?? [];
  if (!status.data) return <Spinner />;
  if (!status.data.ollama.running) {
    return <Alert tone="warning" title="Local model unavailable">Ollama is not running. Start the Ollama application, then refresh this page. Nothing is sent to any cloud service.</Alert>;
  }
  return (
    <div className="space-y-2">
      <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select installed model…</option>
        {models.map((m) => <option key={m.name} value={m.name}>{m.name} · {m.parameters} {m.quantization} · {m.size_gb} GB</option>)}
      </select>
      {models.length === 0 && <p className="text-xs text-amber-700">No models are installed. Install a small instruction model with Ollama (see README), e.g. qwen2.5:3b.</p>}
      <p className="text-xs text-slate-500">Recommended for 16 GB RAM / 4 GB GPU: a 3–4B instruction model (e.g. qwen2.5:3b) for speed, or a 7B Q4 model for best wording.</p>
    </div>
  );
}

export function SettingsPage() {
  const s = useAsync(() => api.settings(), []);
  const status = useAsync(() => api.status(), []);
  const [draft, setDraft] = useState<RuntimeSettings | null>(null);
  const [msg, setMsg] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  useEffect(() => { if (s.data) setDraft(s.data.settings); }, [s.data]);
  if (!draft || !s.data) return <Spinner label="Loading settings…" />;
  const set = <K extends keyof RuntimeSettings>(k: K, v: RuntimeSettings[K]) => setDraft({ ...draft, [k]: v });
  const voices = Object.entries(status.data?.tts.engines ?? {});

  const save = async () => {
    setSaving(true); setMsg(null);
    try { await api.saveSettings(draft); await status.reload(); setMsg({ tone: "success", text: "Settings saved." }); }
    catch (e) { setMsg({ tone: "error", text: (e as Error).message }); }
    finally { setSaving(false); }
  };

  return (
    <>
      <PageHeader title="Settings" subtitle="Everything runs on this computer. No cloud APIs, no telemetry."
        actions={<Button icon={<Save className="h-4 w-4" />} onClick={save} loading={saving}>Save settings</Button>} />
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title={<span className="flex items-center gap-2"><Cpu className="h-4 w-4" /> Local AI</span>}
            actions={<Button size="sm" variant="secondary" loading={testing} onClick={async () => {
              setTesting(true); setMsg(null);
              try { await api.saveSettings(draft); const r = await api.testLLM(); setMsg(r.ok ? { tone: "success", text: `Model responded in ${r.seconds}s.` } : { tone: "error", text: r.message ?? "The model did not respond correctly." }); }
              catch (e) { setMsg({ tone: "error", text: (e as Error).message }); } finally { setTesting(false); }
            }}>Test model</Button>}>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Ollama model"><ModelPicker value={draft.ollama_model} onChange={(m) => set("ollama_model", m)} /></Field>
              <Field label="Ollama address" hint="Must be on this machine (localhost)."><input className={inputCls} value={draft.ollama_host} onChange={(e) => set("ollama_host", e.target.value)} /></Field>
              <Field label={`Creativity (temperature) · ${draft.llm_temperature.toFixed(2)}`} hint="Low values keep wording closest to the source.">
                <input type="range" min={0} max={0.8} step={0.05} value={draft.llm_temperature} onChange={(e) => set("llm_temperature", Number(e.target.value))} className="w-full" />
              </Field>
              <Field label="Timeout per request (s)"><input type="number" min={30} max={900} className={inputCls} value={draft.llm_timeout_s} onChange={(e) => set("llm_timeout_s", Number(e.target.value))} /></Field>
              <Field label="Embedding model" hint="Local sentence-transformers model (prepared with scripts/prepare_models.py).">
                <input className={inputCls} value={draft.embedding_model} onChange={(e) => set("embedding_model", e.target.value)} />
              </Field>
            </div>
          </Card>

          <Card title="Accuracy & verification">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label={`Verification threshold · ${Math.round(draft.verification_threshold * 100)}%`} hint="Statements below this source-match score are flagged for review.">
                <input type="range" min={0.2} max={0.9} step={0.05} value={draft.verification_threshold} onChange={(e) => set("verification_threshold", Number(e.target.value))} className="w-full" />
              </Field>
              <div className="space-y-3 pt-5">
                <Toggle checked={draft.drop_unverified} onChange={(v) => set("drop_unverified", v)} label="Remove low-confidence statements instead of flagging them" />
                <Toggle checked={draft.ocr_enabled} onChange={(v) => set("ocr_enabled", v)} label="Use OCR for scanned pages (when an OCR engine is installed)" />
              </div>
            </div>
            <p className="mt-3 text-xs text-slate-500">Statements containing numbers that do not appear in the source are always removed.</p>
          </Card>

          <Card title={<span className="flex items-center gap-2"><Mic className="h-4 w-4" /> Narration & video</span>}>
            <div className="grid gap-4 md:grid-cols-2">
              <Toggle checked={draft.tts_enabled} onChange={(v) => set("tts_enabled", v)} label="Generate narration by default" />
              <Toggle checked={draft.subtitles} onChange={(v) => set("subtitles", v)} label="Subtitles by default" />
              <Field label="Voice engine">
                <select className={inputCls} value={draft.tts_engine} onChange={(e) => set("tts_engine", e.target.value)}>
                  <option value="auto">Automatic</option>{voices.map(([e]) => <option key={e} value={e}>{e}</option>)}<option value="none">None</option>
                </select>
              </Field>
              <Field label="Default voice">
                <select className={inputCls} value={draft.tts_voice} onChange={(e) => set("tts_voice", e.target.value)}>
                  <option value="">Default</option>
                  {voices.flatMap(([e, vs]) => vs.map((v) => <option key={e + v} value={v}>{v} ({e})</option>))}
                </select>
              </Field>
              <Field label={`Speed · ${draft.tts_rate.toFixed(2)}×`}>
                <input type="range" min={0.7} max={1.4} step={0.05} value={draft.tts_rate} onChange={(e) => set("tts_rate", Number(e.target.value))} className="w-full" />
              </Field>
              <Field label="FFmpeg path" hint="Leave empty to use the bundled engine."><input className={inputCls} value={draft.ffmpeg_path} onChange={(e) => set("ffmpeg_path", e.target.value)} /></Field>
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="System check" actions={<Button size="sm" variant="ghost" onClick={status.reload}>Refresh</Button>}>
            {!status.data ? <Spinner /> : (
              <ul>
                <Row ok={status.data.ollama.running} label="Ollama" detail={status.data.ollama.running ? `${status.data.ollama.models.length} model(s) installed` : "Not running"} />
                <Row ok={status.data.ollama.model_ready} label="Selected model" detail={status.data.ollama.selected || "None selected"} />
                <Row ok={status.data.embeddings.onnx_ready} label="Embeddings" detail={status.data.embeddings.model} />
                <Row ok={status.data.ffmpeg.available} label="FFmpeg" detail={status.data.ffmpeg.path ?? "Not found"} />
                <Row ok={status.data.tts.available} label="Offline voices" detail={Object.values(status.data.tts.engines).flat().length + " voice(s)"} />
                <Row ok={status.data.ocr.available} label="OCR (optional)" detail={status.data.ocr.engine ?? "Not installed - only needed for scanned PDFs"} />
                <Row ok={status.data.gpu.available} label="GPU (optional)" detail={status.data.gpu.name ? `${status.data.gpu.name} · ${status.data.gpu.memory}` : "CPU only"} />
                <Row ok={status.data.disk_free_gb > 5} label="Disk space" detail={`${status.data.disk_free_gb} GB free`} />
              </ul>
            )}
          </Card>
          <Card title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Data & privacy</span>}>
            <ul className="space-y-2 text-sm">
              <li className="flex items-center justify-between">Offline protection <Badge tone={s.data.privacy.strict_offline ? "green" : "amber"}>{s.data.privacy.strict_offline ? "On" : "Off"}</Badge></li>
              <li className="flex items-center justify-between">Telemetry <Badge tone="green">None</Badge></li>
              <li className="flex items-center justify-between">Cloud APIs <Badge tone="green">None</Badge></li>
            </ul>
            <div className="mt-4 space-y-2 text-xs text-slate-500">
              <div className="flex items-center gap-1.5 font-semibold uppercase tracking-wide"><HardDrive className="h-3.5 w-3.5" /> Where your data is stored</div>
              {Object.entries(s.data.storage).map(([k, v]) => <div key={k}><span className="font-medium text-slate-700">{k}:</span> <span className="break-all font-mono">{v}</span></div>)}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
