"""Test environment: every test session runs against a throw-away data directory.

The real ONNX embedding model (./models) is used when present (fast, realistic);
otherwise the deterministic hashing embedder keeps the suite runnable anywhere.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    base = Path(config.rootpath) / ".pytest_data"
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    for key, sub in (("DATA_DIR", "data"), ("OUTPUT_DIR", "outputs"), ("PROJECT_DIR", "projects"),
                     ("BRANDS_DIR", "brands"), ("TEMPLATES_DIR", "templates")):
        os.environ[key] = str(base / sub)
    os.environ["DATABASE_PATH"] = str(base / "data" / "app.db")
    os.environ["MODELS_DIR"] = str(ROOT / "models")  # read-only use of prepared models
    os.environ["OLLAMA_MODEL"] = ""
    onnx = ROOT / "models" / "embeddings" / "sentence-transformers__all-MiniLM-L6-v2" / "model.onnx"
    if not onnx.exists():
        os.environ["ZCS_EMBEDDER"] = "hashing"

    from backend.utils.config import get_settings, reset_settings_cache

    reset_settings_cache()
    get_settings().ensure_dirs()


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory) -> Path:
    from tests.fixtures.make_samples import make_docx, make_pdf

    d = tmp_path_factory.mktemp("fixtures")
    make_pdf(d / "sample_research.pdf")
    make_docx(d / "sample_research.docx")
    return d


@pytest.fixture(scope="session")
def sample_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "sample_research.pdf"


@pytest.fixture(scope="session")
def sample_docx(fixtures_dir) -> Path:
    return fixtures_dir / "sample_research.docx"


@pytest.fixture(scope="session")
def extracted(sample_pdf, tmp_path_factory):
    from backend.extraction.structure import analyze_structure
    from backend.ingestion import get_adapter
    from backend.intelligence.chunking import chunk_document

    work = tmp_path_factory.mktemp("work")
    doc = get_adapter(sample_pdf).extract(sample_pdf, "doc_test", work)
    st = analyze_structure(doc)
    chunks = chunk_document(doc, st)
    return doc, st, chunks


@pytest.fixture(scope="session")
def embedder():
    from backend.intelligence.embeddings import get_embedder

    return get_embedder("sentence-transformers/all-MiniLM-L6-v2")


class FakeLLM:
    """Scripted LLM: returns queued responses (or a callable's output) and records prompts."""

    name = "fake"
    model = "fake-model"

    def __init__(self, responses=None, fn=None):
        self.responses = list(responses or [])
        self.fn = fn
        self.prompts: list[str] = []

    def is_available(self):
        return True

    def list_models(self):
        return [{"name": self.model}]

    def generate(self, prompt, *, system="", json_schema=None, max_tokens=1024, temperature=None):
        self.prompts.append(prompt)
        if self.fn:
            out = self.fn(prompt, json_schema)
            return out if isinstance(out, str) else json.dumps(out)
        r = self.responses.pop(0) if self.responses else "{}"
        return r if isinstance(r, str) else json.dumps(r)

    def unload(self):
        pass


@pytest.fixture
def fake_llm():
    return FakeLLM


def build_plan(extracted, embedder, instruction: str, llm=None, slides: int | None = None):
    from backend.intelligence.relevance import rank_chunks
    from backend.intelligence.verification import Verifier
    from backend.planning.content_contract import parse_instruction
    from backend.planning.content_planner import ContentPlanner, PlanningContext

    doc, st, chunks = extracted
    contract = parse_instruction(instruction, llm, defaults={"slide_count": slides} if slides else None)
    vecs = embedder.encode([c.text for c in chunks])
    rel = rank_chunks(contract, chunks, vecs, embedder)
    cm = {c.id: c for c in chunks}
    ctx = PlanningContext("doc_test", "sample_research.pdf", doc.title, chunks, contract, rel, embedder, Verifier(cm, embedder), llm)
    return ContentPlanner(ctx).build(), ctx


@pytest.fixture(scope="session")
def extractive_plan(extracted, embedder):
    plan, _ = build_plan(extracted, embedder, "Create a 10-slide technical presentation for a senior client audience. "
                         "Focus on architecture, methodology and results. Do not include detailed implementation code.")
    return plan
