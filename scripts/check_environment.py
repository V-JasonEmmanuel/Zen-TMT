"""Environment check for Zensar Content Studio.

    python scripts/check_environment.py [--quiet]

Exit code 0 = ready (required components present), 1 = something required is missing.
Optional components (GPU, OCR, Piper) only produce notes.
"""
from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK, BAD, NOTE = "✓", "✗", "•"
REQUIRED_PY = ["fastapi", "uvicorn", "pydantic", "pydantic_settings", "multipart", "httpx", "pymupdf", "docx", "pptx",
               "bs4", "lxml", "numpy", "onnxruntime", "tokenizers", "PIL", "matplotlib", "imageio_ffmpeg"]


def line(ok: bool | None, label: str, detail: str = "") -> None:
    mark = OK if ok else (NOTE if ok is None else BAD)
    try:
        print(f"  {mark} {label:<22} {detail}")
    except UnicodeEncodeError:
        print(f"  {'OK' if ok else ('--' if ok is None else 'XX')} {label:<22} {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    failures: list[str] = []
    print("\nZensar Content Studio - environment check\n")

    ok = sys.version_info >= (3, 10)
    line(ok, "Python", sys.version.split()[0])
    if not ok:
        failures.append("Python 3.10+ is required")

    node = shutil.which("node")
    if node:
        v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        line(True, "Node", v)
    else:
        line(False, "Node", "not found (needed to run/build the web interface)")
        failures.append("Node.js 18+ is required for the interface")
    nm = (ROOT / "frontend" / "node_modules").exists()
    dist = (ROOT / "frontend" / "dist" / "index.html").exists()
    line(nm or dist, "Node packages", "installed" if nm else ("built UI present" if dist else "run: npm install --prefix frontend"))
    if not (nm or dist):
        failures.append("Frontend packages are not installed")

    missing = []
    for mod in REQUIRED_PY:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    line(not missing, "Python packages", "all present" if not missing else "missing: " + ", ".join(missing))
    if missing:
        failures.append("Install Python packages: pip install -r requirements.txt")
        print("\nSystem not ready.\n  - " + "\n  - ".join(failures))
        return 1

    from backend.utils.config import get_settings

    s = get_settings()
    s.ensure_dirs()
    from backend.storage.database import get_db

    rs = get_db().runtime_settings()

    # Ollama + model
    import httpx

    host = rs.ollama_host.replace("//localhost", "//127.0.0.1")
    try:
        models = [m["name"] for m in httpx.get(f"{host}/api/tags", timeout=4).json().get("models", [])]
        line(True, "Ollama", f"running at {rs.ollama_host} ({len(models)} model(s))")
        chosen = rs.ollama_model
        if chosen and (chosen in models or f"{chosen}:latest" in models):
            line(True, "Model", chosen)
        elif models:
            line(None, "Model", f"none selected - choose one in Settings (installed: {', '.join(models[:4])})")
        else:
            line(None, "Model", "no models installed - e.g. `ollama pull qwen2.5:3b` (extractive mode still works)")
    except Exception:
        line(None, "Ollama", "not running - start Ollama for AI writing (extractive mode still works)")

    from backend.intelligence.embeddings import onnx_dir_for

    onnx = (onnx_dir_for(rs.embedding_model) / "model.onnx").exists()
    line(onnx, "Embedding model", rs.embedding_model if onnx else "not prepared - run: python scripts/prepare_models.py")
    if not onnx:
        failures.append("Prepare the embedding model once: python scripts/prepare_models.py")

    from backend.rendering.video.ffmpeg import find_ffmpeg

    ff = find_ffmpeg(rs.ffmpeg_path)
    line(bool(ff), "FFmpeg", ff or "not found")
    if not ff:
        failures.append("FFmpeg not found (pip install imageio-ffmpeg or set FFMPEG_PATH)")

    from backend.rendering.video.narration import tts_status

    t = tts_status()
    voices = sum(len(v) for v in t["engines"].values())
    line(t["available"] or None, "TTS", f"{', '.join(t['engines'])} - {voices} voice(s)" if t["available"] else "no offline voice (videos will be silent)")

    from backend.extraction.ocr import ocr_status

    o = ocr_status()
    line(o["available"] or None, "OCR (optional)", o["engine"] or "not installed - only needed for scanned PDFs")

    free = shutil.disk_usage(s.data_path).free / 1e9
    line(free > 5, "Disk space", f"{free:.1f} GB free")
    if free < 2:
        failures.append("Less than 2 GB of free disk space")

    gpu = shutil.which("nvidia-smi")
    if gpu:
        r = subprocess.run([gpu, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
        line(None, "GPU (optional)", r.stdout.strip().splitlines()[0] if r.stdout.strip() else "present")
    else:
        line(None, "GPU (optional)", "none detected - CPU mode")

    print()
    if failures:
        print("System not ready:\n  - " + "\n  - ".join(failures) + "\n")
        return 1
    print("System ready.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
