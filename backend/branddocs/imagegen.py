"""Images for brand documents: generated on this computer from the document's own content.

* Prompts are written from each section (its heading and key terms; the local LLM can describe a scene
  when it is installed) plus the visual style measured from the reference's photos.
* A local Stable Diffusion 1.5 model (DreamShaper 8 LCM, CreativeML OpenRAIL-M - commercial use allowed)
  runs in a separate worker process, offline (models/imagegen). CUDA is used when available, else CPU.
* Every image is colour-graded to the reference photos (CIELAB statistics) so it sits in the brand palette,
  then scaled to print resolution. Results are cached by prompt.
* Without the model, a brand-coloured abstract artwork is drawn instead (the report says so).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from backend.branddocs.model import ImageStyle
from backend.utils.config import get_settings
from backend.utils.logging import get_logger

log = get_logger(__name__)
MODEL_NAME = "dreamshaper-8-lcm"
CHECKPOINT = "DreamShaper8_LCM.safetensors"
STOP = set("""a an the and or but if then than that this these those to of in on at by for with from as is are was were be been being it its
we our you your they their them he she his her i me my not no yes do does did done can could should would will shall may might must
have has had about into over under more most less very just also only such so too what which who whom whose when where why how all
any each every some many much few other another same own here there out up down off again further once both between through during
before after above below while because until against among per via within without across like get gets got make makes made use used
using one two three new way ways thing things lot lots really still even often usually doesn don isn aren wasn weren let lets
table tables figure figures below above shows show shown showing following section sections paper chapter example examples
results result based need needs needed want wants help helps important simple simply first second third""".split())
UNSAFE = re.compile(r"\b(nude|naked|sex\w*|porn\w*|erotic|gore|blood\w*|kill\w*|corpse|weapon\w*|gun\w*|terror\w*|suicide|drug\w*)\b", re.I)


def model_dir() -> Path:
    return get_settings().models_path / "imagegen" / MODEL_NAME


def status() -> dict:
    """Is local image generation usable? (model files + libraries; no import of torch here)."""
    import importlib.util as u

    d = model_dir()
    have_model = (d / CHECKPOINT).exists() and (d / "model_index.json").exists()
    libs = all(u.find_spec(m) is not None for m in ("torch", "diffusers", "transformers"))
    msg = "ready" if have_model and libs else ("the image model is not installed (run scripts/fetch_models.py --images)" if not have_model
                                               else "the image libraries are not installed (pip install diffusers)")
    return {"available": have_model and libs, "message": msg, "model": MODEL_NAME, "license": "CreativeML OpenRAIL-M"}


# ------------------------------------------------------------------ prompts
def key_terms(text: str, n: int = 4) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text)
    c = Counter(w.lower() for w in words if w.lower() not in STOP)
    return [w for w, _ in c.most_common(n)]


def section_prompt(title: str, text: str, style: str) -> str:
    subject = re.sub(r"[?!:;\"“”]", "", title).strip() or " ".join(key_terms(text, 3))
    terms = [t for t in key_terms(title + " " + text, 5) if t not in subject.lower()][:3]
    scene = f"{subject}, visual metaphor of {', '.join(terms)}" if terms else subject
    return _safe(f"{scene}, {style}")


def _safe(p: str) -> str:
    return re.sub(r"\s{2,}", " ", UNSAFE.sub("", p)).strip(" ,")


def llm_scenes(items: list[tuple[str, str]]) -> Optional[list[str]]:
    """Ask the local LLM (if running) for one concrete visual scene per section; None when unavailable."""
    try:
        from backend.llm import get_llm

        llm = get_llm()
        if not llm.is_available():
            return None
        listing = "\n".join(f"{i + 1}. {t}: {txt[:400]}" for i, (t, txt) in enumerate(items))
        # the same text gets the same descriptions (so re-running reuses the images already created)
        cache_f = get_settings().data_path / "branddocs" / "scenecache.json"
        key = hashlib.sha256(listing.encode()).hexdigest()[:24]
        try:
            cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
        except ValueError:
            cache = {}
        if isinstance(cache.get(key), list) and len(cache[key]) == len(items):
            return cache[key]
        out = llm.generate(
            "For each numbered section below, describe ONE photograph or concept image that would illustrate it in a corporate "
            "white paper. Concrete subject and setting, 12-25 words, no text or logos in the image, no brand names. "
            "Answer with one line per section, numbered the same way.\n\n" + listing,
            system="You write short, concrete image descriptions for illustrators.")
        lines = [re.sub(r"^\s*\d+[.)]\s*", "", ln).strip() for ln in out.splitlines() if re.match(r"^\s*\d+[.)]", ln)]
        if len(lines) == len(items) and all(lines):
            cache[key] = lines
            cache_f.parent.mkdir(parents=True, exist_ok=True)
            cache_f.write_text(json.dumps(dict(list(cache.items())[-200:]), indent=1), encoding="utf-8")
            return lines
        return None
    except Exception as exc:
        log.info("LLM scene descriptions unavailable", error=str(exc)[:120])
        return None


# ------------------------------------------------------------------ colour grading
def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    from backend.branddocs.reference import _rgb_to_lab as f

    return f(rgb)


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    c = xyz @ m.T
    c = np.where(c > 0.0031308, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(c * 255, 0, 255)


def grade(img: Image.Image, st: ImageStyle, strength: float = 0.75) -> Image.Image:
    """Reinhard colour transfer towards the reference photos' CIELAB mean/std."""
    if len(st.lab_mean) != 3 or len(st.lab_std) != 3:
        return img
    arr = np.asarray(img.convert("RGB")).astype(float)
    lab = _rgb_to_lab(arr)
    mu, sd = lab.reshape(-1, 3).mean(axis=0), lab.reshape(-1, 3).std(axis=0) + 1e-6
    tm, ts = np.array(st.lab_mean), np.array(st.lab_std)
    out = (lab - mu) / sd * ts + tm
    out = lab + (out - lab) * strength
    return Image.fromarray(_lab_to_rgb(out).astype(np.uint8))


