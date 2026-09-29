import {
  ArrowLeft, ArrowRight, Crop as CropIcon, Download, Film, Image as ImageIcon, Mic, Music, Pause, Play, Plus, Presentation,
  RotateCcw, Save, Scissors, Sparkles, Trash2, Wand2,
} from "lucide-react";
import { type PointerEvent as RPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api, fileUrl } from "../services/api";
import type { Crop, MediaAsset, OutputFile, Project, Timeline, TimelineClip, Transition } from "../types";
import { bytes } from "../utils/format";
import { FileDrop } from "./FileDrop";
import { MediaPicker, fmtTime } from "./MediaPicker";
import { Alert, Badge, Button, Card, Field, Modal, Spinner, Toggle, inputCls } from "./ui";

const TRANSITIONS: { id: Transition; label: string }[] = [
  { id: "zensar_grid", label: "Zensar grid" }, { id: "fade", label: "Fade" }, { id: "wipe", label: "Wipe" }, { id: "none", label: "Cut" },
];
const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
const ASPECTS: { label: string; ar: number | null }[] = [
  { label: "Full frame", ar: null }, { label: "16:9", ar: 16 / 9 }, { label: "4:3", ar: 4 / 3 }, { label: "1:1", ar: 1 }, { label: "9:16", ar: 9 / 16 },
];
const CAR = 16 / 9;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const r3 = (v: number) => Math.round(v * 1000) / 1000;
const FULL: Crop = { x: 0, y: 0, w: 1, h: 1 };

const sig = (tl: Timeline | null) => (tl ? JSON.stringify({ ...tl, rendered: undefined, updated_at: undefined }) : "");

function newClip(p: Partial<TimelineClip> & Pick<TimelineClip, "type">): TimelineClip {
  return {
    id: `clip_${Math.random().toString(36).slice(2, 12)}`, label: "", slide_number: null, asset_id: null, trim_start: 0, trim_end: null,
    speed: 1, crop: null, duration: 0, transition: "fade", motion: "subtle", keep_audio: true, audio_volume: 1, narration_text: "",
    narration_locked: false, narration_asset_id: null, narration_segments: [], source_duration: 0, ...p,
  };
}

/** Visible length of a clip in the output (null = automatic, from the narration). */
function clipSeconds(c: TimelineClip, rendered?: { start: number; end: number }): number | null {
  if (c.type === "video") {
    const end = c.trim_end ?? (c.source_duration || c.asset?.duration || 0);
    return end ? Math.max(0.1, (end - c.trim_start) / c.speed) : null;
  }
  if (c.duration) return c.duration;
  return rendered ? rendered.end - rendered.start : null;
}

const box = (ar: number, mode: "contain" | "cover") => {
  const wide = ar > CAR;
  const w = (mode === "contain") === wide ? 100 : (ar / CAR) * 100;
  const h = (mode === "contain") === wide ? (CAR / ar) * 100 : 100;
  return { width: `${w}%`, height: `${h}%`, left: `${(100 - w) / 2}%`, top: `${(100 - h) / 2}%` };
};

function aspectCrop(ar: number | null, srcAr: number): Crop {
  if (!ar) return FULL;
  const w = ar > srcAr ? 1 : ar / srcAr;
  const h = ar > srcAr ? srcAr / ar : 1;
  return { x: r3((1 - w) / 2), y: r3((1 - h) / 2), w: r3(w), h: r3(h) };
}

