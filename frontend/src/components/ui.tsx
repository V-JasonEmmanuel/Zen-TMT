import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({ variant = "primary", size = "md", loading, icon, children, className = "", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode }) {
  const base = "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400";
  const sizes = { sm: "px-2.5 py-1.5 text-xs", md: "px-4 py-2 text-sm" };
  const variants: Record<Variant, string> = {
    primary: "bg-slate-900 text-white hover:bg-slate-700",
    secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-red-600 text-white hover:bg-red-700",
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} disabled={loading || rest.disabled} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ children, className = "", title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

const badgeTones = {
  slate: "bg-slate-100 text-slate-700", green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200", red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
};
export function Badge({ tone = "slate", children, title }: { tone?: keyof typeof badgeTones; children: ReactNode; title?: string }) {
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-transparent ${badgeTones[tone]}`}>{children}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Alert({ tone = "info", children, title }: { tone?: "info" | "warning" | "error" | "success"; children: ReactNode; title?: string }) {
  const map = {
    info: ["border-sky-200 bg-sky-50 text-sky-900", Info],
    warning: ["border-amber-200 bg-amber-50 text-amber-900", AlertTriangle],
    error: ["border-red-200 bg-red-50 text-red-900", XCircle],
    success: ["border-emerald-200 bg-emerald-50 text-emerald-900", CheckCircle2],
  } as const;
  const [cls, Icon] = map[tone];
  return (
    <div className={`flex gap-3 rounded-lg border px-4 py-3 text-sm ${cls}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        {title && <div className="font-semibold">{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      {icon && <div className="mb-3 text-slate-400">{icon}</div>}
      <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      {children && <p className="mt-1 max-w-md text-sm text-slate-500">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onMouseDown={onClose}>
      <div className={`flex max-h-[90vh] w-full flex-col rounded-xl bg-white shadow-2xl ${wide ? "max-w-4xl" : "max-w-lg"}`} onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="Close"><X className="h-4 w-4" /></button>
        </header>
        <div className="scrollbar-thin overflow-y-auto p-5">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; icon?: ReactNode; badge?: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition ${value === t.id ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
          {t.icon}{t.label}{t.badge}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50";

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className={`flex cursor-pointer items-center gap-3 text-sm ${disabled ? "opacity-50" : ""}`}>
      <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition ${checked ? "bg-slate-900" : "bg-slate-300"}`}>
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${checked ? "left-4.5" : "left-0.5"}`} />
      </button>
      {label}
    </label>
  );
}

export function ConfidenceBadge({ status, confidence }: { status: string; confidence: number }) {
  if (status === "structural") return null;
  const pct = Math.round(confidence * 100);
  if (status === "verified") return <Badge tone="green" title="Verified against the source document">✓ {pct}%</Badge>;
  if (status === "user_edited") {
    return confidence < 0.45
      ? <Badge tone="amber" title="Edited by you - this text (or a number in it) was not found in the source document">Edited · not in source</Badge>
      : <Badge tone="blue" title={`Edited by you · source match ${pct}%`}>Edited · {pct}%</Badge>;
  }
  if (status === "unsupported") return <Badge tone="red" title="Not supported by the source">Unsupported</Badge>;
  return <Badge tone="amber" title="Low source confidence - please review">Review · {pct}%</Badge>;
}
