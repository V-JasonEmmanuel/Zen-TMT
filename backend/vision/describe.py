"""Local vision model (Ollama multimodal, e.g. qwen2.5vl:3b / llava / moondream) that describes
video keyframes. Nothing leaves the machine. Without a vision model, frames are still used as
visuals but descriptions are marked unavailable (the user is told how to enable it)."""
from __future__ import annotations

import base64
import io
import re
from typing import Optional

import httpx
from PIL import Image
from pydantic import BaseModel

from backend.llm.structured_output import StructuredOutputError, parse_model
from backend.storage.database import get_db
from backend.utils.logging import get_logger

log = get_logger(__name__)
VISION_HINTS = ("vl", "llava", "moondream", "vision", "bakllava", "minicpm-v", "gemma3")


class FrameDescription(BaseModel):
    screen: str = ""  # which application/page is shown
    visible_text: str = ""  # headings, labels, key numbers readable on screen
    action: str = ""  # what the user is doing / what changed
    description: str = ""  # 1-3 sentence summary


PROMPT = """You are analysing one frame from a software product demo video (a screen recording).
Describe ONLY what is visible. Do not guess hidden functionality.
{context}
Return JSON with:
- screen: the application screen or page shown (a few words)
- visible_text: the most important readable text on screen (titles, buttons, labels, numbers), max 25 words
- action: what the user appears to be doing or what changed compared with the previous frame
- description: 1-3 plain sentences describing the frame for a narrator"""


def _host() -> str:
    rs = get_db().runtime_settings()
    return re.sub(r"//localhost(?=[:/]|$)", "//127.0.0.1", rs.ollama_host.rstrip("/"))


def pick_vision_model() -> Optional[str]:
    rs = get_db().runtime_settings()
    chosen = (rs.extra or {}).get("vision_model")
    try:
        names = [m["name"] for m in httpx.get(f"{_host()}/api/tags", timeout=4).json().get("models", [])]
    except Exception:
        return None
    if chosen and chosen in names:
        return chosen
    for n in names:
        base = n.split(":")[0].lower()
        if any(h in base for h in VISION_HINTS):
            return n
    return None


def _b64(path: str, max_side: int = 896) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def describe_frame(model: str, frame_path: str, previous: str = "", timeout: int = 180) -> FrameDescription:
    ctx = f"Previous frame (for continuity): {previous[:300]}" if previous else ""
    body = {"model": model, "stream": False, "keep_alive": "5m",
            "options": {"temperature": 0.1, "num_predict": 300},
            "format": FrameDescription.model_json_schema(),
            "messages": [{"role": "user", "content": PROMPT.format(context=ctx), "images": [_b64(frame_path)]}]}
    r = httpx.post(f"{_host()}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    text = (r.json().get("message") or {}).get("content", "")
    try:
        d = parse_model(text, FrameDescription)
    except StructuredOutputError:
        d = FrameDescription(description=text.strip()[:500])
    if not d.description:
        d.description = " ".join(x for x in (d.screen, d.action) if x)
    return d


def unload(model: str) -> None:
    try:
        httpx.post(f"{_host()}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
    except Exception:
        pass
