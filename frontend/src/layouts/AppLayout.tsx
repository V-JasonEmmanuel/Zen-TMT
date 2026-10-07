import { FileStack, FolderOpen, GraduationCap, LayoutDashboard, LayoutTemplate, Library, Palette, Plus, Settings, ShieldCheck } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/new", label: "New project", icon: Plus },
  { to: "/projects", label: "Projects", icon: FolderOpen },
  { to: "/papers", label: "Research Papers", icon: GraduationCap },
  { to: "/brand-docs", label: "Brand Documents", icon: FileStack },
  { to: "/templates", label: "Templates", icon: LayoutTemplate },
  { to: "/media", label: "Media Library", icon: Library },
  { to: "/brands", label: "Brand Manager", icon: Palette },
  { to: "/settings", label: "Settings", icon: Settings },
];

function SystemPill() {
  const { data } = useAsync(() => api.status(), []);
  if (!data) return null;
  const ok = data.ready;
  return (
    <NavLink to="/settings" className="block rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : data.ollama.running ? "bg-amber-400" : "bg-red-400"}`} />
        <span className="font-medium text-slate-100">{ok ? "Local AI ready" : data.ollama.running ? "Select a local model" : "Local AI offline"}</span>
      </div>
      {data.offline_guard && (
        <div className="mt-1 flex items-center gap-1.5 text-slate-400"><ShieldCheck className="h-3.5 w-3.5" /> Offline mode · data stays local</div>
      )}
    </NavLink>
  );
}

export function AppLayout() {
  return (
    <div className="flex h-full">
      <aside className="flex w-60 shrink-0 flex-col bg-slate-900 text-slate-200">
        <div className="px-5 py-5">
          <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">Zensar</div>
          <div className="text-lg font-semibold text-white">Content Studio</div>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${isActive ? "bg-white/10 font-medium text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"}`}>
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3"><SystemPill /></div>
      </aside>
      <main className="scrollbar-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-8 py-8"><Outlet /></div>
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
