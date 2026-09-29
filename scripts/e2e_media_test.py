"""End-to-end check of the media features against a running server (http://127.0.0.1:8000).

  python scripts/e2e_media_test.py [--github URL] [--skip-demo]

1. Demo project: demo video + spec document (multi-source), Bold template, background music,
   local-AI writing, video timeline with motion graphics and scene narration.
2. GitHub project: repository import -> slides + architecture/pipeline visuals + video.
3. Video editing: trim / crop / speed an existing clip, insert an image, upload narration audio,
   apply a script, re-render a preview.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
B = "http://127.0.0.1:8000/api"
c = httpx.Client(timeout=600)


def wait(job_id: str, label: str) -> dict:
    t0, last = time.time(), ""
    while True:
        j = c.get(f"{B}/generation/{job_id}").json()
        msg = next((f"{s['label']}: {s['message']}" for s in j["stages"] if s["status"] == "running"), "")
        if msg and msg != last:
            print(f"   [{time.time() - t0:5.0f}s] {msg[:110]}")
            last = msg
        if j["status"] not in ("queued", "running"):
            print(f" {label}: {j['status']} in {time.time() - t0:.0f}s")
            for s in j["stages"]:
                print(f"   {s['status']:8} {s['label']:44} {s['message'][:100]}")
            if j["warnings"]:
                print("   notes:", j["warnings"][:4])
            return j
        time.sleep(3)


def upload(path: Path, endpoint: str = "documents/upload") -> dict:
    with open(path, "rb") as f:
        r = c.post(f"{B}/{endpoint}", files={("file" if "documents" in endpoint else "files"): (path.name, f)})
    r.raise_for_status()
    j = r.json()
    return j[0] if isinstance(j, list) else j


def ffmpeg() -> str:
    from backend.rendering.video.ffmpeg import find_ffmpeg

    return find_ffmpeg()


def demo_project() -> str:
    fx = ROOT / "tests" / "fixtures"
    video = fx / "demo_invoiceflow.mp4"
    if not video.exists():
        from tests.fixtures.make_demo_video import make_demo_video

        make_demo_video(video, ffmpeg())
    spec = fx / "invoiceflow_spec.md"
    spec.write_text("# InvoiceFlow product brief\n\n## Overview\n\nInvoiceFlow automates accounts-payable invoice processing for "
                    "finance teams. Uploaded PDF invoices are read, key fields are extracted and invoices under the approval "
                    "threshold are approved automatically.\n\n## Architecture\n\nThe platform has four components: an Upload "
                    "Service that receives PDF invoices, an Extraction Engine that reads vendor, invoice number and amount, a Rules "
                    "Engine that applies the approval threshold, and an ERP Connector that exports approved invoices to SAP S/4HANA.\n\n"
                    "## Results\n\nIn the pilot, 86% of invoices were approved automatically and the average processing time "
                    "fell to 42 seconds per invoice.\n", encoding="utf-8")
    music = fx / "music_bed.mp3"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=196:d=20", "-f", "lavfi", "-i",
                    "sine=f=294:d=20", "-filter_complex", "amix=inputs=2,volume=0.6", str(music)], check=True)
    print("Uploading sources ...")
    v = upload(video)
    d = upload(spec)
    m = upload(music, "media/upload")
    print(f"  video {v['id']} ({v['kind']}, deferred={v['deferred']}), spec {d['id']} ({d['status']}), music asset {m['id']} ({m['kind']}, {m['duration']}s)")
    p = c.post(f"{B}/projects", json={
        "name": "InvoiceFlow demo walkthrough", "document_ids": [v["id"], d["id"]],
        "instruction": "Create a 6-slide client presentation explaining the InvoiceFlow product: overview, how it works (workflow), "
                       "architecture and results.",
        "output_formats": ["pptx", "pdf", "png", "mp4"],
        "options": {"writing_mode": "llm", "template_id": "preset:zensar_bold", "music_asset_id": m["id"], "narration_mode": "tts"}}).json()
    print("Project", p["id"], "sources:", [s["filename"] for s in p["sources"]])
    job = c.post(f"{B}/generate", json={"project_id": p["id"]}).json()
    wait(job["id"], "Demo project generation")
    plan = c.get(f"{B}/projects/{p['id']}/plan").json()
    for s in plan["slides"]:
        vis = s.get("visual") or {}
        print(f"  #{s['slide_number']} [{s['layout']}] {s['title']} | visual={vis.get('kind')} nodes={[n['label'] for n in vis.get('nodes', [])]}")
    tl = c.get(f"{B}/projects/{p['id']}/timeline").json()
    print("  timeline:", [(cl["type"], cl["label"][:30]) for cl in tl["clips"]])
    demo = next(cl for cl in tl["clips"] if cl["type"] == "video")
    print("  demo narration segments:", [(sg["start"], sg["text"][:60]) for sg in demo["narration_segments"]])
    return p["id"]


def edit_video(pid: str) -> None:
    print("\nVideo editing: trim/crop/speed, insert image, narration upload, script ...")
    tl = c.get(f"{B}/projects/{pid}/timeline").json()
    vid = next(cl for cl in tl["clips"] if cl["type"] == "video")
    vid.update(trim_start=5.0, trim_end=20.0, speed=1.25, crop={"x": 0.05, "y": 0.0, "w": 0.9, "h": 1.0})
    from PIL import Image

    img = ROOT / "tests" / "fixtures" / "office.jpg"
    Image.new("RGB", (1600, 900), (58, 87, 167)).save(img)
    a = upload(img, "media/upload")
    tl["clips"].insert(len(tl["clips"]) - 1, {"type": "image", "asset_id": a["id"], "label": "Team photo", "duration": 4,
                                              "motion": "ken_burns", "transition": "fade"})
    voice = ROOT / "tests" / "fixtures" / "my_voice.wav"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=330:d=3", str(voice)], check=True)
    va = upload(voice, "media/upload")
    first_slide = next(cl for cl in tl["clips"] if cl["type"] == "slide")
    first_slide["narration_asset_id"] = va["id"]
    tl["narration"]["script"] = "## Slide 2\nThis is my own script for the second slide, read by the offline voice."
    r = c.put(f"{B}/projects/{pid}/timeline", json=tl)
    print("  timeline saved:", r.status_code, r.text[:120] if r.status_code != 200 else "")
    job = c.post(f"{B}/projects/{pid}/video/render", json={"quality": "preview"}).json()
    wait(job["id"], "Preview render after edits")
    tl2 = c.get(f"{B}/projects/{pid}/timeline").json()
    print("  rendered clips:", [(x["type"], x["start"], x["end"]) for x in tl2["rendered"].get("preview", {}).get("clips", [])])


def github_project(url: str) -> None:
    print(f"\nGitHub import: {url}")
    r = c.post(f"{B}/documents/github", json={"url": url})
    print("  import:", r.status_code, r.json().get("filename") if r.status_code == 200 else r.text[:200])
    if r.status_code != 200:
        return
    d = r.json()
    p = c.post(f"{B}/projects", json={"name": "Repository explained", "document_ids": [d["id"]],
                                       "instruction": "Create an 7-slide technical presentation explaining this repository: overview, "
                                                      "architecture, workflow, technology stack and API.",
                                       "output_formats": ["pptx", "png", "mp4"],
                                       "options": {"writing_mode": "extractive", "template_id": "preset:zensar_tech"}}).json()
    job = c.post(f"{B}/generate", json={"project_id": p["id"]}).json()
    wait(job["id"], "GitHub project generation")
    plan = c.get(f"{B}/projects/{p['id']}/plan").json()
    for s in plan["slides"]:
        vis = s.get("visual") or {}
        print(f"  #{s['slide_number']} [{s['layout']}] {s['title'][:50]} | visual={vis.get('kind')} nodes={[n['label'] for n in vis.get('nodes', [])][:8]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", default="https://github.com/V-JasonEmmanuel/Zen-TMT")
    ap.add_argument("--skip-demo", action="store_true")
    a = ap.parse_args()
    if not a.skip_demo:
        pid = demo_project()
        edit_video(pid)
    if a.github:
        github_project(a.github)
