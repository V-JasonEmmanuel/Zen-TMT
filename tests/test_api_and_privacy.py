"""End-to-end API workflow + security/privacy guarantees."""
import io
import re
import socket
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.branding.brand_profile import ensure_default_brands
from backend.main import app
from backend.pipeline.jobs import runner
from backend.pipeline.orchestrator import register_handlers
from backend.utils import network_guard

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    ensure_default_brands()
    register_handlers()
    return TestClient(app)  # no lifespan: jobs are executed inline below


@pytest.fixture(scope="module")
def generated(client, sample_pdf):
    r = client.post("/api/documents/upload", files={"file": ("../../evil name.pdf", sample_pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "ready" and doc["filename"] == "evil name.pdf"
    r = client.post("/api/projects", json={"name": "API Test", "document_id": doc["id"], "instruction":
                    "Create a 7-slide presentation focusing on methodology and results for a client audience.",
                    "output_formats": ["pptx", "pdf", "png"], "options": {"writing_mode": "extractive"}})
    assert r.status_code == 200, r.text
    project = r.json()
    job = client.post("/api/generate", json={"project_id": project["id"]}).json()
    network_guard.install()
    try:
        runner.run_inline(job["id"])
    finally:
        network_guard.uninstall()
    return project, client.get(f"/api/generation/{job['id']}").json()


def test_full_generation_job(generated):
    _, job = generated
    assert job["status"] in ("completed", "completed_with_warnings"), job
    states = {s["key"]: s["status"] for s in job["stages"]}
    assert states["plan"] == "done" and states["pptx"] == "done" and states["previews"] == "done"
    assert states["video"] == "skipped"


def test_outputs_listed_and_downloadable(client, generated):
    project, _ = generated
    outs = client.get(f"/api/projects/{project['id']}/outputs").json()
    kinds = {o["kind"] for o in outs}
    assert {"pptx", "pdf", "slide_image", "image", "source_mapping", "content_plan"} <= kinds
    r = client.get(f"/api/projects/{project['id']}/files/presentation/presentation.pptx?download=true")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    visual = next(o["path"] for o in outs if o["kind"] == "image" and o["path"].endswith(".png"))
    jpg = client.get(f"/api/projects/{project['id']}/files/{visual}?format=jpg&download=true")
    assert jpg.status_code == 200 and jpg.headers["content-type"] == "image/jpeg"
    z = client.get(f"/api/projects/{project['id']}/download/all")
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "presentation/presentation.pptx" in names and "source/source_mapping.json" in names


def test_source_mapping_traces_every_claim(client, generated):
    project, _ = generated
    m = client.get(f"/api/projects/{project['id']}/sources").json()
    assert m["document"]["name"] == "evil name.pdf"
    for slide, claims in m["claims"].items():
        for c in claims:
            assert c["page"] and c["chunk_ids"], f"{slide}: untraceable claim {c['claim']}"


def test_edit_slide_preserves_sources_and_versions(client, generated):
    project, _ = generated
    pid = project["id"]
    plan = client.get(f"/api/projects/{pid}/plan").json()
    target = next(s for s in plan["slides"] if s["key_points"] and s["layout"] not in ("references", "cover"))
    pts = target["key_points"]
    kept_sources = pts[0]["sources"]
    pts[0]["text"] = pts[0]["text"] + " (edited)"
    r = client.put(f"/api/projects/{pid}/plan/slides/{target['slide_number']}", json={"key_points": pts, "title": "Edited title"})
    assert r.status_code == 200, r.text
    runner.run_inline(r.json()["job"]["id"])
    new = client.get(f"/api/projects/{pid}/plan").json()
    assert new["version"] == plan["version"] + 1
    s = next(x for x in new["slides"] if x["slide_number"] == target["slide_number"])
    assert s["title"] == "Edited title" and s["edited"]
    assert s["key_points"][0]["status"] == "user_edited" and set(kept_sources) <= set(s["key_points"][0]["sources"])


def test_path_traversal_blocked(client, generated):
    project, _ = generated
    for bad in ("../../data/app.db", "..%2F..%2Fdata%2Fapp.db", "C:/Windows/win.ini"):
        r = client.get(f"/api/projects/{project['id']}/files/{bad}")
        assert r.status_code in (400, 404), bad
    assert client.get("/api/brands/..%2F..%2Fdata/assets/assets/x.png").status_code in (400, 404)


def test_unsupported_upload_rejected(client):
    r = client.post("/api/documents/upload", files={"file": ("tool.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert r.status_code == 400


def test_remote_ollama_host_refused(client):
    r = client.put("/api/settings", json={"ollama_host": "http://llm.example.com:11434"})
    assert r.status_code == 400


def test_delete_project_removes_files(client, sample_pdf):
    doc = client.post("/api/documents/upload", files={"file": ("d.pdf", sample_pdf.read_bytes(), "application/pdf")}).json()
    p = client.post("/api/projects", json={"name": "To delete", "document_id": doc["id"], "instruction": "Create 3 slides on results.",
                                           "options": {"writing_mode": "extractive"}}).json()
    job = client.post("/api/generate", json={"project_id": p["id"]}).json()
    runner.run_inline(job["id"])
    from backend.utils.config import get_settings

    out = get_settings().outputs_path / p["output_dir"]
    assert out.exists()
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    assert not out.exists() and client.get(f"/api/projects/{p['id']}").status_code == 404


# ------------------------------------------------------------------ privacy
def test_network_guard_blocks_external_allows_local():
    network_guard.install()
    try:
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("93.184.216.34", 80), timeout=2)
        s = socket.socket()
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 9))  # loopback allowed (refused by OS, not by the guard)
        except OSError as e:
            assert not isinstance(e, network_guard.NetworkBlocked)
        finally:
            s.close()
    finally:
        network_guard.uninstall()


def test_no_cloud_api_dependencies():
    pattern = re.compile(r"OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY|api\.openai\.com|generativelanguage|anthropic\.com")
    offenders = []
    for base in (ROOT / "backend", ROOT / "frontend" / "src", ROOT / "scripts"):
        for f in base.rglob("*"):
            if f.suffix in (".py", ".ts", ".tsx", ".txt", ".json") and pattern.search(f.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(f))
    assert offenders == []
    for req in (ROOT / "requirements.txt",):
        if req.exists():
            assert not re.search(r"^(openai|anthropic|google-generativeai)\b", req.read_text(), re.M)


def test_frontend_loads_no_remote_assets():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "fonts.googleapis" not in css and "@import url(" not in css
