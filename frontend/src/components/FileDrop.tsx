import { UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

export function FileDrop({ accept, multiple, onFiles, label, hint, disabled }: {
  accept?: string; multiple?: boolean; onFiles: (files: File[]) => void; label: string; hint?: string; disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled && e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
      }}
      onClick={() => !disabled && ref.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && ref.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${over ? "border-slate-900 bg-slate-100" : "border-slate-300 bg-white hover:border-slate-400"} ${disabled ? "pointer-events-none opacity-60" : ""}`}
    >
      <UploadCloud className="mb-3 h-8 w-8 text-slate-400" />
      <div className="text-sm font-medium text-slate-800">{label}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
      <input ref={ref} type="file" className="hidden" accept={accept} multiple={multiple}
        onChange={(e) => { if (e.target.files?.length) onFiles(Array.from(e.target.files)); e.target.value = ""; }} />
    </div>
  );
}
