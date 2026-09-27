export type StageState = "pending" | "running" | "done" | "failed" | "skipped" | "warning";

export interface Stage {
  key: string;
  label: string;
  status: StageState;
  message: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface Job {
  id: string;
  project_id: string;
  kind: "full" | "slide" | "render" | "video";
  status: "queued" | "running" | "completed" | "completed_with_warnings" | "failed" | "cancelled";
  stages: Stage[];
  warnings: string[];
  error: string;
  params: Record<string, unknown>;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  queue_position?: number;
}

export interface DocumentSection {
  id: string;
  title: string;
  level: number;
  type: string;
  pages: [number, number];
}

export interface DocumentInfo {
  id: string;
  filename: string;
  format: string;
  size: number;
  page_count: number;
  status: "uploaded" | "ready" | "failed";
  extraction_method: string;
  error: string;
  title: string;
  warnings: string[];
  ocr_may_help: boolean;
  created_at: string;
  structure: null | {
    title: string;
    pages: number;
    sections: DocumentSection[];
    detected_types: string[];
    tables: number;
    figures: number;
    chunks: number;
  };
}

export interface OutputFile {
  id: string;
  project_id: string;
  kind: "pptx" | "pdf" | "slide_image" | "image" | "video" | "subtitles" | "source_mapping" | "content_plan";
  path: string;
  size: number;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  status: "draft" | "queued" | "generating" | "ready" | "failed";
  brand_id: string;
  document_id: string;
  instruction: string;
  output_formats: string[];
  options: ProjectOptions;
  contract: Contract | null;
  last_job_id: string | null;
  output_dir: string;
  created_at: string;
  updated_at: string;
  document: { id: string; filename: string; pages: number; status: string } | null;
  last_job: Job | null;
  thumbnail: string | null;
  output_counts: Record<string, number>;
  outputs?: OutputFile[];
  jobs?: Job[];
}

export interface ProjectOptions {
  writing_mode?: "llm" | "extractive";
  narration?: boolean;
  voice?: string;
  speed?: number;
  subtitles?: boolean;
  slide_count?: number;
}

export interface Contract {
  audience: string;
  purpose: string;
  slide_count: number;
  tone: string;
  include: string[];
  exclude: string[];
  detail_level: string;
  notes: string;
  parse_method?: string;
}

export type ClaimStatus = "verified" | "needs_review" | "unsupported" | "user_edited" | "structural";

export interface Claim {
  text: string;
  sources: string[];
  confidence: number;
  status: ClaimStatus;
  evidence_page?: number | null;
}

export interface Step {
  title: string;
  description: string;
  sources: string[];
  confidence: number;
  status: ClaimStatus;
}

export interface KPI {
  value: string;
  label: string;
  sources: string[];
  confidence: number;
  status: ClaimStatus;
}

export interface Column {
  heading: string;
  points: Claim[];
}

export interface SourceRef {
  document_id: string;
  document_name: string;
  chunk_id: string;
  page: number | null;
  page_end: number | null;
  section: string;
  content_type: string;
  table: number | null;
  figure: number | null;
}

export interface Slide {
  slide_number: number;
  layout: string;
  title: string;
  subtitle: string;
  key_points: Claim[];
  columns: Column[];
  steps: Step[];
  kpis: KPI[];
  table: { headers: string[]; rows: string[][]; caption: string; source: string } | null;
  chart: { chart_type: string; title: string; categories: string[]; series: { name: string; values: number[] }[]; unit: string; source: string } | null;
  quote: Claim | null;
  visual: { kind: string; nodes: { id: string; label: string; group: string }[]; edges: unknown[] } | null;
  narration: string;
  sources: SourceRef[];
  accent_role: string;
  topic: string;
  edited: boolean;
  warnings: string[];
  needs_review?: boolean;
}

export interface ContentPlan {
  project_id: string;
  version: number;
  title: string;
  subtitle: string;
  contract: Contract;
  slides: Slide[];
  created_at: string;
  generator: Record<string, unknown>;
  warnings: string[];
}

export interface SourceMapping {
  document: { id: string; name: string };
  generated_at: string;
  plan_version: number;
  slides: Record<string, { page: number | null; page_end: number | null; section: string; source: string; chunk_id: string; content_type: string; table: number | null; figure: number | null }[]>;
  claims: Record<string, { kind: string; claim: string; source_document: string | null; page: number | null; section: string | null; confidence: number; status: ClaimStatus; chunk_ids: string[] }[]>;
}

export interface Provenance {
  source: "manual" | "pptx_template" | "reference_image" | "default";
  confidence: number;
  note: string;
}

export interface BrandProfile {
  id: string;
  name: string;
  description: string;
  colors: Record<string, string | null> & { palette: string[] };
  typography: {
    heading: { family: string | null; bold: boolean | null; color_role: string | null };
    body: { family: string | null; bold: boolean | null; color_role: string | null };
    caption: { family: string | null; bold: boolean | null; color_role: string | null };
    sizes: Record<string, number | null>;
  };
  layout: Record<string, number | string | null>;
  components: Record<string, unknown>;
  logo: { file: string | null; file_on_dark: string | null; position: string; width_in: number | null; show_on: string };
  footer: { text: string; show_page_numbers: boolean; show_sources: boolean };
  template: { file: string | null; use_as_base: boolean; blank_layout: string | null };
  references: string[];
  provenance: Record<string, Provenance>;
  updated_at: string;
}

export interface BrandView {
  profile: BrandProfile;
  status: "configured" | "partial" | "unconfigured";
  missing: string[];
  fallbacks: string[];
  resolved: { colors: Record<string, string>; heading_font: string; body_font: string; slide_size: [number, number] };
  reference_images: string[];
  templates: string[];
  errors?: string[];
}

export interface BrandSummary {
  id: string;
  name: string;
  description: string;
  status: string;
  updated_at: string;
  primary: string | null;
  logo: string | null;
}

export interface Suggestion {
  path: string;
  value: unknown;
  confidence: number;
  reason: string;
  source: "pptx_template" | "reference_image" | "manual";
}

export interface RuntimeSettings {
  ollama_host: string;
  ollama_model: string;
  embedding_model: string;
  llm_temperature: number;
  llm_timeout_s: number;
  tts_enabled: boolean;
  tts_engine: string;
  tts_voice: string;
  tts_rate: number;
  subtitles: boolean;
  ocr_enabled: boolean;
  ffmpeg_path: string;
  verification_threshold: number;
  drop_unverified: boolean;
  default_brand: string;
  onboarding_complete: boolean;
}

export interface SystemStatus {
  python: string;
  ollama: { running: boolean; host: string; models: { name: string; size_gb: number; parameters: string; quantization: string }[]; selected: string; model_ready: boolean };
  embeddings: { model: string; onnx_ready: boolean; loaded_backend: string | null };
  ffmpeg: { available: boolean; path: string | null };
  tts: { engines: Record<string, string[]>; available: boolean };
  ocr: { available: boolean; engine: string | null };
  gpu: { available: boolean; name?: string; memory?: string };
  disk_free_gb: number;
  offline_guard: boolean;
  onboarding_complete: boolean;
  ready: boolean;
}
