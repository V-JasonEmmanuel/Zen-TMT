import { Film, Music } from "lucide-react";
import { useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { MediaAsset } from "../types";
import { FileDrop } from "./FileDrop";
import { Button, EmptyState, Modal, Spinner, inputCls } from "./ui";

export const fmtTime = (s?: number | null) => {
  if (s === null || s === undefined || !isFinite(s)) return "–";
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
};

export function MediaThumb({ asset, className = "" }: { asset: Pick<MediaAsset, "kind" | "thumb_url" | "url" | "filename" | "duration">; className?: string }) {
  return (
    <div className={`relative aspect-video overflow-hidden rounded-lg bg-slate-100 ${className}`}>
      {asset.kind === "audio" ? (
        <div className="flex h-full items-center justify-center text-slate-400"><Music className="h-6 w-6" /></div>
      ) : asset.thumb_url || asset.kind === "image" ? (
        <img src={asset.thumb_url ?? asset.url} alt={asset.filename} loading="lazy" className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full items-center justify-center text-slate-400"><Film className="h-6 w-6" /></div>
      )}
      {asset.kind === "video" && <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px] text-white">{fmtTime(asset.duration)}</span>}
      <span className="absolute bottom-0 left-0 max-w-[75%] truncate bg-gradient-to-r from-black/60 to-transparent px-1.5 py-0.5 text-[10px] text-white">{asset.filename}</span>
    </div>
  );
}

const ACCEPT: Record<string, string> = {
  image: ".png,.jpg,.jpeg,.webp,.gif,.bmp",
  video: ".mp4,.mov,.webm,.mkv,.avi,.m4v",
  audio: ".mp3,.wav,.m4a,.aac,.ogg,.flac",
};

/** Choose (or upload) media library assets of the given kinds. */
export function MediaPicker({ kinds, title, onPick, onClose, multiple = false }: {
  kinds: ("image" | "video" | "audio")[]; title: string; onPick: (assets: MediaAsset[]) => void; onClose: () => void; multiple?: boolean;
}) {
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lib = useAsync(async () => (await Promise.all(kinds.map((k) => api.media(k, q)))).flat(), [kinds.join(), q]);
  const items = lib.data ?? [];

  const upload = async (files: File[]) => {
    setUploading(true);
    setError(null);
    try {
      const added = (await api.uploadMedia(files)).filter((a) => (kinds as string[]).includes(a.kind));
      await lib.reload();
      if (!multiple && added[0]) { onPick([added[0]]); return; }
      setPicked((p) => [...p, ...added.map((a) => a.id)]);
    } catch (e) { setError((e as Error).message); }
    setUploading(false);
  };

  return (
    <Modal open wide onClose={onClose} title={title} footer={multiple ? (
      <><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!picked.length} onClick={() => onPick(picked.map((id) => items.find((a) => a.id === id)!).filter(Boolean))}>Add {picked.length || ""}</Button></>
    ) : undefined}>
      <div className="space-y-4">
        <FileDrop multiple={multiple} label={uploading ? "Uploading…" : "Upload from this computer"} disabled={uploading}
          accept={kinds.map((k) => ACCEPT[k]).join(",")} onFiles={upload} />
        {error && <p className="text-sm text-red-700">{error}</p>}
        <input className={inputCls} placeholder="Search the media library" value={q} onChange={(e) => setQ(e.target.value)} />
        {lib.loading && !lib.data ? <Spinner label="Loading…" /> : items.length === 0 ? (
          <EmptyState title="Nothing in the library yet">Upload files above.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {items.map((a) => {
              const on = picked.includes(a.id);
              return (
                <button key={a.id} onClick={() => multiple ? setPicked(on ? picked.filter((x) => x !== a.id) : [...picked, a.id]) : onPick([a])}
                  className={`rounded-lg border-2 p-0.5 text-left ${on ? "border-slate-900" : "border-transparent hover:border-slate-300"}`}>
                  <MediaThumb asset={a} />
                </button>
              );
            })}
          </div>
        )}
      </div>
    </Modal>
  );
}
