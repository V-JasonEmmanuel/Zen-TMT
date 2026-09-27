"""Ollama provider (local HTTP API). Refuses non-local hosts unless explicitly allowed."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from backend.llm.base import LLMProvider, LLMUnavailable
from backend.utils.logging import get_logger

log = get_logger(__name__)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def is_local_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, host: str, model: str, timeout_s: int = 240, temperature: float = 0.2,
                 num_ctx: int = 6144, allow_remote: bool = False):
        # 'localhost' makes Windows try IPv6 first (~2-3 s per request when Ollama listens on IPv4 only)
        self.host = re.sub(r"//localhost(?=[:/]|$)", "//127.0.0.1", host.rstrip("/"))
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.num_ctx = num_ctx
        if not allow_remote and not is_local_host(self.host):
            raise LLMUnavailable(
                "The configured Ollama host is not on this machine. Documents must stay local, "
                "so only localhost Ollama servers are permitted."
            )

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=3)
            if r.status_code != 200:
                return False
            if not self.model:
                return False
            names = {m.get("name", "") for m in r.json().get("models", [])}
            return self.model in names or f"{self.model}:latest" in names
        except httpx.HTTPError:
            return False

    def server_running(self) -> bool:
        try:
            return httpx.get(f"{self.host}/api/tags", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable("Ollama is not running. Start Ollama and try again.") from exc
        out = []
        for m in r.json().get("models", []):
            d = m.get("details", {}) or {}
            out.append({
                "name": m.get("name"), "size_gb": round((m.get("size") or 0) / 1e9, 2),
                "parameters": d.get("parameter_size", ""), "quantization": d.get("quantization_level", ""),
                "family": d.get("family", ""),
            })
        return out

    def generate(self, prompt: str, *, system: str = "", json_schema: Optional[dict[str, Any]] = None,
                 max_tokens: int = 1024, temperature: Optional[float] = None) -> str:
        if not self.model:
            raise LLMUnavailable("No local model is selected. Choose an installed Ollama model in Settings.")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        if json_schema is not None:
            body["format"] = json_schema
        try:
            r = httpx.post(f"{self.host}/api/chat", json=body, timeout=self.timeout_s)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"The local model did not respond within {self.timeout_s}s.") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable("Ollama is not reachable. Start Ollama and try again.") from exc
        if r.status_code == 404:
            raise LLMUnavailable(f"Model '{self.model}' is not installed in Ollama.")
        if r.status_code != 200:
            raise LLMUnavailable(f"Ollama returned HTTP {r.status_code}.")
        data = r.json()
        log.debug("LLM call complete", model=self.model, eval_count=data.get("eval_count"),
                  seconds=round((data.get("total_duration") or 0) / 1e9, 1))
        return (data.get("message") or {}).get("content", "")

    def unload(self) -> None:
        if not self.model:
            return
        try:
            httpx.post(f"{self.host}/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=10)
            log.info("LLM unloaded", model=self.model)
        except httpx.HTTPError:
            pass
