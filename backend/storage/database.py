"""Thin SQLite data-access layer (no ORM needed for a single-user local app)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from pydantic import BaseModel, Field

from backend.schemas import ContentPlan, DocumentChunk, GenerationJob, OutputFile, utcnow
from backend.storage.models import SCHEMA
from backend.utils.config import get_settings


class RuntimeSettings(BaseModel):
    """User-adjustable settings (Settings screen). Defaults come from `.env`."""

    ollama_host: str = ""
    ollama_model: str = ""
    embedding_model: str = ""
    llm_temperature: float = 0.2
    llm_timeout_s: int = 240
    tts_enabled: bool = True
    tts_engine: str = "auto"
    tts_voice: str = ""
    tts_rate: float = 1.0  # 0.5 .. 2.0
    subtitles: bool = True
    ocr_enabled: bool = True
    ffmpeg_path: str = ""
    verification_threshold: float = 0.45
    drop_unverified: bool = False  # False = keep but flag for review
    default_brand: str = "zensar"
    onboarding_complete: bool = False
    allow_internet_image_search: bool = False  # default OFF for confidential environments
    extra: dict[str, Any] = Field(default_factory=dict)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.path, timeout=30)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            try:
                yield con
                con.commit()
            finally:
                con.close()

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def runtime_settings(self) -> RuntimeSettings:
        env = get_settings()
        stored = self.get_setting("runtime", {}) or {}
        base = RuntimeSettings(
            ollama_host=env.ollama_host,
            ollama_model=env.ollama_model,
            embedding_model=env.embedding_model,
            tts_enabled=env.tts_enabled,
            tts_engine=env.tts_engine,
            ocr_enabled=env.ocr_enabled,
            ffmpeg_path=env.ffmpeg_path,
        )
        merged = base.model_dump()
        merged.update({k: v for k, v in stored.items() if k in merged and v not in (None,)})
        # empty strings in stored settings fall back to env values
        for k in ("ollama_host", "embedding_model"):
            if not merged.get(k):
                merged[k] = getattr(base, k)
        return RuntimeSettings(**merged)

    def save_runtime_settings(self, rs: RuntimeSettings) -> None:
        self.set_setting("runtime", rs.model_dump())

    # ------------------------------------------------------------------ projects
    def create_project(self, row: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        row = {**row, "created_at": now, "updated_at": now}
        row["output_formats"] = json.dumps(row.get("output_formats", []))
        row["options"] = json.dumps(row.get("options", {}))
        cols = ",".join(row)
        with self.connect() as con:
            con.execute(f"INSERT INTO projects({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
        return self.get_project(row["id"])  # type: ignore[return-value]

    def update_project(self, project_id: str, **fields: Any) -> None:
        if not fields:
            return
        for k in ("output_formats", "options", "contract"):
            if k in fields and not isinstance(fields[k], str) and fields[k] is not None:
                fields[k] = json.dumps(fields[k])
        fields["updated_at"] = utcnow()
        sets = ",".join(f"{k}=?" for k in fields)
        with self.connect() as con:
            con.execute(f"UPDATE projects SET {sets} WHERE id=?", (*fields.values(), project_id))

    def _project_row(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["output_formats"] = json.loads(d.get("output_formats") or "[]")
        d["options"] = json.loads(d.get("options") or "{}")
        d["contract"] = json.loads(d["contract"]) if d.get("contract") else None
        return d

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            r = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return self._project_row(r) if r else None

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [self._project_row(r) for r in rows]

    def delete_project(self, project_id: str) -> None:
        with self.connect() as con:
            for table in ("content_plans", "generation_jobs", "outputs", "source_mappings"):
                con.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            con.execute("DELETE FROM projects WHERE id=?", (project_id,))

    # ------------------------------------------------------------------ documents
    def create_document(self, row: dict[str, Any]) -> None:
        row = {**row, "created_at": utcnow()}
        row["meta"] = json.dumps(row.get("meta", {}))
        cols = ",".join(row)
        with self.connect() as con:
            con.execute(f"INSERT INTO documents({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values()))

    def update_document(self, document_id: str, **fields: Any) -> None:
        for k in ("structure", "meta"):
            if k in fields and not isinstance(fields[k], str) and fields[k] is not None:
                fields[k] = json.dumps(fields[k])
        sets = ",".join(f"{k}=?" for k in fields)
        with self.connect() as con:
            con.execute(f"UPDATE documents SET {sets} WHERE id=?", (*fields.values(), document_id))

    def _doc_row(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        d["structure"] = json.loads(d["structure"]) if d.get("structure") else None
        return d

    def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            r = con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        return self._doc_row(r) if r else None

    def find_document_by_hash(self, sha: str) -> Optional[dict[str, Any]]:
        with self.connect() as con:
            r = con.execute("SELECT * FROM documents WHERE sha256=? ORDER BY created_at DESC", (sha,)).fetchone()
        return self._doc_row(r) if r else None

    def list_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM documents ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._doc_row(r) for r in rows]

    # ------------------------------------------------------------------ chunks
    def replace_chunks(self, document_id: str, chunks: list[DocumentChunk]) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
            con.executemany(
                "INSERT INTO document_chunks(id,document_id,idx,payload) VALUES(?,?,?,?)",
                [(c.id, document_id, c.index, c.model_dump_json()) for c in chunks],
            )

    def get_chunks(self, document_id: str) -> list[DocumentChunk]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload FROM document_chunks WHERE document_id=? ORDER BY idx", (document_id,)
            ).fetchall()
        return [DocumentChunk.model_validate_json(r["payload"]) for r in rows]

    # ------------------------------------------------------------------ plans
    def save_plan(self, plan: ContentPlan) -> int:
        with self.connect() as con:
            row = con.execute(
                "SELECT COALESCE(MAX(version),0) AS v FROM content_plans WHERE project_id=?", (plan.project_id,)
            ).fetchone()
            plan.version = int(row["v"]) + 1
            con.execute(
                "INSERT INTO content_plans(project_id,version,plan,created_at) VALUES(?,?,?,?)",
                (plan.project_id, plan.version, plan.model_dump_json(), utcnow()),
            )
            # keep the latest 20 versions only
            con.execute(
                "DELETE FROM content_plans WHERE project_id=? AND version <= ?", (plan.project_id, plan.version - 20)
            )
        return plan.version

    def latest_plan(self, project_id: str) -> Optional[ContentPlan]:
        with self.connect() as con:
            r = con.execute(
                "SELECT plan FROM content_plans WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)
            ).fetchone()
        return ContentPlan.model_validate_json(r["plan"]) if r else None

    # ------------------------------------------------------------------ jobs
    def save_job(self, job: GenerationJob) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO generation_jobs(id,project_id,payload,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (job.id, job.project_id, job.model_dump_json(), job.created_at),
            )

    def get_job(self, job_id: str) -> Optional[GenerationJob]:
        with self.connect() as con:
            r = con.execute("SELECT payload FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        return GenerationJob.model_validate_json(r["payload"]) if r else None

    def list_jobs(self, project_id: str) -> list[GenerationJob]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload FROM generation_jobs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [GenerationJob.model_validate_json(r["payload"]) for r in rows]

    def mark_interrupted_jobs(self) -> int:
        """Jobs left 'running' by a previous process are marked failed on startup."""
        n = 0
        with self.connect() as con:
            rows = con.execute("SELECT payload FROM generation_jobs").fetchall()
        for r in rows:
            job = GenerationJob.model_validate_json(r["payload"])
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = "Interrupted: the application was restarted during generation."
                for s in job.stages:
                    if s.status in ("pending", "running"):
                        s.status = "skipped" if s.status == "pending" else "failed"
                self.save_job(job)
                n += 1
        return n

    # ------------------------------------------------------------------ outputs
    def replace_outputs(self, project_id: str, kinds: list[str], outputs: list[OutputFile]) -> None:
        with self.connect() as con:
            if kinds:
                con.execute(
                    f"DELETE FROM outputs WHERE project_id=? AND kind IN ({','.join('?' * len(kinds))})",
                    (project_id, *kinds),
                )
            con.executemany(
                "INSERT OR REPLACE INTO outputs(id,project_id,kind,path,payload,created_at) VALUES(?,?,?,?,?,?)",
                [(o.id, project_id, o.kind, o.path, o.model_dump_json(), o.created_at) for o in outputs],
            )

    def list_outputs(self, project_id: str) -> list[OutputFile]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload FROM outputs WHERE project_id=? ORDER BY kind, path", (project_id,)
            ).fetchall()
        return [OutputFile.model_validate_json(r["payload"]) for r in rows]

    def get_output(self, output_id: str) -> Optional[OutputFile]:
        with self.connect() as con:
            r = con.execute("SELECT payload FROM outputs WHERE id=?", (output_id,)).fetchone()
        return OutputFile.model_validate_json(r["payload"]) if r else None

    # ------------------------------------------------------------------ source mapping
    def save_source_mapping(self, project_id: str, mapping: dict[int, list[dict[str, Any]]]) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM source_mappings WHERE project_id=?", (project_id,))
            con.executemany(
                "INSERT INTO source_mappings(project_id,slide_number,mapping) VALUES(?,?,?)",
                [(project_id, n, json.dumps(m)) for n, m in mapping.items()],
            )

    # ------------------------------------------------------------------ brands / templates
    def upsert_brand(self, brand_id: str, name: str, status: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO brand_profiles(id,name,status,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,status=excluded.status,updated_at=excluded.updated_at",
                (brand_id, name, status, utcnow()),
            )

    def delete_brand(self, brand_id: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM brand_profiles WHERE id=?", (brand_id,))
            con.execute("DELETE FROM templates WHERE brand_id=?", (brand_id,))

    def add_template(self, row: dict[str, Any]) -> None:
        row = {**row, "created_at": utcnow()}
        if row.get("analysis") is not None and not isinstance(row["analysis"], str):
            row["analysis"] = json.dumps(row["analysis"])
        cols = ",".join(row)
        with self.connect() as con:
            con.execute(f"INSERT OR REPLACE INTO templates({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values()))

    def list_templates(self, brand_id: Optional[str] = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM templates", ()
        if brand_id:
            q, args = q + " WHERE brand_id=?", (brand_id,)
        with self.connect() as con:
            rows = con.execute(q + " ORDER BY created_at DESC", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["analysis"] = json.loads(d["analysis"]) if d.get("analysis") else None
            out.append(d)
        return out

    def get_template(self, template_id: str) -> Optional[dict[str, Any]]:
        for t in self.list_templates():
            if t["id"] == template_id:
                return t
        return None

    def delete_template(self, template_id: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM templates WHERE id=?", (template_id,))


_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    global _db
    with _db_lock:
        if _db is None:
            _db = Database(get_settings().db_file)
        return _db


def set_db(db: Optional[Database]) -> None:
    """Used by tests to point the app at a temporary database."""
    global _db
    with _db_lock:
        _db = db