def finish(img: Image.Image, st: ImageStyle, size: tuple[int, int]) -> Image.Image:
    img = grade(img, st)
    img = img.resize(size, Image.LANCZOS)
    return img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=2))


def brand_art(size: tuple[int, int], palette: list[str], seed: int = 7) -> Image.Image:
    """Fallback artwork when no image model is available: soft light and circles in the reference palette."""
    rng = np.random.default_rng(seed)
    cols = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in (palette or ["#101030", "#303080", "#E0E0F0"])]
    cols.sort(key=lambda c: sum(c))
    dark, mid, light = cols[0], cols[len(cols) // 2], cols[-1]
    w, h = size
    y = np.linspace(0, 1, h)[:, None, None]
    base = (np.array(mid) * (1 - y) + np.array(dark) * y) * np.ones((1, w, 1))
    img = Image.fromarray(base.astype(np.uint8))
    glow = Image.new("L", size, 0)
    d = ImageDraw.Draw(glow)
    cx, cy = int(w * rng.uniform(0.3, 0.7)), int(h * rng.uniform(0.15, 0.4))
    r = int(min(w, h) * 0.35)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=170)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.12))
    img = Image.composite(Image.new("RGB", size, light), img, glow)
    over = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for _ in range(3):
        rr = int(min(w, h) * rng.uniform(0.25, 0.6))
        x, yy = int(w * rng.uniform(0, 1)), int(h * rng.uniform(0.2, 1))
        d.ellipse([x - rr, yy - rr, x + rr, yy + rr], fill=(*mid, 38))
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


# ------------------------------------------------------------------ generation
@dataclass
class ImageJob:
    key: str  # "cover", "section-3"
    prompt: str
    w: int  # generation size (multiple of 8)
    h: int
    out_size: tuple[int, int]  # final pixels
    seed: int = 7
    result: Optional[Path] = None
    generated: bool = False
    meta: dict = field(default_factory=dict)


def _cache_dir() -> Path:
    d = get_settings().data_path / "branddocs" / "imagecache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(j: ImageJob, negative: str, steps: int) -> str:
    return hashlib.sha256(f"{MODEL_NAME}|{j.prompt}|{negative}|{j.w}x{j.h}|{j.seed}|{steps}".encode()).hexdigest()[:24]


def run(jobs: list[ImageJob], style: ImageStyle, out_dir: Path, on_progress: Callable[[str], None] = lambda m: None,
        use_model: bool = True, steps: int = 5) -> list[str]:
    """Fill job.result for every job. Returns notes for the report."""
    notes: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    negative = style.negative
    st = status()
    todo = []
    for j in jobs:
        raw = _cache_dir() / f"{_cache_key(j, negative, steps)}.png"
        j.meta["raw"] = str(raw)
        if raw.exists():
            j.generated = True
        elif use_model and st["available"]:
            todo.append(j)
    if todo:
        on_progress(f"Loading the image model ({len(todo)} image{'s' if len(todo) > 1 else ''} to create)")
        with tempfile.TemporaryDirectory() as td:
            spec = {"model_dir": str(model_dir()), "checkpoint": str(model_dir() / CHECKPOINT),
                    "jobs": [{"prompt": j.prompt, "negative": negative, "w": j.w, "h": j.h, "seed": j.seed, "steps": steps,
                              "guidance": 1.5, "out": j.meta["raw"]} for j in todo]}
            jf = Path(td) / "job.json"
            jf.write_text(json.dumps(spec), encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            proc = subprocess.Popen([sys.executable, "-m", "backend.branddocs.imagegen_worker", str(jf)], cwd=str(root),
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            device = "cpu"
            done = 0
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") == "loaded":
                        device = ev.get("device", "cpu")
                        on_progress(f"Creating image 1 of {len(todo)} on the {'GPU' if device == 'cuda' else 'CPU'}")
                    elif ev.get("event") == "image":
                        done += 1
                        todo[ev["i"]].generated = True
                        if done < len(todo):
                            on_progress(f"Creating image {done + 1} of {len(todo)} on the {'GPU' if device == 'cuda' else 'CPU'}")
                    elif ev.get("event") == "error":
                        notes.append(f"Image generation: {ev.get('message', 'failed')}")
                proc.wait(timeout=60)
            finally:
                if proc.poll() is None:
                    proc.kill()
            if device == "cpu" and done:
                notes.append("Images were created on the CPU. A CUDA build of PyTorch would use the GPU and be about 10x faster.")
    elif use_model and not st["available"]:
        notes.append(f"Local image generation is not available ({st['message']}); brand-coloured artwork was used instead.")
    for j in jobs:
        out = out_dir / f"{j.key}.jpg"
        if j.generated and Path(j.meta["raw"]).exists():
            img = finish(Image.open(j.meta["raw"]).convert("RGB"), style, j.out_size)
        else:
            img = brand_art(j.out_size, style.palette, seed=j.seed)
            j.generated = False
        img.save(out, quality=90)
        j.result = out
    return notes
