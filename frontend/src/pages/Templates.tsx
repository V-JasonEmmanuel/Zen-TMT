import { useState } from "react";
import { FileDrop } from "../components/FileDrop";
import { TemplateGallery } from "../components/TemplateGallery";
import { Alert, Card, Field, inputCls } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../layouts/AppLayout";
import { api } from "../services/api";

/** Browse design presets and upload PowerPoint templates for a brand. */
export function Templates() {
  const brands = useAsync(() => api.brands(), []);
  const [brandId, setBrandId] = useState("zensar");
  const [selected, setSelected] = useState("");
  const [msg, setMsg] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [key, setKey] = useState(0);

  const upload = async (files: File[]) => {
    setUploading(true);
    setMsg(null);
    try {
      const r = await api.uploadTemplate(brandId, files[0]);
      setMsg({ tone: "success", text: `${files[0].name} was added with ${((r.analysis.layouts as unknown[]) ?? []).length} layouts. Pick it when you create a project.` });
      setKey((k) => k + 1);
    } catch (e) { setMsg({ tone: "error", text: (e as Error).message }); }
    setUploading(false);
  };

  return (
    <>
      <PageHeader title="Presentation templates" subtitle="Every template uses the brand's official colours, fonts and logo; choose one per project in the New Project wizard." />
      <div className="space-y-6">
        <Card>
          <div className="grid gap-4 md:grid-cols-[16rem_1fr] md:items-end">
            <Field label="Brand">
              <select className={inputCls} value={brandId} onChange={(e) => setBrandId(e.target.value)}>
                {(brands.data ?? [{ id: "zensar", name: "Zensar" }]).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </Field>
            <FileDrop label={uploading ? "Analysing template…" : "Upload a PowerPoint template (.pptx)"} disabled={uploading} accept=".pptx"
              hint="Its slide size, layouts and theme are analysed; the file stays on this computer." onFiles={upload} />
          </div>
          {msg && <div className="mt-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
        </Card>
        <Card title="Gallery">
          <TemplateGallery key={`${brandId}-${key}`} brandId={brandId} value={selected} onChange={setSelected} />
          <p className="mt-4 text-xs text-slate-500">Previews show a cover, a process slide and a KPI slide rendered with sample text.</p>
        </Card>
      </div>
    </>
  );
}
