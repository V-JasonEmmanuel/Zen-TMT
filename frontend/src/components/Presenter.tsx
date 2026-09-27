import { ChevronLeft, ChevronRight, StickyNote, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/** Full-screen, keyboard-driven presentation mode (←/→/Space/PageUp/PageDown, N = notes, Esc = exit). */
export function Presenter({ images, start, notes, onClose }: { images: string[]; start: number; notes: string[]; onClose: () => void }) {
  const [i, setI] = useState(start);
  const [showNotes, setShowNotes] = useState(false);
  const [chrome, setChrome] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>();

  const go = useCallback((d: number) => setI((x) => Math.min(images.length - 1, Math.max(0, x + d))), [images.length]);

  useEffect(() => {
    const el = ref.current;
    el?.requestFullscreen?.().catch(() => undefined);
    const onFs = () => { if (!document.fullscreenElement) onClose(); };
    document.addEventListener("fullscreenchange", onFs);
    return () => {
      document.removeEventListener("fullscreenchange", onFs);
      if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    };
  }, [onClose]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); go(1); }
      else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); go(-1); }
      else if (e.key === "Home") setI(0);
      else if (e.key === "End") setI(images.length - 1);
      else if (e.key.toLowerCase() === "n") setShowNotes((s) => !s);
      else if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [go, images.length, onClose]);

  const poke = () => {
    setChrome(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setChrome(false), 2200);
  };
  useEffect(() => { poke(); return () => clearTimeout(hideTimer.current); }, []);

  return (
    <div ref={ref} className="fixed inset-0 z-[60] flex flex-col bg-black" onMouseMove={poke}>
      <div className="relative flex flex-1 items-center justify-center" onClick={(e) => (e.clientX > window.innerWidth / 3 ? go(1) : go(-1))}>
        <img src={images[i]} alt={`Slide ${i + 1}`} className="max-h-full max-w-full select-none object-contain" draggable={false} />
      </div>
      {showNotes && notes[i] && (
        <div className="max-h-48 overflow-y-auto bg-slate-900/95 px-8 py-4 text-base leading-relaxed text-slate-100">{notes[i]}</div>
      )}
      <div className={`absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-6 py-4 text-sm text-white transition-opacity ${chrome ? "opacity-100" : "opacity-0"}`}>
        <div className="flex items-center gap-2">
          <button className="rounded-full p-2 hover:bg-white/15" onClick={() => go(-1)} aria-label="Previous"><ChevronLeft className="h-5 w-5" /></button>
          <span className="tabular-nums">{i + 1} / {images.length}</span>
          <button className="rounded-full p-2 hover:bg-white/15" onClick={() => go(1)} aria-label="Next"><ChevronRight className="h-5 w-5" /></button>
        </div>
        <div className="flex items-center gap-2">
          <button className={`flex items-center gap-1 rounded-full px-3 py-1.5 hover:bg-white/15 ${showNotes ? "bg-white/15" : ""}`} onClick={() => setShowNotes(!showNotes)}>
            <StickyNote className="h-4 w-4" /> Notes (N)
          </button>
          <button className="rounded-full p-2 hover:bg-white/15" onClick={onClose} aria-label="Exit"><X className="h-5 w-5" /></button>
        </div>
      </div>
    </div>
  );
}
