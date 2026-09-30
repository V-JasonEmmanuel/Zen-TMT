"""Creates the "InvoiceFlow showcase" project through the API - every feature in one run.

Start the app first (start.bat), then:
    python samples/run_showcase.py              # document + demo video, AI writing if a local model is ready
    python samples/run_showcase.py --github     # also import this project's GitHub repository as a third source

What it exercises
  sources      the Word case study + the demo screen recording (+ optionally a GitHub repository)
  design       the Zensar Experience template (LinkedIn design language)
  video        motion graphics, brand intro/outro, background music, a script for slides 1-2,
               an extra image, frame-by-frame narration of the demo video
  editing      trims / speeds up / crops the demo clip on the timeline and renders a quick preview
Open the printed link to review the slides, visuals and video, and to keep editing in the video editor.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API = "http://127.0.0.1:8000/api"
REPO = "https://github.com/V-JasonEmmanuel/Zen-TMT"


def wait(c: httpx.Client, job_id: str) -> dict:
    last = ""
    while True:
        j = c.get(f"{API}/generation/{job_id}").json()
        run = next((f"{s['label']}: {s['message']}" for s in j["stages"] if s["status"] == "running"), "")
        if run and run != last:
            print(f"   {run[:110]}")
            last = run
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(3)


def upload(c: httpx.Client, path: Path, media: bool = False) -> dict:
    with open(path, "rb") as f:
        r = c.post(f"{API}/{'media/upload' if media else 'documents/upload'}", files={("files" if media else "file"): (path.name, f)})
    r.raise_for_status()
    j = r.json()
    return j[0] if isinstance(j, list) else j


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true", help=f"also import {REPO} (needs internet once)")
    a = ap.parse_args()
    if not (HERE / "demo_invoiceflow.mp4").exists():
        print("Generating the sample files first ...")
        import runpy

        runpy.run_path(str(HERE / "make_showcase.py"), run_name="__main__")
    c = httpx.Client(timeout=900)
    try:
        c.get(f"{API}/health").raise_for_status()
    except Exception:
        print("The app is not running - start it with start.bat and try again.")
        return 1

    print("1/5 Uploading sources ...")
    sources = [upload(c, HERE / "InvoiceFlow_Showcase.docx"), upload(c, HERE / "demo_invoiceflow.mp4")]
    if a.github:
        r = c.post(f"{API}/documents/github", json={"url": REPO})
        if r.status_code == 200:
            sources.append(r.json())
        else:
            print("   GitHub import skipped:", r.json().get("detail"))
    for s in sources:
        print(f"   {s['filename']} ({s['kind']})")
    music = upload(c, HERE / "background_music.mp3", media=True)
    backdrop = upload(c, HERE / "brand_backdrop.png", media=True)

    status = c.get(f"{API}/system/status").json()
    mode = "llm" if status["ollama"]["model_ready"] else "extractive"
    print(f"2/5 Creating the project (writing: {mode}, template: Zensar Experience) ...")
    p = c.post(f"{API}/projects", json={
        "name": "InvoiceFlow showcase", "document_ids": [s["id"] for s in sources],
        "instruction": "Create a 10-slide client presentation about InvoiceFlow: overview, the problem, architecture, "
                       "workflow, results with the key metrics, before and after, and recommendations.",
        "output_formats": ["pptx", "pdf", "png", "mp4"],
        "options": {"writing_mode": mode, "template_id": "preset:zensar_experience", "narration_mode": "tts",
                    "script": (HERE / "narration_script.md").read_text(encoding="utf-8"),
                    "music_asset_id": music["id"], "video_media": [backdrop["id"]], "transition": "zensar_grid",
                    "motion": "subtle", "intro": True, "outro": True, "subtitles": True}}).json()

    print("3/5 Generating (a demo video is analysed frame by frame; allow a few minutes) ...")
    j = wait(c, c.post(f"{API}/generate", json={"project_id": p["id"]}).json()["id"])
    print(f"   {j['status']}")
    for s in j["stages"]:
        print(f"   {s['status']:8} {s['label']:44} {s['message'][:80]}")

    print("4/5 Editing the video: trim, speed up and crop the demo clip ...")
    tl = c.get(f"{API}/projects/{p['id']}/timeline").json()
    demo = next((cl for cl in tl["clips"] if cl["type"] == "video"), None)
    if demo:
        demo.update(trim_start=2.0, speed=1.25, crop={"x": 0.0, "y": 0.0, "w": 0.94, "h": 1.0})
        c.put(f"{API}/projects/{p['id']}/timeline", json=tl).raise_for_status()
    print("5/5 Rendering a quick preview of the edited video ...")
    j = wait(c, c.post(f"{API}/projects/{p['id']}/video/render", json={"quality": "preview"}).json()["id"])
    print(f"   {j['status']}")
    print(f"\nDone. Open http://localhost:8000/projects/{p['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
