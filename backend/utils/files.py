"""File-system safety helpers: filename sanitising and path containment."""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class UnsafePathError(ValueError):
    pass


def sanitize_filename(name: str, default: str = "file", max_len: int = 120) -> str:
    """Return a filename safe for any OS: no directories, no traversal, no reserved names."""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = name.replace("\\", "/").split("/")[-1]  # drop any directory component
    name = _SAFE.sub("_", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name or set(name) <= {".", "_"}:
        name = default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    ext = ext[:10]
    stem = stem[: max_len - len(ext) - 1] or default
    return f"{stem}.{ext}" if ext else stem


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].strip("-")) or "project"


def safe_join(base: Path, *parts: str) -> Path:
    """Join `parts` onto `base` and guarantee the result stays inside `base`."""
    base = Path(base).resolve()
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise UnsafePathError("Path escapes the permitted directory") from exc
    return candidate


def is_within(base: Path, path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"
