"""Download the embedding model (ONNX) once, during setup - no torch/transformers needed.

    python scripts/fetch_models.py

Fetches the official ONNX export + tokenizer of sentence-transformers/all-MiniLM-L6-v2 from the
Hugging Face hub into ./models/embeddings/, verifies it runs, and exits. After this the
application never needs the internet for embeddings.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.intelligence.embeddings import onnx_dir_for  # noqa: E402

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FILES = {"model.onnx": f"https://huggingface.co/{MODEL}/resolve/main/onnx/model.onnx",
         "tokenizer.json": f"https://huggingface.co/{MODEL}/resolve/main/tokenizer.json"}


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ZensarContentStudio-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, shown = 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            pct = done * 100 // total if total else 0
            if total and pct // 20 != shown:
                shown = pct // 20
                print(f"  {dest.name}: {pct}%", flush=True)
    tmp.replace(dest)


def main() -> int:
    out = onnx_dir_for(MODEL)
    out.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        if (out / name).exists() and (out / name).stat().st_size > 1000:
            print(f"  {name}: already present")
            continue
        print(f"Downloading {name} ...")
        download(url, out / name)
    from backend.intelligence.embeddings import OnnxEmbedder

    emb = OnnxEmbedder(MODEL, out)
    v = emb.encode(["the cat sat on the mat", "a cat was sitting on a rug", "quarterly revenue grew"])
    sim_close, sim_far = float(v[0] @ v[1]), float(v[0] @ v[2])
    if not sim_close > sim_far + 0.3:
        print("Embedding model verification failed")
        return 1
    print(f"Embedding model ready ({out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
