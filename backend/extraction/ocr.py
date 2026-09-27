"""Modular offline OCR. Engines are optional; `get_ocr_engine()` returns None when none is usable.

Supported (auto-detected in this order):
  * RapidOCR (pip install rapidocr_onnxruntime) - pure pip, ONNX, no system install
  * Tesseract (system binary + pytesseract)
"""
from __future__ import annotations

import io
import shutil
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Optional

from backend.utils.logging import get_logger

log = get_logger(__name__)


class OCREngine(ABC):
    name = ""

    @abstractmethod
    def image_to_text(self, png_bytes: bytes) -> str: ...


class RapidOCREngine(OCREngine):
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        self._engine = RapidOCR()

    def image_to_text(self, png_bytes: bytes) -> str:
        result, _ = self._engine(png_bytes)
        if not result:
            return ""
        # result: [box, text, score]; group lines into paragraphs by vertical gaps
        lines = sorted(((r[0][0][1], r[0][0][0], r[1]) for r in result), key=lambda t: (round(t[0] / 10), t[1]))
        out, last_y = [], None
        for y, _, text in lines:
            if last_y is not None and y - last_y > 40:
                out.append("")
            out.append(text)
            last_y = y
        return "\n".join(out)


class TesseractEngine(OCREngine):
    name = "tesseract"

    def __init__(self):
        import pytesseract  # type: ignore

        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract binary not found")
        self._pt = pytesseract

    def image_to_text(self, png_bytes: bytes) -> str:
        from PIL import Image

        return self._pt.image_to_string(Image.open(io.BytesIO(png_bytes)))


@lru_cache(maxsize=1)
def _detect() -> Optional[OCREngine]:
    for cls in (RapidOCREngine, TesseractEngine):
        try:
            engine = cls()
            log.info("OCR engine available", engine=cls.name)
            return engine
        except Exception:
            continue
    log.info("No OCR engine available")
    return None


def get_ocr_engine() -> Optional[OCREngine]:
    from backend.storage.database import get_db

    try:
        if not get_db().runtime_settings().ocr_enabled:
            return None
    except Exception:
        pass
    return _detect()


def ocr_status() -> dict:
    engine = _detect()
    return {"available": engine is not None, "engine": engine.name if engine else None}
