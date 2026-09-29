import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { FileDrop } from "../components/FileDrop";
import { MediaThumb, fmtTime } from "../components/MediaPicker";
import { Alert, Button, EmptyState, Modal, Spinner, Tabs, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";
import type { MediaAsset } from "../types";
import { bytes } from "../utils/format";

type Kind = "image" | "video" | "audio";

export function MediaLibrary() {
  const [kind, setKind] = useState<Kind>("image");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<MediaAsset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const lib = useAsync(() => api.media(kind, q), [kind, q]);

  const upload = async (files: File[]) => {
    setUploading(true);
    setError(null);
    try { await api.uploadMedia(files); await lib.reload(); } catch (e) { setError((e as Error).message); }
    setUploading(false);
  };
  const remove = async (a: MediaAsset) => {
    try { await api.deleteMedia(a.id); setOpen(null); await lib.reload(); } catch (e) { setError((e as Error).message); }
  };

  return (
    <>
      <PageHeader title="Media library" subtitle="Images, video clips and audio (music and narration) for your videos. Everything is stored on this computer." />
      <div className="space-y-5">
        <FileDrop multiple label={uploading ? "Uploading…" : "Drop images, videos or audio files here"} disabled={uploading}
          hint="PNG JPG WEBP GIF · MP4 MOV WEBM MKV · MP3 WAV M4A AAC OGG FLAC" onFiles={upload} />
        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <Tabs<Kind> value={kind} onChange={setKind} tabs={[{ id: "image", label: "Images" }, { id: "video", label: "Videos" }, { id: "audio", label: "Audio" }]} />
          <input className={`${inputCls} w-64`} placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {lib.loading && !lib.data ? <Spinner label="Loading…" /> : !lib.data?.length ? (
          <EmptyState title={`No ${kind === "audio" ? "audio files" : `${kind}s`} yet`}>Upload files above, or add them while creating a project.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {lib.data.map((a) => <button key={a.id} onClick={() => setOpen(a)} className="text-left"><MediaThumb asset={a} /></button>)}
          </div>
        )}
      </div>
      {open && (
        <Modal open wide title={open.filename} onClose={() => setOpen(null)} footer={<>
          <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => remove(open)}>Delete</Button>
          <a href={`${open.url}?download=true`}><Button variant="secondary" icon={<Download className="h-4 w-4" />}>Download</Button></a>
        </>}>
          <div className="space-y-3">
            {open.kind === "video" ? <video src={open.url} controls className="aspect-video w-full rounded-lg bg-black" />
              : open.kind === "audio" ? <audio src={open.url} controls className="w-full" />
                : <img src={open.url} alt={open.filename} className="max-h-[60vh] w-full rounded-lg object-contain" />}
            <p className="text-xs text-slate-500">
              {open.width ? `${open.width}×${open.height} · ` : ""}{open.duration ? `${fmtTime(open.duration)} · ` : ""}{bytes(open.bytes)} · {open.source_label}
            </p>
          </div>
        </Modal>
      )}
    </>
  );
}
