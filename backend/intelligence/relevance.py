"""Relevance ranking: instruction + structure + semantics + keywords + section/content type.

The goal is to *exclude* everything the instruction does not ask for, so the planner
only ever sees relevant, traceable material.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from backend.intelligence.retrieval import VectorIndex
from backend.intelligence.text import stems
from backend.schemas import ContentContract, ContentType, DocumentChunk, SectionType

S = SectionType

# Topic vocabulary used to interpret include / exclude terms from the content contract.
TOPICS: dict[str, dict] = {
    "overview": {"sections": [S.abstract, S.executive_summary, S.introduction], "keywords": "overview summary purpose objective aim goal", "desc": "overview, purpose and objectives"},
    "executive_summary": {"sections": [S.executive_summary, S.abstract, S.conclusion], "keywords": "summary key takeaway overview", "desc": "executive summary and key takeaways"},
    "introduction": {"sections": [S.introduction], "keywords": "introduction motivation objective", "desc": "introduction"},
    "background": {"sections": [S.background, S.introduction, S.related_work], "keywords": "background context problem challenge motivation", "desc": "background, context and the problem being addressed"},
    "problem": {"sections": [S.background, S.introduction], "keywords": "problem challenge issue gap limitation pain", "desc": "the problem statement and challenges"},
    "related_work": {"sections": [S.related_work], "keywords": "prior work literature previous studies", "desc": "related work and literature"},
    "architecture": {"sections": [S.architecture], "keywords": "architecture component layer module system design pipeline framework service interface integration", "desc": "system architecture, components and how they interact"},
    "methodology": {"sections": [S.methodology, S.experiments], "keywords": "method methodology approach procedure dataset data collection training model technique design step process", "desc": "methodology, approach and procedure"},
    "implementation": {"sections": [S.implementation], "keywords": "implementation deploy deployment setup configuration tooling", "desc": "implementation and deployment"},
    "implementation_code": {"sections": [], "content": [ContentType.code], "keywords": "code function class snippet listing", "desc": "source code listings"},
    "experiments": {"sections": [S.experiments], "keywords": "experiment evaluation benchmark setup dataset baseline", "desc": "experimental setup and evaluation"},
    "results": {"sections": [S.results, S.experiments, S.discussion], "keywords": "result accuracy performance improvement outperform increase decrease reduction score metric percent significant finding", "desc": "results, findings, metrics and performance", "tables": True},
    "findings": {"sections": [S.results, S.discussion, S.conclusion], "keywords": "finding result insight observation", "desc": "key findings and insights", "tables": True},
    "discussion": {"sections": [S.discussion], "keywords": "discussion implication interpretation", "desc": "discussion and implications"},
    "limitations": {"sections": [S.discussion], "keywords": "limitation constraint threat weakness caveat", "desc": "limitations and constraints"},
    "conclusion": {"sections": [S.conclusion], "keywords": "conclusion conclude summary", "desc": "conclusions"},
    "recommendations": {"sections": [S.recommendations, S.conclusion], "keywords": "recommend recommendation next step should propose roadmap", "desc": "recommendations and next steps"},
    "future_work": {"sections": [S.recommendations, S.conclusion], "keywords": "future work extension direction", "desc": "future work"},
    "benefits": {"sections": [S.results, S.conclusion, S.executive_summary], "keywords": "benefit value saving advantage roi impact efficiency", "desc": "business benefits and value"},
    "business_impact": {"sections": [S.results, S.executive_summary, S.conclusion], "keywords": "impact business value revenue cost saving customer market roi", "desc": "business impact and value"},
    "costs": {"sections": [], "keywords": "cost budget price expense investment spend", "desc": "costs and budget"},
    "risks": {"sections": [S.discussion], "keywords": "risk mitigation threat issue concern", "desc": "risks and mitigations"},
    "timeline": {"sections": [], "keywords": "timeline phase milestone schedule quarter month week plan roadmap", "desc": "timeline, phases and milestones"},
    "references": {"sections": [S.references], "content": [ContentType.reference], "keywords": "reference citation", "desc": "bibliography"},
    "appendix": {"sections": [S.appendix], "keywords": "appendix", "desc": "appendix material"},
    "math": {"sections": [], "keywords": "equation theorem proof lemma formula derivation", "desc": "mathematical derivations"},
}
ALIASES = {
    "method": "methodology", "methods": "methodology", "approach": "methodology", "result": "results",
    "outcomes": "results", "performance": "results", "metrics": "results", "evaluation": "experiments",
    "code": "implementation_code", "source_code": "implementation_code", "implementation_details": "implementation_code",
    "detailed_implementation_code": "implementation_code", "system_architecture": "architecture", "design": "architecture",
    "conclusions": "conclusion", "summary": "executive_summary", "next_steps": "recommendations",
    "limitation": "limitations", "risk": "risks", "cost": "costs", "roadmap": "timeline", "equations": "math",
    "citations": "references", "bibliography": "references", "literature_review": "related_work", "context": "background",
}
ALWAYS_LOW = {S.references, S.acknowledgements, S.appendix}


def canonical_topic(term: str) -> str:
    t = term.strip().lower().replace(" ", "_")
    return ALIASES.get(t, t)


@dataclass
class ScoredChunk:
    chunk_id: str
    score: float
    semantic: float
    keyword: float
    section: float
    content: float
    topic: str = ""
    excluded: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class RelevanceResult:
    scored: list[ScoredChunk] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    def ranked(self, include_excluded: bool = False) -> list[ScoredChunk]:
        items = [s for s in self.scored if include_excluded or not s.excluded]
        return sorted(items, key=lambda s: -s.score)

    def by_id(self) -> dict[str, ScoredChunk]:
        return {s.chunk_id: s for s in self.scored}


def _topic_query(topic: str) -> str:
    spec = TOPICS.get(topic)
    return f"{topic.replace('_', ' ')}: {spec['desc']}" if spec else topic.replace("_", " ")


def rank_chunks(contract: ContentContract, chunks: list[DocumentChunk], vectors: np.ndarray, embedder) -> RelevanceResult:
    if not chunks:
        return RelevanceResult()
    includes = [canonical_topic(t) for t in contract.include]
    excludes = [canonical_topic(t) for t in contract.exclude]
    topics = includes or ["overview", "results", "conclusion"]

    # ---- semantic similarity: instruction + one query per included topic
    queries = [contract.raw_instruction or f"{contract.purpose} for {contract.audience}"] + [_topic_query(t) for t in topics]
    qv = embedder.encode(queries)
    index = VectorIndex(vectors)
    sim_instr = index.similarities(qv[0])
    topic_sims = np.vstack([index.similarities(q) for q in qv[1:]]) if len(qv) > 1 else sim_instr[None, :]
    best_topic_idx = topic_sims.argmax(0)
    sem_raw = 0.4 * sim_instr + 0.6 * topic_sims.max(0)
    lo, hi = float(np.percentile(sem_raw, 5)), float(sem_raw.max())
    sem = np.clip((sem_raw - lo) / max(hi - lo, 1e-6), 0, 1)

    # ---- keyword overlap with topic vocabularies and the instruction
    kw_terms: set[str] = stems(contract.raw_instruction)
    for t in topics:
        kw_terms |= stems(TOPICS.get(t, {}).get("keywords", t.replace("_", " ")))
    topic_kw = {t: stems(TOPICS.get(t, {}).get("keywords", t.replace("_", " "))) for t in topics}

    result = RelevanceResult(topics=topics)
    for i, ch in enumerate(chunks):
        cs = stems(ch.text + " " + ch.section)
        kw = min(1.0, len(cs & kw_terms) / 6.0)

        # section importance
        stype = ch.section_type
        if any(stype in TOPICS.get(t, {}).get("sections", []) for t in topics):
            sec = 1.0
        elif stype in (S.abstract, S.executive_summary, S.conclusion):
            sec = 0.55
        elif stype in ALWAYS_LOW:
            sec = 0.0
        else:
            sec = 0.3

        # content type
        con = 0.5
        if ch.content_type == ContentType.table and any(TOPICS.get(t, {}).get("tables") for t in topics):
            con = 1.0
        elif ch.content_type in (ContentType.figure,):
            con = 0.6
        elif ch.content_type in (ContentType.code, ContentType.reference):
            con = 0.1
        if len(ch.text) < 60 and ch.content_type == ContentType.paragraph:
            con *= 0.4

        score = 0.45 * float(sem[i]) + 0.20 * kw + 0.25 * sec + 0.10 * con

        # topic assignment: section mapping first; otherwise only on strong keyword + semantic evidence.
        # Unassigned chunks ("") are context: usable for summaries, never for topic slides.
        topic = next((t for t in topics if stype in TOPICS.get(t, {}).get("sections", [])), None)
        if topic is None:  # section heading names a requested topic (e.g. "Costs", "Timeline")
            topic = next((t for t in topics if stems(ch.section) & stems(t.replace("_", " "))), None)
        if topic is None:
            kw_best = max(topics, key=lambda t: len(cs & topic_kw[t]))
            sem_best = topics[int(best_topic_idx[i])] if len(qv) > 1 else topics[0]
            if len(cs & topic_kw[kw_best]) >= 2 and (kw_best == sem_best or sem[i] >= 0.6):
                topic = kw_best
            elif not TOPICS.get(sem_best, {}).get("sections") and sem[i] >= 0.5:
                topic = sem_best  # custom / structure-less topics (e.g. "timeline", "costs")
            else:
                topic = ""
                score *= 0.85

        sc = ScoredChunk(ch.id, round(score, 4), round(float(sem[i]), 4), round(kw, 4), sec, con, topic)

        # ---- exclusions (hard filter)
        heading = stems(ch.section)
        for ex in excludes:
            spec = TOPICS.get(ex, {})
            if ch.content_type in spec.get("content", []) or stype in spec.get("sections", []):
                sc.excluded, sc.reason = True, f"excluded by instruction ({ex})"
                break
            # the section heading names the excluded topic (e.g. a "Risks" section)
            if heading and heading & stems(ex.replace("_", " ")) and ex not in ("implementation_code",):
                sc.excluded, sc.reason = True, f"section '{ch.section}' excluded by instruction ({ex})"
                break
            ex_kw = stems(spec.get("keywords", ex.replace("_", " ")))
            if ex_kw and len(cs & ex_kw) >= 3 and sc.topic not in includes:
                sc.excluded, sc.reason = True, f"matches excluded topic ({ex})"
                break
        if not sc.excluded and stype in ALWAYS_LOW and not any(t in ("references", "appendix") for t in includes):
            sc.excluded, sc.reason = True, f"{stype.value} section not requested"
        if not sc.excluded and ch.content_type == ContentType.code and "implementation_code" not in includes:
            sc.excluded, sc.reason = True, "code listings are not suitable for slides unless requested"
        result.scored.append(sc)
    return result
