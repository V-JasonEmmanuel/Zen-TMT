"""SQLite schema. JSON payloads are stored as TEXT and validated by Pydantic on read."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    brand_id TEXT,
    template_id TEXT,
    document_id TEXT,
    instruction TEXT DEFAULT '',
    output_formats TEXT DEFAULT '[]',
    options TEXT DEFAULT '{}',
    contract TEXT,
    last_job_id TEXT,
    output_dir TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    format TEXT NOT NULL,
    size INTEGER NOT NULL,
    page_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'uploaded',
    extraction_method TEXT DEFAULT '',
    error TEXT DEFAULT '',
    structure TEXT,
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id, idx);

CREATE TABLE IF NOT EXISTS content_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    plan TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_project ON content_plans(project_id, version);

CREATE TABLE IF NOT EXISTS brand_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unconfigured',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    analysis TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON generation_jobs(project_id, created_at);

CREATE TABLE IF NOT EXISTS outputs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outputs_project ON outputs(project_id, kind);

CREATE TABLE IF NOT EXISTS source_mappings (
    project_id TEXT NOT NULL,
    slide_number INTEGER NOT NULL,
    mapping TEXT NOT NULL,
    PRIMARY KEY (project_id, slide_number)
);

CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    collection TEXT NOT NULL,
    kind TEXT NOT NULL,
    category TEXT DEFAULT 'other',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_collection ON media_assets(collection, category);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