// ------------------------------------------------------------------ live clip preview (crop / trim / speed)
function CropOverlay({ crop, onChange, frame }: { crop: Crop; onChange: (c: Crop) => void; frame: React.RefObject<HTMLDivElement> }) {
  const start = (e: RPointerEvent, mode: "move" | "nw" | "se") => {
    e.preventDefault();
    e.stopPropagation();
    const r = frame.current!.getBoundingClientRect();
    const x0 = e.clientX, y0 = e.clientY, c0 = { ...crop };
    const move = (ev: PointerEvent) => {
      const dx = (ev.clientX - x0) / r.width, dy = (ev.clientY - y0) / r.height;
      const c = { ...c0 };
      if (mode === "move") { c.x = clamp(c0.x + dx, 0, 1 - c0.w); c.y = clamp(c0.y + dy, 0, 1 - c0.h); }
      else if (mode === "se") { c.w = clamp(c0.w + dx, 0.05, 1 - c0.x); c.h = clamp(c0.h + dy, 0.05, 1 - c0.y); }
      else {
        const nx = clamp(c0.x + dx, 0, c0.x + c0.w - 0.05), ny = clamp(c0.y + dy, 0, c0.y + c0.h - 0.05);
        c.w = c0.w + (c0.x - nx); c.h = c0.h + (c0.y - ny); c.x = nx; c.y = ny;
      }
      onChange({ x: r3(c.x), y: r3(c.y), w: r3(c.w), h: r3(c.h) });
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const handle = "absolute h-3.5 w-3.5 rounded-sm border-2 border-white bg-sky-500 shadow";
  return (
    <div className="absolute inset-0">
      <div role="slider" aria-label="Crop area" aria-valuenow={Math.round(crop.w * 100)} tabIndex={0} onPointerDown={(e) => start(e, "move")}
        className="absolute cursor-move border-2 border-sky-400 shadow-[0_0_0_9999px_rgba(0,0,0,0.55)]"
        style={{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%` }}>
        <span onPointerDown={(e) => start(e, "nw")} className={`${handle} -left-2 -top-2 cursor-nwse-resize`} />
        <span onPointerDown={(e) => start(e, "se")} className={`${handle} -bottom-2 -right-2 cursor-nwse-resize`} />
      </div>
    </div>
  );
}

function ClipPreview({ clip, onChange }: { clip: TimelineClip; onChange: (p: Partial<TimelineClip>) => void }) {
  const vref = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"edit" | "result">("result");
  const [t, setT] = useState(clip.trim_start);
  const [playing, setPlaying] = useState(false);
  const [natural, setNatural] = useState<[number, number] | null>(null);
  const a = clip.asset;
  const srcAr = natural ? natural[0] / natural[1] : a?.width && a?.height ? a.width / a.height : CAR;
  const crop = clip.crop ?? FULL;
  const isVideo = clip.type === "video";
  const dur = clip.source_duration || a?.duration || 0;
  const end = clip.trim_end ?? dur;

  useEffect(() => { if (vref.current) vref.current.playbackRate = clip.speed; }, [clip.speed, playing]);
  useEffect(() => { const v = vref.current; if (v && !playing) { v.currentTime = clip.trim_start; setT(clip.trim_start); } }, [clip.trim_start]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (vref.current) { vref.current.muted = !clip.keep_audio; vref.current.volume = Math.min(1, clip.audio_volume); } }, [clip.keep_audio, clip.audio_volume]);
  useEffect(() => { setMode(clip.crop ? "result" : "result"); setPlaying(false); setNatural(null); }, [clip.id]);

  if (clip.type === "slide" || clip.type === "intro" || clip.type === "outro") {
    return (
      <div className="relative aspect-video overflow-hidden rounded-xl bg-slate-900">
        {clip.thumb_url ? <img src={clip.thumb_url} alt={clip.label} className="h-full w-full object-contain" />
          : <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-300"><Sparkles className="h-8 w-8" />
            <span className="text-sm">{clip.type === "intro" ? "Animated brand intro" : clip.type === "outro" ? "Closing card" : clip.label}</span></div>}
        <span className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">Slides are animated when rendered</span>
      </div>
    );
  }
  if (!a) return <Alert tone="error">This clip's media file is missing from the library.</Alert>;

  const toggle = async () => {
    const v = vref.current;
    if (!v) return;
    if (v.paused) {
      if (v.currentTime < clip.trim_start || v.currentTime >= end - 0.05) v.currentTime = clip.trim_start;
      v.playbackRate = clip.speed;
      await v.play().catch(() => undefined);
    } else v.pause();
  };
  const media = isVideo ? (
    <video ref={vref} src={a.url} preload="auto" playsInline className="absolute inset-0 h-full w-full"
      onLoadedMetadata={(e) => { const v = e.currentTarget; setNatural([v.videoWidth, v.videoHeight]); v.currentTime = clip.trim_start; v.playbackRate = clip.speed; }}
      onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
      onTimeUpdate={(e) => { const v = e.currentTarget; setT(v.currentTime); if (end && v.currentTime >= end - 0.03) { v.currentTime = clip.trim_start; } }} />
  ) : (
    <img src={a.url} alt={a.filename} className="absolute inset-0 h-full w-full" onLoad={(e) => setNatural([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} />
  );
  const cropAr = (srcAr * crop.w) / crop.h;
  return (
    <div className="space-y-2">
      <div className="relative aspect-video overflow-hidden rounded-xl bg-black">
        {mode === "edit" ? (
          <div ref={frame} className="absolute" style={box(srcAr, "contain")}>
            {media}
            <CropOverlay crop={crop} frame={frame} onChange={(c) => onChange({ crop: c })} />
          </div>
        ) : (
          <div className="absolute overflow-hidden" style={box(cropAr, isVideo ? "contain" : "cover")}>
            <div className="absolute" style={{ width: `${100 / crop.w}%`, height: `${100 / crop.h}%`, left: `${(-crop.x / crop.w) * 100}%`, top: `${(-crop.y / crop.h) * 100}%` }}>{media}</div>
          </div>
        )}
        <div className="absolute right-2 top-2 flex overflow-hidden rounded-lg bg-black/60 text-xs text-white">
          <button className={`px-2.5 py-1 ${mode === "result" ? "bg-white/25" : ""}`} onClick={() => setMode("result")}>Result</button>
          <button className={`flex items-center gap-1 px-2.5 py-1 ${mode === "edit" ? "bg-white/25" : ""}`} onClick={() => setMode("edit")}><CropIcon className="h-3 w-3" /> Crop</button>
        </div>
      </div>
      {isVideo && (
        <div className="flex items-center gap-3">
          <Button size="sm" variant="secondary" onClick={toggle} icon={playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}>{playing ? "Pause" : "Play clip"}</Button>
          <TrimBar duration={dur} start={clip.trim_start} end={end} t={t} onSeek={(s) => { if (vref.current) vref.current.currentTime = s; setT(s); }} />
          <span className="w-24 text-right font-mono text-xs text-slate-600">{fmtTime(t)}</span>
        </div>
      )}
      {isVideo && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" icon={<Scissors className="h-3.5 w-3.5" />} disabled={t >= end - 0.2}
            onClick={() => onChange({ trim_start: r3(Math.max(0, t)) })}>Set start at playhead</Button>
          <Button size="sm" variant="ghost" icon={<Scissors className="h-3.5 w-3.5" />} disabled={t <= clip.trim_start + 0.2}
            onClick={() => onChange({ trim_end: r3(t) })}>Set end at playhead</Button>
          <span className="self-center text-xs text-slate-500">Plays the trimmed range at {clip.speed}× on loop - exactly what will be rendered.</span>
        </div>
      )}
      {mode === "edit" && (
        <div className="flex flex-wrap gap-1.5">
          {ASPECTS.map((x) => (
            <button key={x.label} onClick={() => onChange({ crop: x.ar ? aspectCrop(x.ar, srcAr) : null })}
              className="rounded-full border border-slate-200 px-2.5 py-1 text-xs hover:bg-slate-50">{x.label}</button>
          ))}
          <span className="self-center text-xs text-slate-500">Drag the box to move it; drag the corners to resize.</span>
        </div>
      )}
    </div>
  );
}

function TrimBar({ duration, start, end, t, onSeek }: { duration: number; start: number; end: number; t: number; onSeek: (s: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  if (!duration) return <div className="flex-1" />;
  const pct = (v: number) => `${clamp(v / duration, 0, 1) * 100}%`;
  return (
    <div ref={ref} role="slider" aria-label="Seek" aria-valuenow={Math.round(t)} tabIndex={0} className="relative h-6 flex-1 cursor-pointer rounded bg-slate-200"
      onClick={(e) => { const r = ref.current!.getBoundingClientRect(); onSeek(clamp((e.clientX - r.left) / r.width, 0, 1) * duration); }}>
      <div className="absolute inset-y-0 rounded bg-sky-300/70 ring-2 ring-sky-500" style={{ left: pct(start), width: `calc(${pct(end)} - ${pct(start)})` }} />
      <div className="absolute inset-y-[-3px] w-0.5 bg-red-600" style={{ left: pct(t) }} />
    </div>
  );
}

// ------------------------------------------------------------------ clip inspector
function Inspector({ clip, onChange, onRemove, onMove, slides, pickAudio }: {
  clip: TimelineClip; onChange: (p: Partial<TimelineClip>) => void; onRemove: () => void; onMove: (d: -1 | 1) => void;
  slides: number[]; pickAudio: (cb: (a: MediaAsset) => void) => void;
}) {
  const dur = clip.source_duration || clip.asset?.duration || 0;
  const end = clip.trim_end ?? dur;
  const out = clipSeconds(clip);
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <ClipPreview clip={clip} onChange={onChange} />
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <input className={`${inputCls} flex-1`} value={clip.label} onChange={(e) => onChange({ label: e.target.value })} aria-label="Clip name" />
          <Button size="sm" variant="ghost" onClick={() => onMove(-1)} aria-label="Move earlier"><ArrowLeft className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => onMove(1)} aria-label="Move later"><ArrowRight className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={onRemove} aria-label="Remove clip"><Trash2 className="h-4 w-4 text-red-600" /></Button>
        </div>

        {clip.type === "video" && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label={`Trim start · ${fmtTime(clip.trim_start)}`}>
                <input type="range" className="w-full" min={0} max={dur || 1} step={0.1} value={clip.trim_start}
                  onChange={(e) => onChange({ trim_start: Math.min(Number(e.target.value), end - 0.2) })} />
              </Field>
              <Field label={`Trim end · ${fmtTime(end)}`}>
                <input type="range" className="w-full" min={0} max={dur || 1} step={0.1} value={end}
                  onChange={(e) => { const v = Math.max(Number(e.target.value), clip.trim_start + 0.2); onChange({ trim_end: v >= dur - 0.05 ? null : v }); }} />
              </Field>
            </div>
            <Field label={`Speed · ${clip.speed}×`}>
              <div className="flex flex-wrap gap-1.5">
                {SPEEDS.map((s) => (
                  <button key={s} onClick={() => onChange({ speed: s })}
                    className={`rounded-md border px-2 py-1 text-xs ${clip.speed === s ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 hover:bg-slate-50"}`}>{s}×</button>
                ))}
              </div>
            </Field>
            <p className="text-xs text-slate-500">Source {fmtTime(dur)} → in the video {fmtTime(out)}{clip.crop ? ` · cropped to ${Math.round(clip.crop.w * 100)}% × ${Math.round(clip.crop.h * 100)}%` : ""}</p>
            {clip.asset?.has_audio && (
              <div className="grid grid-cols-2 items-end gap-3">
                <Toggle checked={clip.keep_audio} onChange={(v) => onChange({ keep_audio: v })} label="Keep original sound" />
                <Field label={`Sound volume · ${Math.round(clip.audio_volume * 100)}%`}>
                  <input type="range" className="w-full" min={0} max={2} step={0.05} value={clip.audio_volume} disabled={!clip.keep_audio}
                    onChange={(e) => onChange({ audio_volume: Number(e.target.value) })} />
                </Field>
              </div>
            )}
          </>
        )}

        {clip.type !== "video" && (
          <Field label={clip.duration ? `Duration · ${clip.duration.toFixed(1)} s` : "Duration · automatic (fits the narration)"}>
            <div className="flex items-center gap-2">
              <input type="range" className="flex-1" min={0} max={30} step={0.5} value={clip.duration} onChange={(e) => onChange({ duration: Number(e.target.value) })} />
              {clip.duration > 0 && <Button size="sm" variant="ghost" onClick={() => onChange({ duration: 0 })}>Auto</Button>}
            </div>
          </Field>
        )}
        {clip.type === "slide" && (
          <Field label="Slide">
            <select className={inputCls} value={clip.slide_number ?? ""} onChange={(e) => onChange({ slide_number: Number(e.target.value), thumb_url: undefined })}>
              {slides.map((n) => <option key={n} value={n}>Slide {n}</option>)}
            </select>
          </Field>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Transition in">
            <select className={inputCls} value={clip.transition} onChange={(e) => onChange({ transition: e.target.value as Transition })}>
              {TRANSITIONS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </Field>
          {clip.type !== "video" && clip.type !== "intro" && clip.type !== "outro" && (
            <Field label="Motion">
              <select className={inputCls} value={clip.motion} onChange={(e) => onChange({ motion: e.target.value as TimelineClip["motion"] })}>
                <option value="subtle">{clip.type === "slide" ? "Animated builds" : "Still"}</option>
                <option value="ken_burns">{clip.type === "slide" ? "Builds + slow zoom" : "Slow zoom (Ken Burns)"}</option>
                <option value="none">Static</option>
              </select>
            </Field>
          )}
        </div>

        {clip.type !== "intro" && clip.type !== "outro" && (
          <div className="space-y-2 rounded-lg border border-slate-200 p-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500"><Mic className="h-3.5 w-3.5" /> Narration for this clip</span>
              {clip.narration_asset ? (
                <span className="flex items-center gap-2 text-xs"><Badge tone="blue">{clip.narration_asset.filename}</Badge>
                  <button className="text-red-600 hover:underline" onClick={() => onChange({ narration_asset_id: null, narration_asset: null })}>Remove</button></span>
              ) : (
                <Button size="sm" variant="secondary" icon={<Mic className="h-3.5 w-3.5" />}
                  onClick={() => pickAudio((a) => onChange({ narration_asset_id: a.id, narration_asset: { id: a.id, filename: a.filename, duration: a.duration } }))}>Use my recording</Button>
              )}
            </div>
            {clip.narration_asset ? <p className="text-xs text-slate-500">Your recording replaces the generated voice for this clip; still clips stretch to fit it.</p>
              : clip.narration_segments.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-xs text-slate-500">Scene-by-scene narration written from the video frames. Each line is spoken when its scene is on screen.</p>
                  {clip.narration_segments.map((s, i) => (
                    <div key={i} className={`flex gap-2 ${s.end <= clip.trim_start || s.start >= end ? "opacity-40" : ""}`}>
                      <span className="w-20 shrink-0 pt-1.5 font-mono text-[11px] text-slate-500">{fmtTime(s.start)}–{fmtTime(s.end)}</span>
                      <textarea className={`${inputCls} min-h-14 text-xs`} value={s.text}
                        onChange={(e) => onChange({ narration_locked: true, narration_segments: clip.narration_segments.map((x, j) => j === i ? { ...x, text: e.target.value } : x) })} />
                    </div>
                  ))}
                </div>
              ) : (
                <textarea className={`${inputCls} min-h-24 text-sm`} value={clip.narration_text} placeholder={clip.type === "slide" ? "Generated from the slide" : "Optional words to say over this clip"}
                  onChange={(e) => onChange({ narration_text: e.target.value, narration_locked: true })} />
              )}
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ editor
export function VideoEditor({ project, outputs, version, busy, onJob }: {
  project: Project; outputs: OutputFile[]; version: string; busy: boolean; onJob: (jobId: string) => void;
}) {
  const [tl, setTl] = useState<Timeline | null>(null);
  const [saved, setSaved] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [picker, setPicker] = useState<null | { kinds: ("image" | "video" | "audio")[]; title: string; multiple?: boolean; cb: (a: MediaAsset[]) => void }>(null);
  const [adding, setAdding] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [player, setPlayer] = useState<"preview" | "final">("final");
  const [drag, setDrag] = useState<string | null>(null);
  const playerRef = useRef<HTMLVideoElement>(null);
  const status = useAsync(() => api.status(), []);
  const voices = useMemo(() => Object.entries(status.data?.tts.engines ?? {}).flatMap(([e, vs]) => vs.map((v) => ({ engine: e, v }))), [status.data]);
  const dirty = !!tl && sig(tl) !== saved;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  const load = useCallback(async () => {
    try {
      const t = await api.timeline(project.id);
      setTl(t);
      setSaved(sig(t));
      setSel((s) => s ?? t.clips[0]?.id ?? null);
      setError(null);
    } catch (e) { setError((e as Error).message); }
  }, [project.id]);
  useEffect(() => { if (!dirtyRef.current) load(); }, [load, version]);

  const finalVideo = outputs.find((o) => o.kind === "video");
  const vtt = outputs.find((o) => o.path.endsWith(".vtt"));
  const hasPreview = !!tl?.rendered.preview;
  useEffect(() => { if (!finalVideo && hasPreview) setPlayer("preview"); }, [finalVideo, hasPreview]);

  if (error && !tl) return <Alert tone="error">{error}</Alert>;
  if (!tl) return <Spinner label="Loading the video timeline…" />;

  const rendered = tl.rendered[player];
  const renderedClip = (id: string) => rendered?.clips.find((c) => c.id === id);
  const clip = tl.clips.find((c) => c.id === sel) ?? null;
  const slides = tl.clips.filter((c) => c.type === "slide").map((c) => c.slide_number!).filter((n, i, a) => a.indexOf(n) === i).sort((a, b) => a - b);
  const total = tl.clips.reduce((s, c) => s + (clipSeconds(c, renderedClip(c.id)) ?? 6), 0);

  const set = (p: Partial<Timeline>) => setTl({ ...tl, ...p });
  const patchClip = (id: string, p: Partial<TimelineClip>) => set({ clips: tl.clips.map((c) => (c.id === id ? { ...c, ...p } : c)) });
  const insert = (items: TimelineClip[]) => {
    const i = sel ? tl.clips.findIndex((c) => c.id === sel) + 1 : tl.clips.length;
    const at = i > 0 ? i : tl.clips.length;
    set({ clips: [...tl.clips.slice(0, at), ...items, ...tl.clips.slice(at)] });
    if (items[0]) setSel(items[0].id);
  };
  const move = (id: string, d: -1 | 1) => {
    const i = tl.clips.findIndex((c) => c.id === id), j = i + d;
    if (j < 0 || j >= tl.clips.length) return;
    const clips = [...tl.clips];
    [clips[i], clips[j]] = [clips[j], clips[i]];
    set({ clips });
  };
  const dropOn = (target: string) => {
    if (!drag || drag === target) return;
    const clips = tl.clips.filter((c) => c.id !== drag);
    const moved = tl.clips.find((c) => c.id === drag)!;
    clips.splice(clips.findIndex((c) => c.id === target), 0, moved);
    set({ clips });
    setDrag(null);
  };
  const pickAudio = (cb: (a: MediaAsset) => void) => setPicker({ kinds: ["audio"], title: "Choose a recording", cb: (a) => a[0] && cb(a[0]) });

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const t = await api.saveTimeline(project.id, tl);
      setTl(t);
      setSaved(sig(t));
      return true;
    } catch (e) { setError((e as Error).message); return false; } finally { setSaving(false); }
  };
  const render = async (quality: "preview" | "final") => {
    if (dirty && !(await save())) return;
    try {
      const j = await api.renderVideo(project.id, quality);
      setPlayer(quality);
      onJob(j.id);
    } catch (e) { setError((e as Error).message); }
  };
  const importScript = async (files: File[]) => {
    try { set({ narration: { ...tl.narration, script: (await api.parseScript(files[0])).script } }); } catch (e) { setError((e as Error).message); }
  };
  const seekPlayer = (id: string) => {
    const r = renderedClip(id);
    if (r && playerRef.current) playerRef.current.currentTime = r.start + 0.05;
  };

  const src = player === "final" ? finalVideo?.path : hasPreview ? "video/preview.mp4" : undefined;

  return (
    <div className="space-y-6">
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-slate-600">{tl.clips.length} clips · about {fmtTime(total)}{dirty && <Badge tone="amber">Unsaved changes</Badge>}</div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setConfirmReset(true)} disabled={busy}>Rebuild from slides</Button>
          <Button variant="secondary" size="sm" icon={<Save className="h-3.5 w-3.5" />} onClick={save} loading={saving} disabled={!dirty}>Save</Button>
          <Button variant="secondary" size="sm" icon={<Play className="h-3.5 w-3.5" />} onClick={() => render("preview")} disabled={busy}>Render preview</Button>
          <Button size="sm" icon={<Film className="h-3.5 w-3.5" />} onClick={() => render("final")} disabled={busy}>Render final video</Button>
        </div>
      </div>

      {/* rendered player */}
      <Card title={<span className="flex items-center gap-3">Rendered video
        <span className="flex overflow-hidden rounded-md border border-slate-200 text-xs font-normal">
          <button className={`px-2 py-0.5 ${player === "final" ? "bg-slate-900 text-white" : ""}`} onClick={() => setPlayer("final")}>Final</button>
          <button className={`px-2 py-0.5 ${player === "preview" ? "bg-slate-900 text-white" : ""}`} onClick={() => setPlayer("preview")}>Quick preview</button>
        </span></span>}
        actions={player === "final" && finalVideo ? <a href={fileUrl(project.id, finalVideo.path, { download: true })}><Button size="sm" icon={<Download className="h-3.5 w-3.5" />}>Download MP4 · {bytes(finalVideo.size)}</Button></a> : undefined}>
        {src ? (
          <div className="mx-auto max-w-4xl overflow-hidden rounded-xl bg-black">
            <video ref={playerRef} key={`${src}-${version}`} controls preload="metadata" className="aspect-video w-full" crossOrigin="anonymous">
              <source src={fileUrl(project.id, src, { v: version })} type="video/mp4" />
              {player === "final" && vtt && <track kind="subtitles" srcLang="en" label="English" src={fileUrl(project.id, vtt.path, { v: version })} default />}
            </video>
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-slate-500">{player === "final" ? "No final video yet." : "No preview yet."} Edit the timeline below, then use <b>Render preview</b> (fast, lower resolution) or <b>Render final video</b>.</p>
        )}
        {rendered && dirty && <p className="mt-2 text-xs text-amber-700">The timeline changed since this was rendered - render again to see the edits.</p>}
      </Card>

      {/* timeline strip */}
      <Card title="Timeline" actions={<Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>Add</Button>}>
        <div className="scrollbar-thin flex gap-2 overflow-x-auto pb-2" role="list">
          {tl.clips.map((c, i) => {
            const secs = clipSeconds(c, renderedClip(c.id));
            const thumb = c.thumb_url ?? c.asset?.thumb_url ?? (c.asset?.kind === "image" ? c.asset.url : null);
            const Icon = c.type === "slide" ? Presentation : c.type === "video" ? Film : c.type === "image" ? ImageIcon : Sparkles;
            return (
              <div key={c.id} role="listitem" draggable onDragStart={() => setDrag(c.id)} onDragOver={(e) => e.preventDefault()} onDrop={() => dropOn(c.id)}
                onClick={() => { setSel(c.id); seekPlayer(c.id); }}
                className={`relative shrink-0 cursor-pointer overflow-hidden rounded-lg border-2 bg-white transition ${sel === c.id ? "border-slate-900" : "border-slate-200 hover:border-slate-400"} ${drag === c.id ? "opacity-40" : ""}`}
                style={{ width: Math.min(260, Math.max(112, (secs ?? 6) * 12)) }}>
                <div className="relative h-16 bg-slate-800">
                  {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" draggable={false} /> : <div className="flex h-full items-center justify-center text-slate-400"><Icon className="h-5 w-5" /></div>}
                  <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] text-white">{i + 1}</span>
                  <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 text-[10px] text-white">{secs ? `${secs.toFixed(1)}s` : "auto"}</span>
                  {c.speed !== 1 && <span className="absolute right-1 top-1 rounded bg-sky-600 px-1 text-[10px] text-white">{c.speed}×</span>}
                  {c.crop && <CropIcon className="absolute left-6 top-1 h-3 w-3 text-sky-300" />}
                  {c.narration_asset_id && <Mic className="absolute bottom-1 left-1 h-3 w-3 text-emerald-300" />}
                </div>
                <div className="flex items-center gap-1 px-1.5 py-1 text-[11px]"><Icon className="h-3 w-3 shrink-0 text-slate-400" /><span className="truncate">{c.label || c.type}</span></div>
              </div>
            );
          })}
        </div>
        {tl.clips.length === 0 && <p className="text-sm text-slate-500">The timeline is empty. Add clips or rebuild it from the slides.</p>}
        <p className="mt-1 text-xs text-slate-500">Drag clips to reorder. Click a clip to edit it (and jump there in the rendered video).</p>
      </Card>

      {clip && (
        <Card title={<span className="flex items-center gap-2"><Wand2 className="h-4 w-4" /> Edit clip</span>}>
          <Inspector key={clip.id} clip={clip} slides={slides} pickAudio={pickAudio} onChange={(p) => patchClip(clip.id, p)} onMove={(d) => move(clip.id, d)}
            onRemove={() => { const i = tl.clips.findIndex((c) => c.id === clip.id); set({ clips: tl.clips.filter((c) => c.id !== clip.id) }); setSel(tl.clips[i + 1]?.id ?? tl.clips[i - 1]?.id ?? null); }} />
        </Card>
      )}

      {/* audio */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Mic className="h-4 w-4" /> Narration</span>}>
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {([["tts", "Offline voice"], ["upload", "My recording"], ["none", "None"]] as const).map(([id, label]) => (
                <button key={id} onClick={() => set({ narration: { ...tl.narration, mode: id } })}
                  className={`rounded-lg border-2 px-3 py-1.5 text-sm ${tl.narration.mode === id ? "border-slate-900 bg-slate-50 font-semibold" : "border-slate-200"}`}>{label}</button>
              ))}
            </div>
            {tl.narration.mode === "tts" && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Voice">
                    <select className={inputCls} value={tl.narration.voice} onChange={(e) => set({ narration: { ...tl.narration, voice: e.target.value } })}>
                      <option value="">Default voice</option>
                      {voices.map(({ engine, v }) => <option key={engine + v} value={v}>{v} ({engine})</option>)}
                    </select>
                  </Field>
                  <Field label={`Speed · ${tl.narration.speed.toFixed(2)}×`}>
                    <input type="range" className="w-full" min={0.7} max={1.4} step={0.05} value={tl.narration.speed} onChange={(e) => set({ narration: { ...tl.narration, speed: Number(e.target.value) } })} />
                  </Field>
                </div>
                <Field label="Script" hint={<>Overrides the generated narration. Use <code>## Slide 3</code> markers to target slides, or <code>---</code> between sections; plain text is spread across the clips.</>}>
                  <textarea className={`${inputCls} min-h-32 font-mono text-xs`} value={tl.narration.script} maxLength={100000}
                    onChange={(e) => set({ narration: { ...tl.narration, script: e.target.value } })} placeholder="Leave empty to use the narration written for each slide and scene" />
                </Field>
                <FileDrop label="Import script" hint=".txt .md .docx .srt .vtt" accept=".txt,.md,.docx,.srt,.vtt" onFiles={importScript} />
              </>
            )}
            {tl.narration.mode === "upload" && (
              tl.narration.asset ? (
                <div className="flex items-center gap-2 rounded-lg border border-slate-200 p-3 text-sm">
                  <Music className="h-4 w-4 text-slate-500" /><span className="flex-1 truncate">{tl.narration.asset.filename}</span>
                  {tl.narration.asset.duration ? <Badge>{fmtTime(tl.narration.asset.duration)}</Badge> : null}
                  <Button size="sm" variant="ghost" onClick={() => set({ narration: { ...tl.narration, asset_id: null, asset: null } })}>Remove</Button>
                </div>
              ) : (
                <Button variant="secondary" icon={<Mic className="h-4 w-4" />}
                  onClick={() => pickAudio((a) => set({ narration: { ...tl.narration, asset_id: a.id, asset: { id: a.id, filename: a.filename, duration: a.duration } } }))}>Upload or choose your narration</Button>
              )
            )}
            <Toggle checked={tl.subtitles} onChange={(v) => set({ subtitles: v })} label="Subtitles (.srt / .vtt)" />
          </div>
        </Card>
        <Card title={<span className="flex items-center gap-2"><Music className="h-4 w-4" /> Background music</span>}>
          <div className="space-y-4">
            {tl.music.asset ? (
              <div className="flex items-center gap-2 rounded-lg border border-slate-200 p-3 text-sm">
                <Music className="h-4 w-4 text-slate-500" /><span className="flex-1 truncate">{tl.music.asset.filename}</span>
                {tl.music.asset.duration ? <Badge>{fmtTime(tl.music.asset.duration)}</Badge> : null}
                <Button size="sm" variant="ghost" onClick={() => set({ music: { ...tl.music, asset_id: null, asset: null } })}>Remove</Button>
              </div>
            ) : (
              <Button variant="secondary" icon={<Music className="h-4 w-4" />}
                onClick={() => pickAudio((a) => set({ music: { ...tl.music, asset_id: a.id, asset: { id: a.id, filename: a.filename, duration: a.duration } } }))}>Add music</Button>
            )}
            <Field label={`Volume · ${Math.round(tl.music.volume * 100)}%`}>
              <input type="range" className="w-full" min={0} max={1} step={0.01} value={tl.music.volume} onChange={(e) => set({ music: { ...tl.music, volume: Number(e.target.value) } })} />
            </Field>
            <Toggle checked={tl.music.duck} onChange={(v) => set({ music: { ...tl.music, duck: v } })} label="Lower the music while narration plays" />
            <div className="grid grid-cols-2 gap-3">
              <Field label={`Fade in · ${tl.music.fade_in.toFixed(1)} s`}>
                <input type="range" className="w-full" min={0} max={8} step={0.5} value={tl.music.fade_in} onChange={(e) => set({ music: { ...tl.music, fade_in: Number(e.target.value) } })} />
              </Field>
              <Field label={`Fade out · ${tl.music.fade_out.toFixed(1)} s`}>
                <input type="range" className="w-full" min={0} max={8} step={0.5} value={tl.music.fade_out} onChange={(e) => set({ music: { ...tl.music, fade_out: Number(e.target.value) } })} />
              </Field>
            </div>
            <p className="text-xs text-slate-500">Music loops to the length of the video.</p>
          </div>
        </Card>
      </div>

      {adding && (
        <Modal open title="Add to the timeline" onClose={() => setAdding(false)}>
          <div className="grid gap-2">
            <Button variant="secondary" icon={<ImageIcon className="h-4 w-4" />} onClick={() => {
              setAdding(false);
              setPicker({
                kinds: ["image", "video"], title: "Add images or video clips", multiple: true,
                cb: (assets) => insert(assets.map((a) => newClip({
                  type: a.kind === "video" ? "video" : "image", asset_id: a.id, label: a.filename.replace(/\.[^.]+$/, ""),
                  duration: a.kind === "video" ? 0 : 5, source_duration: a.duration ?? 0, motion: a.kind === "video" ? "none" : "ken_burns",
                  asset: { id: a.id, kind: a.kind, filename: a.filename, url: a.url, thumb_url: a.thumb_url, duration: a.duration, width: a.width, height: a.height, has_audio: !!a.meta?.has_audio },
                }))),
              });
            }}>Images or video clips</Button>
            {slides.length > 0 && (
              <Button variant="secondary" icon={<Presentation className="h-4 w-4" />} onClick={() => {
                setAdding(false);
                insert([newClip({ type: "slide", slide_number: slides[0], label: `Slide ${slides[0]}`, transition: "zensar_grid" })]);
              }}>A slide (choose which in the clip editor)</Button>
            )}
            <Button variant="secondary" icon={<Sparkles className="h-4 w-4" />} onClick={() => { setAdding(false); insert([newClip({ type: "intro", label: "Brand intro", transition: "none" })]); }}>Animated brand intro</Button>
            <Button variant="secondary" icon={<Sparkles className="h-4 w-4" />} onClick={() => { setAdding(false); insert([newClip({ type: "outro", label: "Closing card" })]); }}>Closing card</Button>
          </div>
        </Modal>
      )}
      {picker && <MediaPicker kinds={picker.kinds} title={picker.title} multiple={picker.multiple} onClose={() => setPicker(null)} onPick={(a) => { setPicker(null); picker.cb(a); }} />}
      {confirmReset && (
        <Modal open title="Rebuild the timeline?" onClose={() => setConfirmReset(false)} footer={<>
          <Button variant="secondary" onClick={() => setConfirmReset(false)}>Cancel</Button>
          <Button variant="danger" onClick={async () => { setConfirmReset(false); try { const t = await api.resetTimeline(project.id); setTl(t); setSaved(sig(t)); setSel(t.clips[0]?.id ?? null); } catch (e) { setError((e as Error).message); } }}>Rebuild</Button>
        </>}>
          <p className="text-sm text-slate-600">This replaces your clip edits (order, trims, crops, speeds, added media and narration changes) with a fresh timeline built from the current slides and the project's video settings.</p>
        </Modal>
      )}
    </div>
  );
}
