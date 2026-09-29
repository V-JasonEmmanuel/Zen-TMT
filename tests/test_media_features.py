"""Media features: scripts, templates, repository + demo-video sources, the video timeline editor and the composer."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from backend.rendering.video.ffmpeg import find_ffmpeg, media_duration, media_streams

FF = find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(not FF, reason="FFmpeg not available")


# ------------------------------------------------------------------ helpers
def make_video(path: Path, colors=("red", "blue", "green"), seconds: float = 3.0, audio: bool = False) -> Path:
    args = [FF, "-hide_banner", "-loglevel", "error", "-y"]
    for c in colors:
        args += ["-f", "lavfi", "-i", f"color=c={c}:s=640x360:d={seconds}:r=15"]
    chain = "".join(f"[{i}:v]" for i in range(len(colors))) + f"concat=n={len(colors)}:v=1:a=0[v]"
    if audio:
        args += ["-f", "lavfi", "-t", str(seconds * len(colors)), "-i", "sine=f=440"]
    args += ["-filter_complex", chain, "-map", "[v]"]
    if audio:
        args += ["-map", f"{len(colors)}:a", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True)
    return path


def make_audio(path: Path, seconds: float = 6.0, freq: int = 220) -> Path:
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}", str(path)], check=True)
    return path


def make_repo_zip(path: Path) -> Path:
    files = {
        "shop/README.md": "# Shop service\n\nA small ordering service. Orders are validated, priced and stored.\n\n## Architecture\n\n"
                          "The api module exposes HTTP endpoints, the pricing module computes totals and the storage module persists orders.\n",
        "shop/requirements.txt": "fastapi\nuvicorn\nsqlalchemy\n",
        "shop/app/__init__.py": "",
        "shop/app/main.py": '"""Application entry point."""\nfrom app import api\n\napp = api.build()\n',
        "shop/app/api.py": '"""HTTP endpoints for orders."""\nfrom fastapi import APIRouter\nfrom app import pricing, storage\n\n'
                           'router = APIRouter()\n\n\n@router.get("/orders")\ndef list_orders():\n    return storage.all()\n\n\n'
                           '@router.post("/orders")\ndef create(order: dict):\n    return storage.save(pricing.total(order))\n\n\ndef build():\n    return router\n',
        "shop/app/pricing.py": '"""Order pricing rules."""\n\n\ndef total(order):\n    return order\n',
        "shop/app/storage.py": '"""Order persistence."""\n_DB = []\n\n\ndef save(o):\n    _DB.append(o)\n    return o\n\n\ndef all():\n    return list(_DB)\n',
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
        z.writestr("../escape.txt", "zip-slip attempt")
    return path


# ------------------------------------------------------------------ scripts, instructions, titles, presets
def test_script_markers_and_distribution():
    from backend.planning.script import distribute, parse_script

    marked, plain = parse_script("## Slide 2\nHello there.\n\n## Slide 4\nSecond part.")
    assert marked == {2: "Hello there.", 4: "Second part."} and plain == []
    assert distribute("## Slide 2\nOnly two.", [1, 2, 3], [1, 1, 1]) == {2: "Only two."}
    assert distribute("One.\n---\nTwo.\n---\nThree.", [1, 2, 3], [1, 1, 1]) == {1: "One.", 2: "Two.", 3: "Three."}
    spread = distribute("A first sentence. A second sentence. A third sentence. A fourth sentence.", [1, 2], [1, 1])
    assert set(spread) == {1, 2} and "first" in spread[1] and "fourth" in spread[2]


def test_instruction_topics_keep_user_order():
    from backend.planning.content_contract import parse_instruction_rules

    c = parse_instruction_rules("Create a 7-slide deck explaining this repository: overview, architecture, workflow, technology stack and API.")
    assert c.include == ["overview", "architecture", "workflow", "implementation"]
    c = parse_instruction_rules("Explain the demo: how the pipeline works and the results.")
    assert "workflow" in c.include and "results" in c.include


def test_duplicate_titles_are_renamed():
    from backend.planning.content_planner import dedupe_titles
    from backend.schemas import Column, Slide

    a = Slide(slide_number=2, layout="executive_summary", title="Product Overview", topic="overview")
    b = Slide(slide_number=3, layout="two_column", title="Product Overview", topic="overview",
              columns=[Column(heading="Key features"), Column(heading="Highlights")])
    dedupe_titles([a, b])
    assert a.title == "Product Overview" and b.title == "Key features & Highlights"


def test_template_presets_change_the_theme():
    from backend.branding.brand_profile import BrandStore, ensure_default_brands
    from backend.branding.presets import PRESETS, apply_preset
    from backend.branding.theme import build_theme

    ensure_default_brands()
    base = build_theme(BrandStore().load("zensar"))
    looks = {pid: vars(apply_preset(base.model_copy(deep=True) if hasattr(base, "model_copy") else base, pid)).copy() for pid in PRESETS}
    assert len(PRESETS) == 5
    assert len({str(sorted((k, str(v)) for k, v in l.items())) for l in looks.values()}) == 5  # every preset is distinct


def test_narration_keeps_whole_sentences():
    from backend.ingestion.video import fit_sentences

    text = "Here we open the login form. Enter your email and password to continue. Then press sign in."
    assert fit_sentences(text, 8) == "Here we open the login form."
    assert fit_sentences(text, 3) == "Here we open the login form."  # at least one sentence
    assert fit_sentences(text, 50).endswith("sign in.")


def test_github_url_parsing():
    from backend.services.github import GitHubError, parse_url

    assert parse_url("https://github.com/owner/repo")[:2] == ("owner", "repo")
    assert parse_url("https://github.com/owner/repo.git")[:2] == ("owner", "repo")
    with pytest.raises(GitHubError):
        parse_url("https://example.com/owner/repo")


# ------------------------------------------------------------------ sources
def test_repository_analysis(tmp_path):
    from backend.ingestion.base import get_adapter

    z = make_repo_zip(tmp_path / "shop.zip")
    doc = get_adapter(z).extract(z, "doc_repo", tmp_path / "work")
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "work" / "escape.txt").exists()
    headings = [b.text for b in doc.blocks if b.type.value == "heading"]
    assert {"Repository overview", "Technology stack", "Architecture"} <= set(headings)
    text = " ".join(b.text for b in doc.blocks)
    assert "fastapi" in text.lower() and "/orders" in text
    graph = doc.metadata["architecture_graph"]
    labels = {n["label"] for n in graph["nodes"]}
    assert {"api", "pricing", "storage"} <= labels
    assert any(e for e in graph["edges"])


@needs_ffmpeg
def test_scene_detection(tmp_path):
    from backend.vision.keyframes import detect_scenes, extract_keyframes

    v = make_video(tmp_path / "demo.mp4", seconds=3.0)
    scenes = detect_scenes(v)
    assert len(scenes) == 3
    assert scenes[1].start == pytest.approx(3.0, abs=0.6) and scenes[-1].end == pytest.approx(9.0, abs=0.3)
    extract_keyframes(v, scenes, tmp_path / "kf")
    assert all(Path(s.frame).exists() for s in scenes)


@needs_ffmpeg
def test_video_adapter_with_fake_vision(tmp_path, monkeypatch):
    from backend.ingestion import video as vmod
    from backend.vision import describe

    screens = iter(["Login screen", "Dashboard", "Settings"])

    def fake_describe(model, frame, previous=""):
        s = next(screens)
        return describe.FrameDescription(screen=s, visible_text=s, action="", description=f"The {s.lower()} of the app is shown.")

    monkeypatch.setattr(describe, "pick_vision_model", lambda: "fake-vision")
    monkeypatch.setattr(describe, "describe_frame", fake_describe)
    monkeypatch.setattr(describe, "unload", lambda m: None)
    monkeypatch.setattr(vmod, "write_narration", lambda scenes: ("Demo", {d["index"]: f"Here is the {d['screen'].lower()}. It has 99 items." for d in scenes}))
    v = make_video(tmp_path / "demo.mp4")
    doc = vmod.VideoAdapter().extract(v, "doc_vid", tmp_path / "work")
    scenes = doc.metadata["scenes"]
    assert [s["screen"] for s in scenes] == ["Login screen", "Dashboard", "Settings"]
    assert scenes[0]["narration"] == "Here is the login screen."  # the unseen number was dropped
    assert any(b.type.value == "figure" for b in doc.blocks)


# ------------------------------------------------------------------ end to end: sources -> project -> timeline edits -> render
@pytest.fixture(scope="module")
def media_project(tmp_path_factory):
    if not FF:
        pytest.skip("FFmpeg not available")
    from fastapi.testclient import TestClient

    from backend.branding.brand_profile import ensure_default_brands
    from backend.main import app
    from backend.pipeline.jobs import runner
    from backend.pipeline.orchestrator import register_handlers
    from backend.vision import describe

    ensure_default_brands()
    register_handlers()
    client = TestClient(app)
    d = tmp_path_factory.mktemp("media")
    orig = describe.pick_vision_model
    describe.pick_vision_model = lambda: None  # deterministic: no local vision model in tests
    try:
        spec = d / "spec.md"
        spec.write_text("# Shop platform\n\n## Overview\n\nThe shop platform takes orders online and prices them automatically.\n\n"
                        "## Workflow\n\nFirst an order is received. Then it is validated. Next the price is calculated. "
                        "Finally the order is stored and confirmed.\n\n## Results\n\nOrders are confirmed in 3 seconds on average "
                        "and 97% are processed without manual work.\n", encoding="utf-8")
        ids = []
        for p, mime in ((spec, "text/markdown"), (make_video(d / "demo.mp4", audio=True), "video/mp4"), (make_repo_zip(d / "shop.zip"), "application/zip")):
            r = client.post("/api/documents/upload", files={"file": (p.name, p.read_bytes(), mime)})
            assert r.status_code == 200, r.text
            ids.append(r.json())
        assert [x["kind"] for x in ids] == ["document", "video", "repository"]
        assert ids[1]["deferred"] and ids[2]["deferred"] and ids[1]["media_asset_id"]
        music = client.post("/api/media/upload", files={"files": ("bed.mp3", make_audio(d / "bed.mp3", 8).read_bytes(), "audio/mpeg")}).json()[0]
        image = client.post("/api/media/upload", files={"files": ("photo.png", _png(), "image/png")}).json()[0]
        assert music["kind"] == "audio" and music["duration"] == pytest.approx(8, abs=0.2)
        r = client.post("/api/projects", json={
            "name": "Media test", "document_ids": [x["id"] for x in ids],
            "instruction": "Create a 6-slide presentation: overview, workflow and results.",
            "output_formats": ["pptx", "png", "mp4"],
            "options": {"writing_mode": "extractive", "template_id": "preset:zensar_bold", "narration_mode": "none",
                        "music_asset_id": music["id"], "video_media": [image["id"]], "transition": "fade", "intro": True, "outro": True}})
        assert r.status_code == 200, r.text
        project = r.json()
        assert len(project["sources"]) == 3
        job = client.post("/api/generate", json={"project_id": project["id"]}).json()
        runner.run_inline(job["id"])
        yield client, project, client.get(f"/api/generation/{job['id']}").json(), {"music": music, "image": image, "dir": d}
    finally:
        describe.pick_vision_model = orig


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (800, 450), (58, 87, 167)).save(buf, "PNG")
    return buf.getvalue()


def test_multi_source_generation(media_project):
    client, project, job, _ = media_project
    assert job["status"] in ("completed", "completed_with_warnings"), job
    states = {s["key"]: s["status"] for s in job["stages"]}
    assert states["video"] in ("done", "warning"), job["stages"]
    plan = client.get(f"/api/projects/{project['id']}/plan").json()
    assert len({s["title"].lower() for s in plan["slides"]}) == len(plan["slides"])
    outs = {o["kind"] for o in client.get(f"/api/projects/{project['id']}/outputs").json()}
    assert {"pptx", "video", "slide_image"} <= outs


def test_timeline_contents(media_project):
    client, project, _, extra = media_project
    tl = client.get(f"/api/projects/{project['id']}/timeline").json()
    types = [c["type"] for c in tl["clips"]]
    assert types[0] == "intro" and types[-1] == "outro"
    assert "video" in types and "image" in types
    assert tl["music"]["asset_id"] == extra["music"]["id"] and tl["narration"]["mode"] == "none"
    assert "final" in tl["rendered"]


def test_timeline_validation(media_project):
    client, project, _, _ = media_project
    url = f"/api/projects/{project['id']}/timeline"
    tl = client.get(url).json()
    vid = next(c for c in tl["clips"] if c["type"] == "video")
    vid.update(trim_start=5.0, trim_end=4.0)
    assert client.put(url, json=tl).status_code == 422
    vid.update(trim_start=0.0, trim_end=None, speed=9)
    assert client.put(url, json=tl).status_code == 422
    vid.update(speed=1.0, asset_id="med_missing")
    assert client.put(url, json=tl).status_code == 422


def test_edit_and_render_preview(media_project):
    from backend.pipeline.jobs import runner

    client, project, _, extra = media_project
    url = f"/api/projects/{project['id']}/timeline"
    tl = client.get(url).json()
    vid = next(c for c in tl["clips"] if c["type"] == "video")
    vid.update(trim_start=1.0, trim_end=7.0, speed=2.0, crop={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}, keep_audio=True)
    voice = client.post("/api/media/upload", files={"files": ("voice.wav", make_audio(extra["dir"] / "voice.wav", 2.5, 330).read_bytes(), "audio/wav")}).json()[0]
    slide = next(c for c in tl["clips"] if c["type"] == "slide")
    slide["narration_asset_id"] = voice["id"]
    tl["clips"].remove(next(c for c in tl["clips"] if c["type"] == "outro"))
    r = client.put(url, json=tl)
    assert r.status_code == 200, r.text
    job = client.post(f"/api/projects/{project['id']}/video/render", json={"quality": "preview"}).json()
    runner.run_inline(job["id"])
    assert client.get(f"/api/generation/{job['id']}").json()["status"] in ("completed", "completed_with_warnings")
    tl = client.get(url).json()
    rendered = tl["rendered"]["preview"]
    clips = {c["id"]: c for c in rendered["clips"]}
    assert "outro" not in [c["type"] for c in rendered["clips"]]
    from backend.rendering.video.motion import TRANSITION_SECONDS

    rv = clips[vid["id"]]
    # trimmed 6 s at 2x = 3 s, plus the incoming transition that is rendered at the start of the clip
    assert rv["end"] - rv["start"] == pytest.approx((7.0 - 1.0) / 2.0 + TRANSITION_SECONDS[vid["transition"]], abs=0.2)
    rs = clips[slide["id"]]
    assert rs["end"] - rs["start"] >= 2.5  # a still clip stretches to fit the uploaded narration
    r = client.get(f"/api/projects/{project['id']}/files/video/preview.mp4")
    assert r.status_code == 200
    p = extra["dir"] / "preview.mp4"
    p.write_bytes(r.content)
    assert media_duration(FF, p) == pytest.approx(rendered["duration"], abs=0.6)
    assert media_streams(FF, p)["Audio"] == 1


def test_script_import_and_template_gallery(media_project):
    client, _, _, _ = media_project
    r = client.post("/api/scripts/parse", files={"file": ("s.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHello world.\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond line.\n", "text/plain")})
    assert r.status_code == 200 and r.json()["script"] == "Hello world.\nSecond line."
    assert client.post("/api/scripts/parse", files={"file": ("s.exe", b"x", "application/octet-stream")}).status_code == 400
    g = client.get("/api/templates/gallery?brand_id=zensar").json()
    assert {"preset:zensar_corporate", "preset:zensar_midnight"} <= {t["id"] for t in g}
    r = client.get(g[1]["previews"][0])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
