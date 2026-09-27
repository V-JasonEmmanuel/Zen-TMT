"""Privacy-safe image search queries.

Queries are assembled ONLY from a fixed, generic vocabulary (industry, visual intent, audience,
style). No document text, names, numbers or phrases are ever copied into a query, so nothing
confidential can leave the machine even when web image search is enabled.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional

from backend.schemas import Slide

INDUSTRIES: dict[str, tuple[str, ...]] = {
    "banking": ("bank", "banking", "loan", "credit", "deposit", "payments", "fintech", "lending"),
    "insurance": ("insurance", "insurer", "claims", "policyholder", "underwriting", "actuarial"),
    "healthcare": ("health", "healthcare", "patient", "clinical", "hospital", "medical", "pharma"),
    "retail": ("retail", "store", "shopper", "ecommerce", "merchandise", "consumer"),
    "manufacturing": ("manufacturing", "factory", "plant", "production", "supply chain", "industrial"),
    "telecom": ("telecom", "network operator", "5g", "subscriber", "mobile network"),
    "energy": ("energy", "utility", "grid", "power", "renewable", "oil"),
    "public sector": ("government", "public sector", "citizen", "municipal"),
    "education": ("education", "student", "university", "learning"),
    "cloud": ("cloud", "aws", "azure", "kubernetes", "infrastructure"),
    "artificial intelligence": ("ai", "artificial intelligence", "machine learning", "model", "llm", "neural"),
    "data analytics": ("data", "analytics", "dashboard", "retrieval", "database", "warehouse"),
    "cybersecurity": ("security", "cyber", "threat", "compliance", "risk"),
}
INTENTS = {
    "cover": "enterprise technology", "executive_summary": "business leadership", "architecture": "technology infrastructure",
    "workflow": "digital workflow", "process": "business process", "research_methodology": "research team laboratory",
    "research_results": "data analytics", "kpi": "business performance", "chart": "data analytics",
    "key_findings": "business insights meeting", "conclusion": "strategy team", "timeline": "project planning",
    "comparison": "business decision", "text_image": "technology team", "image_text": "technology team",
    "two_column": "technology team", "three_column": "business team",
}
TOPIC_INTENTS = {
    "results": "data analytics", "methodology": "research process", "architecture": "technology infrastructure",
    "recommendations": "strategy planning", "background": "business challenge", "benefits": "business growth",
    "risks": "risk management", "costs": "finance planning", "timeline": "project planning",
}
AUDIENCE = {"executive": "executive", "senior_client": "business", "client": "business", "technical": "engineering",
            "academic": "research", "students": "learning", "sales": "business"}
ALLOWED = set(" ".join(list(INTENTS.values()) + list(TOPIC_INTENTS.values()) + list(AUDIENCE.values()) +
                       list(INDUSTRIES) + ["professional", "modern", "office", "people", "abstract", "technology"]).split())


def detect_industry(texts: Iterable[str]) -> Optional[str]:
    """Most prominent industry keyword family in the document (computed locally)."""
    c: Counter[str] = Counter()
    for t in texts:
        low = t.lower()
        for name, kws in INDUSTRIES.items():
            c[name] += sum(len(re.findall(rf"\b{re.escape(k)}\b", low)) for k in kws)
    best = c.most_common(1)
    return best[0][0] if best and best[0][1] >= 3 else None


def build_query(slide: Slide, audience: str = "", industry: Optional[str] = None, style: str = "professional") -> str:
    intent = TOPIC_INTENTS.get(slide.topic) or INTENTS.get(slide.layout, "technology team")
    parts = [industry or "", intent, AUDIENCE.get(audience, ""), style]
    words: list[str] = []
    for w in " ".join(p for p in parts if p).split():
        if w in ALLOWED and w not in words:
            words.append(w)
    return " ".join(words[:6])


def is_safe_query(q: str) -> bool:
    """Guard used before any network call: only generic vocabulary is permitted."""
    return bool(q.strip()) and all(w in ALLOWED for w in q.lower().split())
