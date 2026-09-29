import type {
  BrandSummary, BrandView, ContentPlan, Contract, DocumentInfo, Job, MediaAsset, OutputFile, Project, RuntimeSettings,
  SourceMapping, Suggestion, SystemStatus, TemplateItem, Timeline,
} from "../types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  } catch {
    throw new ApiError("Cannot reach the Content Studio service. Is the backend running?", 0);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch { /* not json */ }
    throw new ApiError(msg || `Request failed (${res.status})`, res.status);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.text() as unknown)) as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  // documents
  uploadDocument(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return request<DocumentInfo>("/api/documents/upload", { method: "POST", body: fd });
  },
  importGithub: (url: string, token = "") => request<DocumentInfo>("/api/documents/github", { method: "POST", body: json({ url, token }) }),
  documents: () => request<DocumentInfo[]>("/api/documents"),
  document: (id: string) => request<DocumentInfo>(`/api/documents/${id}`),
  formats: () => request<{ extensions: string[] }>("/api/documents/formats"),

  // projects
  projects: () => request<Project[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (body: Partial<Project> & { name: string; document_id?: string; document_ids?: string[]; instruction: string }) =>
    request<Project>("/api/projects", { method: "POST", body: json(body) }),
  updateProject: (id: string, body: Partial<Pick<Project, "name" | "brand_id" | "instruction" | "output_formats" | "options">>) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", body: json(body) }),
  deleteProject: (id: string) => request<{ deleted: string }>(`/api/projects/${id}`, { method: "DELETE" }),
  plan: (id: string) => request<ContentPlan>(`/api/projects/${id}/plan`),
  layouts: (id: string) => request<{ id: string; guidance: string }[]>(`/api/projects/${id}/layouts`),
  editSlide: (id: string, n: number, body: Record<string, unknown>) =>
    request<{ plan_version: number; job: Job }>(`/api/projects/${id}/plan/slides/${n}`, { method: "PUT", body: json(body) }),
  regenerateSlide: (id: string, n: number, body: { layout?: string | null; guidance?: string }) =>
    request<Job>(`/api/projects/${id}/slides/${n}/regenerate`, { method: "POST", body: json(body) }),
  sources: (id: string) => request<SourceMapping>(`/api/projects/${id}/sources`),
  outputs: (id: string) => request<OutputFile[]>(`/api/projects/${id}/outputs`),

  // generation
  parseInstruction: (instruction: string) => request<Contract>("/api/instruction/parse", { method: "POST", body: json({ instruction }) }),
  generate: (project_id: string, kind: "full" | "render" | "video" = "full", include_video = false) =>
    request<Job>("/api/generate", { method: "POST", body: json({ project_id, kind, include_video }) }),
  job: (id: string) => request<Job>(`/api/generation/${id}`),
  cancelJob: (id: string) => request<{ cancelling: string }>(`/api/generation/${id}/cancel`, { method: "POST" }),

  // video editor
  timeline: (id: string) => request<Timeline>(`/api/projects/${id}/timeline`),
  saveTimeline: (id: string, tl: Timeline) => request<Timeline>(`/api/projects/${id}/timeline`, { method: "PUT", body: json(tl) }),
  resetTimeline: (id: string) => request<Timeline>(`/api/projects/${id}/timeline/reset`, { method: "POST" }),
  renderVideo: (id: string, quality: "preview" | "final") => request<Job>(`/api/projects/${id}/video/render`, { method: "POST", body: json({ quality }) }),
  parseScript(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ script: string; sections: number }>("/api/scripts/parse", { method: "POST", body: fd });
  },

  // media library
  media: (kind?: string, q = "") => request<MediaAsset[]>(`/api/media?${new URLSearchParams({ ...(kind ? { kind } : {}), q })}`),
  uploadMedia(files: File[], category = "other") {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("category", category);
    return request<MediaAsset[]>("/api/media/upload", { method: "POST", body: fd });
  },
  deleteMedia: (id: string) => request<unknown>(`/api/media/${id}`, { method: "DELETE" }),

  // templates
  templateGallery: (brandId: string) => request<TemplateItem[]>(`/api/templates/gallery?brand_id=${encodeURIComponent(brandId)}`),

  // brands
  brands: () => request<BrandSummary[]>("/api/brands"),
  brand: (id: string) => request<BrandView>(`/api/brands/${id}`),
  createBrand: (name: string, description = "") => request<BrandView>("/api/brands", { method: "POST", body: json({ name, description }) }),
  saveBrand: (id: string, profile: unknown) => request<BrandView>(`/api/brands/${id}`, { method: "PUT", body: json(profile) }),
  deleteBrand: (id: string) => request<{ deleted: string }>(`/api/brands/${id}`, { method: "DELETE" }),
  resetBrand: (id: string) => request<BrandView>(`/api/brands/${id}/reset`, { method: "POST" }),
  uploadLogo(id: string, file: File, variant: "default" | "dark" = "default") {
    const fd = new FormData();
    fd.append("file", file);
    return request<BrandView>(`/api/brands/${id}/logo?variant=${variant}`, { method: "POST", body: fd });
  },
  uploadFont(id: string, file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ fonts: string[] }>(`/api/brands/${id}/fonts`, { method: "POST", body: fd });
  },
  uploadReferences(id: string, files: File[]) {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<BrandView>(`/api/brands/${id}/references`, { method: "POST", body: fd });
  },
  deleteReference: (id: string, name: string) => request<BrandView>(`/api/brands/${id}/references/${encodeURIComponent(name)}`, { method: "DELETE" }),
  analyzeReferences: (id: string) =>
    request<{ images: Record<string, unknown>[]; summary: Record<string, unknown>; suggestions: Suggestion[] }>(`/api/brands/${id}/analyze-references`, { method: "POST" }),
  uploadTemplate(id: string, file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ template_id: string; analysis: Record<string, unknown> & { suggestions: Suggestion[] }; brand: BrandView }>(
      `/api/brands/${id}/template`, { method: "POST", body: fd });
  },
  applySuggestions: (id: string, items: Suggestion[]) => request<BrandView>(`/api/brands/${id}/apply-suggestions`, { method: "POST", body: json({ items }) }),
  brandPreview: (id: string) => request<{ images: string[]; fallbacks: string[] }>(`/api/brands/${id}/preview`, { method: "POST" }),
  fonts: () => request<{ families: string[] }>("/api/fonts"),

  // settings
  settings: () => request<{ settings: RuntimeSettings; storage: Record<string, string>; privacy: Record<string, unknown> }>("/api/settings"),
  saveSettings: (body: Partial<RuntimeSettings>) =>
    request<{ settings: RuntimeSettings; storage: Record<string, string>; privacy: Record<string, unknown> }>("/api/settings", { method: "PUT", body: json(body) }),
  status: () => request<SystemStatus>("/api/system/status"),
  testLLM: () => request<{ ok: boolean; seconds?: number; message?: string }>("/api/llm/test", { method: "POST" }),
};

export const fileUrl = (projectId: string, path: string, opts: { download?: boolean; format?: string; v?: string | number } = {}) => {
  const q = new URLSearchParams();
  if (opts.download) q.set("download", "true");
  if (opts.format) q.set("format", opts.format);
  if (opts.v !== undefined) q.set("v", String(opts.v));
  const qs = q.toString();
  return `/api/projects/${projectId}/files/${path}${qs ? `?${qs}` : ""}`;
};

export const brandAssetUrl = (brandId: string, kind: "assets" | "references", name: string) =>
  `/api/brands/${brandId}/assets/${kind}/${encodeURIComponent(name)}`;
