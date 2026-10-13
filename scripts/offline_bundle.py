"""Offline bundle for machines that can reach GitHub (git) but not pypi.org / huggingface.co.

    python scripts/offline_bundle.py build    <bundle_dir>             # on a PC with internet
    python scripts/offline_bundle.py assemble <bundle_dir> <out_dir>   # on the server (start.bat does this)

The bundle repository (https://github.com/V-JasonEmmanuel/Zen-TMT-offline) holds:
    wheels/   every Python package for Windows x64 + Python 3.12 (incl. the CUDA build of PyTorch)
    models/   the embedding model (ONNX) and the image model (DreamShaper 8 LCM)
    extras/   the Microsoft Visual C++ runtime installer
GitHub refuses files over 100 MB, so large files are stored as numbered pieces; manifest.json lists every
file with its size and SHA-256, and `assemble` joins and verifies them. Standard library only (runs before
any package is installed).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

PIECE = 95 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(bundle: Path) -> int:
    bundle.mkdir(parents=True, exist_ok=True)
    # models from this installation
    for rel in ("models/embeddings", "models/imagegen"):
        src = ROOT / rel
        if src.exists():
            dst = bundle / rel
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".cache", "*.lock", "*.part"))
    manifest = {"version": 1, "files": {}}
    for f in sorted(p for p in bundle.rglob("*") if p.is_file()):
        rel = f.relative_to(bundle).as_posix()
        if rel.startswith(".git/") or rel in ("manifest.json", "README.md", ".gitattributes") or ".part" in f.name:
            continue
        size = f.stat().st_size
        entry = {"size": size, "sha256": sha256(f), "pieces": 0}
        if size > PIECE:
            n = 0
            with open(f, "rb") as src:
                while True:
                    chunk = src.read(PIECE)
                    if not chunk:
                        break
                    (f.parent / f"{f.name}.part{n:03d}").write_bytes(chunk)
                    n += 1
            entry["pieces"] = n
            f.unlink()
        manifest["files"][rel] = entry
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(e["size"] for e in manifest["files"].values())
    print(f"Bundle ready: {len(manifest['files'])} files, {total / 1e9:.2f} GB")
    return 0


def assemble(bundle: Path, out: Path) -> int:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    done = out / ".assembled"
    stamp = sha256(bundle / "manifest.json")
    if done.exists() and done.read_text().strip() == stamp:
        print("Offline bundle already assembled")
        return 0
    bad = 0
    for rel, e in manifest["files"].items():
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.stat().st_size == e["size"] and sha256(dst) == e["sha256"]:
            continue
        src = bundle / rel
        if e["pieces"]:
            with open(dst, "wb") as w:
                for n in range(e["pieces"]):
                    with open(src.parent / f"{src.name}.part{n:03d}", "rb") as r:
                        shutil.copyfileobj(r, w, 1 << 20)
        else:
            shutil.copyfile(src, dst)
        if sha256(dst) != e["sha256"]:
            print(f"CHECKSUM MISMATCH: {rel}")
            dst.unlink(missing_ok=True)
            bad += 1
    if bad:
        print(f"{bad} file(s) are damaged - delete the 'offline' folder and run start.bat again.")
        return 1
    done.write_text(stamp)
    print(f"Offline bundle assembled into {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        sys.exit(build(Path(sys.argv[2])))
    if len(sys.argv) >= 4 and sys.argv[1] == "assemble":
        sys.exit(assemble(Path(sys.argv[2]), Path(sys.argv[3])))
    print(__doc__)
    sys.exit(2)
