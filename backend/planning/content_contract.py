"""Instruction understanding -> ContentContract (the controlling specification).

Deterministic rules always run. When a local LLM is available its interpretation is
merged in, but explicit facts found by the rules (e.g. a stated slide count) win.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.intelligence.relevance import ALIASES, TOPICS, canonical_topic
from backend.llm.base import LLMProvider, LLMUnavailable
from backend.llm.prompts import load_prompt, system_prompt
from backend.llm.structured_output import StructuredOutputError, generate_structured
from backend.schemas import ContentContract
from backend.utils.logging import get_logger

log = get_logger(__name__)

WORD_NUMBERS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
AUDIENCES = [
    ("senior_client", r"senior client|client leadership|client executives?|cxo client"),
    ("executive", r"executive|leadership|board|c-suite|cxo|management|senior management|decision makers?"),
    ("client", r"\bclients?\b|customer"),
    ("technical", r"technical audience|engineers?|developers?|architects?|technical team|data scientists?"),
    ("academic", r"academic|researchers?|conference|scholars?|professors?"),
    ("students", r"students?|learners?|trainees?|classroom"),
    ("sales", r"sales|prospects?|pre-?sales"),
    ("internal_team", r"internal team|our team|colleagues|staff|employees"),
]
PURPOSES = [
    ("technical_presentation", r"technical (presentation|deck|overview|talk)"),
    ("executive_briefing", r"executive (summary|briefing|overview)|briefing"),
    ("research_summary", r"research (summary|presentation|paper)|academic presentation|paper summary"),
    ("client_proposal", r"proposal|pitch"),
    ("training", r"training|tutorial|workshop|onboarding"),
    ("status_update", r"status update|progress report|quarterly|qbr"),
]
TONES = [("formal", r"\bformal\b"), ("persuasive", r"persuasive|convincing|sell"), ("academic", r"academic tone|scholarly"),
         ("conversational", r"conversational|casual|friendly|informal"), ("professional", r"professional")]
NEGATION = re.compile(
    r"(?:do not|don't|dont|never|no need to|avoid|exclude|excluding|without|skip|leave out|omit|not include|no)\s+"
    r"(?:include|including|show|showing|cover|covering|mention|use|using|add|adding|any)?\s*([^.;]+)", re.I)
FOCUS = re.compile(
    r"(?:focus(?:ing|ed)? (?:on|upon)|emphasi[sz](?:e|ing) (?:on )?|highlight(?:ing)?|cover(?:ing)?|include|including|"
    r"covering|about|concentrat(?:e|ing) on|with (?:a )?focus on)\s+([^.;]+)", re.I)


class LLMContract(BaseModel):
    audience: str = ""
    purpose: str = ""
    slide_count: Optional[int] = None
    tone: str = ""
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    detail_level: Literal["low", "medium", "high"] = "medium"
    notes: str = ""


def _phrase_topics(phrase: str) -> list[str]:
    """Map a free-text phrase ('methodology, results and architecture') to topic keys."""
    phrase = phrase.lower()
    phrase = re.split(r"\b(for|to|in|using|so that|because|with the|use the|audience)\b", phrase)[0]
    found: list[str] = []
    parts = re.split(r",|\band\b|\bor\b|/|&", phrase)
    for part in parts:
        p = part.strip(" .:-'\"").removeprefix("the ").removeprefix("its ").strip()
        if not p:
            continue
        hit = None
        if "code" in p:
            hit = "implementation_code"
        else:
            words = re.findall(r"[a-z]+", p)
            joined = "_".join(words)
            for cand in (joined, *(words[::-1])):
                c = canonical_topic(cand)
                if c in TOPICS:
                    hit = c
                    break
                for alias, target in ALIASES.items():
                    if cand == alias:
                        hit = target
                        break
                if hit:
                    break
            if hit is None and 0 < len(words) <= 3 and not set(words) <= {"a", "an", "the", "detailed", "slides", "slide", "presentation"}:
                hit = "_".join(w for w in words if w not in ("detailed", "the", "a", "an"))
        if hit and hit not in found:
            found.append(hit)
    return found


def parse_instruction_rules(instruction: str) -> ContentContract:
    text = " ".join(instruction.split())
    low = text.lower()
    c = ContentContract(raw_instruction=text, parse_method="rules")

    m = re.search(r"\b(\d{1,2})\s*[- ]?\s*(?:slides?|pages?)\b", low) or re.search(
        r"\b(" + "|".join(WORD_NUMBERS) + r")[- ](?:slides?|pages?)\b", low)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_NUMBERS[m.group(1)]
        c.slide_count = max(1, min(40, n))

    for key, pat in AUDIENCES:
        if re.search(pat, low):
            c.audience = key
            break
    for key, pat in PURPOSES:
        if re.search(pat, low):
            c.purpose = key
            break
    for key, pat in TONES:
        if re.search(pat, low):
            c.tone = key
            break
    if re.search(r"high[- ]level|brief|concise|short|overview", low):
        c.detail_level = "low"
    if re.search(r"(?<!no )(?<!not )\b(detailed|in-depth|deep dive|comprehensive)\b", low) and not re.search(
            r"(not|no|without|avoid)\s+(any\s+)?(detailed|in-depth)", low):
        c.detail_level = "high"

    excludes: list[str] = []
    neg_spans = []
    for m in NEGATION.finditer(text):
        neg_spans.append(m.span())
        excludes += _phrase_topics(m.group(1))
    includes: list[str] = []
    for m in FOCUS.finditer(text):
        if any(a <= m.start() < b for a, b in neg_spans):
            continue
        includes += _phrase_topics(m.group(1))
    # topic words mentioned anywhere outside negations also count as includes
    clean = text
    for a, b in sorted(neg_spans, reverse=True):
        clean = clean[:a] + " " + clean[b:]
    for key in ("architecture", "methodology", "results", "benefits", "recommendations", "timeline", "risks",
                "limitations", "background", "findings", "conclusion", "costs", "business_impact", "workflow", "implementation",
                "overview"):
        pat = key.replace("_", " ")
        if re.search(rf"\b{pat}", clean.lower()) or any(
                re.search(rf"\b{a.replace('_', ' ')}\b", clean.lower()) for a, t in ALIASES.items() if t == key and len(a) > 5):
            includes.append(key)
    if re.search(r"\b(apis?|endpoints?)\b", clean.lower()):
        includes.append("implementation")

    def _pos(topic: str) -> int:  # keep the order in which the user listed the topics
        words = [topic.replace("_", " ")] + [a.replace("_", " ") for a, t in ALIASES.items() if t == topic]
        words += ["api", "stack"] if topic == "implementation" else []
        hits = [m.start() for w in words for m in [re.search(rf"\b{re.escape(w)}", clean.lower())] if m]
        return min(hits) if hits else 10 ** 6

    c.include = sorted([t for t in dict.fromkeys(includes) if t not in excludes], key=_pos)
    c.exclude = list(dict.fromkeys(excludes))

    formats = []
    if re.search(r"\bvideo|mp4|explainer", low):
        formats.append("mp4")
    if re.search(r"\bimages?|infographics?|visuals?|png", low):
        formats.append("png")
    if formats:
        c.output_formats = ["pptx", *formats]
    return c


def parse_instruction(instruction: str, llm: Optional[LLMProvider] = None, sections: list[str] | None = None,
                      defaults: dict | None = None) -> ContentContract:
    rules = parse_instruction_rules(instruction)
    stated_count = bool(re.search(r"\d{1,2}\s*[- ]?\s*(slides?|pages?)|(" + "|".join(WORD_NUMBERS) + r")[- ](slides?|pages?)",
                                  instruction.lower()))
    contract = rules
    if llm is not None:
        try:
            p = load_prompt("instruction_parser").render(instruction=instruction, sections=", ".join(sections or []) or "unknown")
            got = generate_structured(llm, p, LLMContract, system=system_prompt(), retries=1, max_tokens=400)
            merged = rules.model_dump()
            if rules.audience == "general_business" and got.audience:
                merged["audience"] = got.audience.strip().lower().replace(" ", "_")
            if rules.purpose == "presentation" and got.purpose:
                merged["purpose"] = got.purpose.strip().lower().replace(" ", "_")
            if rules.tone == "professional" and got.tone:
                merged["tone"] = got.tone.strip().lower()
            if not stated_count and got.slide_count and 1 <= got.slide_count <= 40:
                merged["slide_count"] = got.slide_count
            llm_ex = [canonical_topic(x) for x in got.exclude]
            # keep model-proposed topics only if they add something (not "operations_results" next to "results")
            llm_in = [t for t in (canonical_topic(x) for x in got.include)
                      if t and not any(r in t.split("_") or t in r.split("_") for r in rules.include if r != t)]
            merged["exclude"] = list(dict.fromkeys(rules.exclude + llm_ex))
            merged["include"] = [t for t in dict.fromkeys(rules.include + llm_in) if t not in merged["exclude"]]
            if merged["detail_level"] == "medium":
                merged["detail_level"] = got.detail_level
            merged["notes"] = got.notes[:300]
            merged["parse_method"] = "rules+llm"
            contract = ContentContract(**merged)
        except (LLMUnavailable, StructuredOutputError, KeyError) as exc:
            log.warning("LLM instruction parsing unavailable; using rules", reason=type(exc).__name__)
    if defaults:
        data = contract.model_dump()
        data.update({k: v for k, v in defaults.items() if v is not None})
        contract = ContentContract(**data)
    log.info("Content contract generated", slides=contract.slide_count, include=len(contract.include),
             exclude=len(contract.exclude), method=contract.parse_method)
    return contract
