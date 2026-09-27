import { ArrowRight, Check, Cpu, FilePlus2, Palette, Presentation } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Card } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { ModelPicker } from "./Settings";

export function Welcome() {
  const nav = useNavigate();
  const status = useAsync(() => api.status(), []);
  const settings = useAsync(() => api.settings(), []);
  const brands = useAsync(() => api.brands(), []);
  const [model, setModel] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const zensar = brands.data?.find((b) => b.id === "zensar");
  const current = model ?? settings.data?.settings.ollama_model ?? "";

  const finish = async (to: string) => {
    await api.saveSettings({ onboarding_complete: true, ...(model !== null ? { ollama_model: model } : {}) });
    nav(to);
  };

  const steps = [
    {
      icon: Cpu, title: "Configure local AI", done: !!status.data?.ollama.model_ready || saved,
      body: (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Choose the installed Ollama model used to understand your instructions and write concise slide text. It runs entirely on this computer.</p>
          <ModelPicker value={current} onChange={setModel} />
          {model !== null && <Button size="sm" onClick={async () => { await api.saveSettings({ ollama_model: model }); setSaved(true); status.reload(); }}>Use this model</Button>}
          <p className="text-xs text-slate-500">No model? You can still generate presentations in fast extractive mode.</p>
        </div>
      ),
    },
    {
      icon: Palette, title: "Configure the Zensar brand", done: zensar?.status === "configured",
      body: (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Outputs follow the brand profile exactly. Set the official colours, fonts and logo - nothing is invented.</p>
          {zensar && zensar.status !== "configured" && <Alert tone="info">The Zensar profile is currently <b>{zensar.status}</b>. Until it is configured, outputs use neutral placeholder styling.</Alert>}
          <Link to="/brands/zensar"><Button size="sm" variant="secondary">Open Zensar brand</Button></Link>
        </div>
      ),
    },
    {
      icon: Presentation, title: "Add reference templates", done: false,
      body: (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Upload the Zensar PowerPoint template and reference slide images in the Brand Manager. Colours, fonts, slide size and the master logo are extracted as suggestions for you to confirm.</p>
          <Link to="/brands/zensar"><Button size="sm" variant="secondary">Upload template</Button></Link>
        </div>
      ),
    },
    {
      icon: FilePlus2, title: "Create your first project", done: false,
      body: (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Upload a document, describe the presentation you need, and generate slides, visuals and video.</p>
          <Button size="sm" onClick={() => finish("/new")}>Create a project <ArrowRight className="h-4 w-4" /></Button>
        </div>
      ),
    },
  ];

  return (
    <div className="min-h-full bg-slate-50 py-12">
      <div className="mx-auto max-w-3xl px-6">
        <div className="mb-8 text-center">
          <div className="text-xs font-semibold uppercase tracking-widest text-slate-500">Zensar</div>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Welcome to Content Studio</h1>
          <p className="mt-2 text-slate-500">Turn documents into on-brand presentations, visuals and videos - privately, on this computer.</p>
        </div>
        <div className="space-y-4">
          {steps.map((s, i) => (
            <Card key={s.title}>
              <div className="flex gap-4">
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${s.done ? "bg-emerald-600 text-white" : "bg-slate-900 text-white"}`}>
                  {s.done ? <Check className="h-5 w-5" /> : <s.icon className="h-5 w-5" />}
                </div>
                <div className="flex-1">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Step {i + 1}</div>
                  <h2 className="mb-2 text-lg font-semibold">{s.title}</h2>
                  {s.body}
                </div>
              </div>
            </Card>
          ))}
        </div>
        <div className="mt-8 text-center">
          <button className="text-sm font-medium text-slate-500 hover:text-slate-800" onClick={() => finish("/")}>Skip for now and go to the dashboard</button>
        </div>
      </div>
    </div>
  );
}
