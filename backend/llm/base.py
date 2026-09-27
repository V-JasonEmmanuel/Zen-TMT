"""LLM provider abstraction. The pipeline never depends on a specific model or vendor."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMUnavailable(Exception):
    """No usable local model. Callers degrade to deterministic (extractive) behaviour."""


class LLMProvider(ABC):
    name: str = ""
    model: str = ""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        json_schema: Optional[dict[str, Any]] = None,
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
    ) -> str: ...

    def unload(self) -> None:
        """Release model memory (VRAM/RAM) when a generation run finishes."""
