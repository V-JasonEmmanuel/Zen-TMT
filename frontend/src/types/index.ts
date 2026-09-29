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
  kind: "document" | "video" | "repository";
  media_asset_id?: string | null;
  duration?: number | null;
  source_url?: string;
  deferred?: boolean;
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
  sources?: { id: string; filename: string; format: string; status: string }[];
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
  template_id?: string;
  extra_document_ids?: string[];
  narration_mode?: "tts" | "upload" | "none";
  narration_asset_id?: string | null;
  script?: string;
  music_asset_id?: string | null;
  video_media?: string[];
  transition?: Transition;
  motion?: "none" | "subtle" | "ken_burns";
  intro?: boolean;
  outro?: boolean;
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

export type Transition = "zensar_grid" | "fade" | "wipe" | "none";

export interface MediaAsset {
  id: string;
  kind: string;
  filename: string;
  collection: string;
  category: string;
  tags: string[];
  description: string;
  width: number;
  height: number;
  bytes: number;
  url: string;
  thumb_url: string | null;
  duration?: number | null;
  source_label?: string;
  created_at?: string;
  meta?: Record<string, unknown>;
}

export interface TemplateItem {
  id: string;
  name: string;
  description: string;
  kind: "preset" | "pptx";
  previews: string[];
}

export interface Crop { x: number; y: number; w: number; h: number }

export interface TimelineClip {
  id: string;
  type: "slide" | "image" | "video" | "intro" | "outro";
  label: string;
  slide_number?: number | null;
  asset_id?: string | null;
  trim_start: number;
  trim_end?: number | null;
  speed: number;
  crop?: Crop | null;
  duration: number;
  transition: Transition;
  motion: "none" | "subtle" | "ken_burns";
  keep_audio: boolean;
  audio_volume: number;
  narration_text: string;
  narration_locked: boolean;
  narration_asset_id?: string | null;
  narration_segments: { start: number; end: number; text: string }[];
  source_duration: number;
  // read-only enrichment from the server
  asset?: { id: string; kind: string; filename: string; url: string; thumb_url: string | null; duration?: number | null; width: number; height: number; has_audio: boolean } | null;
  narration_asset?: { id: string; filename: string; duration?: number | null } | null;
  thumb_url?: string;
}

export interface Timeline {
  version: number;
  width: number;
  height: number;
  fps: number;
  clips: TimelineClip[];
  music: { asset_id?: string | null; volume: number; duck: boolean; fade_in: number; fade_out: number; asset?: { id: string; filename: string; duration?: number | null } | null };
  narration: { mode: "tts" | "upload" | "none"; voice: string; speed: number; asset_id?: string | null; script: string; asset?: { id: string; filename: string; duration?: number | null } | null };
  subtitles: boolean;
  updated_at: string;
  rendered: Partial<Record<"preview" | "final", { duration: number; clips: { id: string; type: string; label: string; start: number; end: number }[] }>>;
}
