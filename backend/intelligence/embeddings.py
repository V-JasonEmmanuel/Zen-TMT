"""Local embeddings with lazy loading, caching and graceful fallback.

Resolution order for the configured model name:
  1. ONNX export in ./models/embeddings/<name>/ (fast start: onnxruntime + tokenizers, no torch)
     -> create with `python scripts/prepare_models.py`
  2. sentence-transformers from the local HuggingFace cache (offline, slower to load)
  3. Hashing embedder (lexical only, always available) - reported as degraded
"""
from __future__ import annotations

import json
import os
import re
import threading
import zlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np

from backend.utils.config import get_settings
from backend.utils.logging import get_logger

log = get_logger(__name__)


class Embedder(ABC):
    name: str = ""
    kind: str = ""
    degraded: bool = False

    @abstractmethod
    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Return L2-normalised float32 vectors, shape (n, dim)."""


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (v / n).astype(np.float32)


def onnx_dir_for(model_name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", model_name)
    return get_settings().models_path / "embeddings" / safe


class OnnxEmbedder(Embedder):
    kind = "onnx"

    def __init__(self, model_name: str, model_dir: Path):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.name = model_name
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self._session = ort.InferenceSession(str(model_dir / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tok.enable_truncation(max_length=256)
        self._tok.enable_padding()

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch_size):
            enc = self._tok.encode_batch(texts[i:i + batch_size])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feed)[0]  # (b, seq, dim)
            m = mask[..., None].astype(np.float32)
            out.append((hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None))
        return _normalize(np.vstack(out)) if out else np.zeros((0, 384), np.float32)


class SentenceTransformerEmbedder(Embedder):
    kind = "sentence-transformers"

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        local = get_settings().models_path / model_name
        self._model = SentenceTransformer(str(local) if local.exists() else model_name, device="cpu")

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        v = self._model.encode(texts, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True)
        return _normalize(np.asarray(v, dtype=np.float32))


class HashingEmbedder(Embedder):
    """Deterministic lexical embedding (unigrams + bigrams). Used only as a fallback."""

    kind = "hashing"
    degraded = True

    def __init__(self, dim: int = 1024):
        self.name = f"hashing-{dim}"
        self.dim = dim

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        from backend.intelligence.text import tokenize

        mat = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            toks = tokenize(t)
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for g in grams:
                mat[r, zlib.crc32(g.encode()) % self.dim] += 1.0
        return _normalize(np.log1p(mat))


_lock = threading.Lock()
_instance: Optional[Embedder] = None


def get_embedder(model_name: Optional[str] = None) -> Embedder:
    global _instance
    if model_name is None:
        from backend.storage.database import get_db

        model_name = get_db().runtime_settings().embedding_model or get_settings().embedding_model
    with _lock:
        if _instance is not None and getattr(_instance, "_requested", None) == model_name:
            return _instance
        _instance = _load(model_name)
        _instance._requested = model_name  # type: ignore[attr-defined]
        return _instance


def _load(model_name: str) -> Embedder:
    if os.environ.get("ZCS_EMBEDDER") == "hashing":  # tests / minimal installs
        return HashingEmbedder()
    onnx_dir = onnx_dir_for(model_name)
    if (onnx_dir / "model.onnx").exists() and (onnx_dir / "tokenizer.json").exists():
        try:
            e = OnnxEmbedder(model_name, onnx_dir)
            log.info("Embedding model loaded", backend="onnx", model=model_name)
            return e
        except Exception as exc:
            log.warning("ONNX embedder failed; trying sentence-transformers", error=type(exc).__name__)
    try:
        e = SentenceTransformerEmbedder(model_name)
        log.info("Embedding model loaded", backend="sentence-transformers", model=model_name)
        return e
    except Exception as exc:
        log.warning("Embedding model unavailable; using lexical fallback", error=type(exc).__name__)
        return HashingEmbedder()


def unload_embedder() -> None:
    global _instance
    with _lock:
        _instance = None


def embedder_status() -> dict:
    from backend.storage.database import get_db

    name = get_db().runtime_settings().embedding_model or get_settings().embedding_model
    onnx_ready = (onnx_dir_for(name) / "model.onnx").exists()
    loaded = _instance.kind if _instance else None
    return {"model": name, "onnx_ready": onnx_ready, "loaded_backend": loaded}


# ---------------------------------------------------------------- cached document embeddings
def embed_chunks_cached(doc_dir: Path, chunk_ids: list[str], texts: list[str]) -> tuple[np.ndarray, Embedder]:
    """Embed chunk texts, reusing vectors cached on disk for this document + model."""
    emb = get_embedder()
    key = re.sub(r"[^A-Za-z0-9]+", "_", emb.name)[-60:]
    vec_file, ids_file = doc_dir / f"emb_{key}.npy", doc_dir / f"emb_{key}.json"
    cached: dict[str, np.ndarray] = {}
    if vec_file.exists() and ids_file.exists():
        try:
            vecs = np.load(vec_file)
            ids = json.loads(ids_file.read_text())
            cached = {cid: vecs[i] for i, cid in enumerate(ids)}
        except Exception:
            cached = {}
    missing = [i for i, cid in enumerate(chunk_ids) if cid not in cached]
    if missing:
        new = emb.encode([texts[i] for i in missing])
        for j, i in enumerate(missing):
            cached[chunk_ids[i]] = new[j]
        all_ids = list(cached)
        np.save(vec_file, np.vstack([cached[c] for c in all_ids]))
        ids_file.write_text(json.dumps(all_ids))
        log.info("Embeddings computed", new=len(missing), cached=len(chunk_ids) - len(missing), backend=emb.kind)
    return np.vstack([cached[c] for c in chunk_ids]) if chunk_ids else np.zeros((0, 1), np.float32), emb
