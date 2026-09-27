"""Never trust raw LLM JSON: extract -> validate (Pydantic) -> repair/retry -> validated object."""
from __future__ import annotations

import json
import re
from typing import Optional, TypeVar

from pydantic import BaseModel, ValidationError

from backend.llm.base import LLMProvider
from backend.utils.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    pass


def extract_json(text: str) -> Optional[str]:
    """Return the first balanced JSON object in `text` (handles ```json fences and chatter)."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def _loads_lenient(s: str) -> object:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        s2 = re.sub(r",\s*([}\]])", r"\1", s)  # trailing commas
        return json.loads(s2)


def parse_model(text: str, model: type[T]) -> T:
    raw = extract_json(text)
    if raw is None:
        raise StructuredOutputError("no JSON object found in the response")
    try:
        return model.model_validate(_loads_lenient(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise StructuredOutputError(_short_error(exc)) from exc


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
    return str(exc)[:300]


def generate_structured(llm: LLMProvider, prompt: str, model: type[T], *, system: str = "",
                        retries: int = 2, max_tokens: int = 1200) -> T:
    schema = model.model_json_schema()
    last_error, last_output = "", ""
    for attempt in range(retries + 1):
        p = prompt
        if attempt:
            p = (f"{prompt}\n\nYour previous answer was invalid ({last_error}). "
                 f"Return ONLY a corrected JSON object that matches the schema. Previous answer:\n{last_output[:1500]}")
        out = llm.generate(p, system=system, json_schema=schema, max_tokens=max_tokens)
        try:
            return parse_model(out, model)
        except StructuredOutputError as exc:
            last_error, last_output = str(exc), out
            log.warning("LLM output failed validation", schema=model.__name__, attempt=attempt + 1)
    raise StructuredOutputError(f"{model.__name__}: {last_error}")
