"""LLM access. `get_llm()` returns the configured local provider or raises LLMUnavailable."""
from __future__ import annotations

from backend.llm.base import LLMProvider, LLMUnavailable


def get_llm() -> LLMProvider:
    from backend.llm.ollama import OllamaProvider
    from backend.storage.database import get_db

    rs = get_db().runtime_settings()
    if not rs.ollama_model:
        raise LLMUnavailable("Local model unavailable. Please install/configure a supported Ollama model in Settings.")
    return OllamaProvider(
        rs.ollama_host, rs.ollama_model, timeout_s=rs.llm_timeout_s, temperature=rs.llm_temperature,
        allow_remote=bool(rs.extra.get("allow_remote_ollama", False)),
    )


__all__ = ["LLMProvider", "LLMUnavailable", "get_llm"]
