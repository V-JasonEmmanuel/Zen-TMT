"""Structured logging.

Usage:  log = get_logger(__name__); log.info("Document uploaded", pages=42)

Policy: log identifiers, counts and timings only - never document text, extracted
content, prompts or LLM responses (documents are confidential enterprise material).
"""
from __future__ import annotations

import logging
import sys
from typing import Any

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", "%H:%M:%S"))
    root = logging.getLogger("zcs")
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _CONFIGURED = True


def _fmt(value: Any) -> str:
    s = str(value)
    if len(s) > 120:  # guard against accidentally logging content
        s = s[:40] + "...<truncated>"
    return f'"{s}"' if " " in s else s


class StructuredLogger:
    def __init__(self, name: str):
        short = name.replace("backend.", "")
        self._log = logging.getLogger(f"zcs.{short}")

    def _emit(self, level: int, event: str, fields: dict[str, Any]) -> None:
        if fields:
            event = event + "  " + " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        self._log.log(level, event)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, fields)

    def exception(self, event: str, **fields: Any) -> None:
        if fields:
            event = event + "  " + " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        self._log.exception(event)


def get_logger(name: str) -> StructuredLogger:
    configure_logging()
    return StructuredLogger(name)
