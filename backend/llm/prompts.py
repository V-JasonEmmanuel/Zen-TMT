"""Versioned prompt templates loaded from backend/llm/prompts/*.txt.

File format: optional header lines `# key: value` (e.g. `# version: 3`), then the body.
Placeholders use {{name}}. Missing placeholders raise, so prompts never ship half-filled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    body: str

    def render(self, **values: object) -> str:
        missing = {m for m in _VAR.findall(self.body) if m not in values}
        if missing:
            raise KeyError(f"Prompt '{self.name}' missing values: {sorted(missing)}")
        return _VAR.sub(lambda m: str(values[m.group(1)]), self.body)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> Prompt:
    path = PROMPT_DIR / f"{name}.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    meta, i = {}, 0
    while i < len(lines) and lines[i].startswith("#"):
        k, _, v = lines[i][1:].partition(":")
        meta[k.strip()] = v.strip()
        i += 1
    return Prompt(name=name, version=meta.get("version", "1"), body="\n".join(lines[i:]).strip())


def system_prompt() -> str:
    return load_prompt("system").body


def prompt_versions() -> dict[str, str]:
    return {p.stem: load_prompt(p.stem).version for p in sorted(PROMPT_DIR.glob("*.txt"))}
