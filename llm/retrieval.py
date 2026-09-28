from __future__ import annotations

import math
import re
from collections import Counter

from llm.regulations import BOOTSTRAP_CLAUSES
from shared.enums import RuleId
from shared.schemas.incidents import IncidentRecord
from shared.schemas.llm import CitedSentence, ClauseChunk, GroundedBriefing, RetrievalHit

TOKEN_RE = re.compile(r"[a-z0-9]+")
MODEL_ID = "deterministic-grounded-briefing-v1"
RETRIEVAL_MODE = "local-bm25-alias-bootstrap"
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "near",
    "of",
    "or",
    "so",
    "that",
    "the",
    "to",
    "where",
    "with",
}
SEMANTIC_HINTS: dict[RuleId, tuple[str, ...]] = {
    RuleId.R1: ("helmet", "head", "ppe", "protection", "impact"),
    RuleId.R2: ("vest", "visibility", "conspicuous", "traffic", "plant"),
    RuleId.R3: ("restricted", "zone", "barrier", "access", "authorised"),
    RuleId.R4: ("machinery", "plant", "separation", "danger", "movement"),
    RuleId.R5: ("edge", "fall", "height", "guardrail", "net"),
}


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS)


def _bm25_like(query_tokens: tuple[str, ...], document_tokens: tuple[str, ...]) -> float:
    if not query_tokens or not document_tokens:
        return 0.0
    query_counts = Counter(query_tokens)
    doc_counts = Counter(document_tokens)
    length_norm = 1.0 + math.log1p(len(document_tokens))
    return sum(min(count, doc_counts[token]) for token, count in query_counts.items()) / length_norm


def _semantic_hint_score(rule_id: RuleId | None, document_tokens: tuple[str, ...]) -> float:
    if rule_id is None:
        return 0.0
    hints = set(SEMANTIC_HINTS[rule_id])
    matched = len(hints.intersection(document_tokens))
    return matched / max(1, len(hints))


def _document_text(chunk: ClauseChunk) -> str:
    return f"{chunk.clause_ref} {chunk.title} {chunk.text}"


def build_incident_query(incident: IncidentRecord) -> str:
    parts = [
        incident.rule_id.value,
        incident.reason_code,
        incident.basis,
        incident.severity,
        incident.observation_text,
        incident.action_text,
        " ".join(incident.references),
    ]
    return " ".join(part for part in parts if part)


def retrieve_clauses(
    query: str,
    *,
    rule_id: RuleId | None = None,
    top_k: int = 3,
    corpus: tuple[ClauseChunk, ...] = BOOTSTRAP_CLAUSES,
) -> tuple[RetrievalHit, ...]:
    query_tokens = _tokens(query)
    scored: list[tuple[float, float, float, ClauseChunk]] = []
    for chunk in corpus:
        if rule_id is not None and rule_id not in chunk.rule_ids:
            continue
        document_tokens = _tokens(_document_text(chunk))
        lexical_score = _bm25_like(query_tokens, document_tokens)
        semantic_hint_score = _semantic_hint_score(rule_id, document_tokens)
        score = lexical_score + semantic_hint_score
        if score > 0.0:
            scored.append((score, lexical_score, semantic_hint_score, chunk))

    scored.sort(key=lambda item: (-item[0], item[3].chunk_id))
    return tuple(
        RetrievalHit(
            chunk=chunk,
            score=score,
            lexical_score=lexical_score,
            semantic_hint_score=semantic_hint_score,
            rank=index + 1,
        )
        for index, (score, lexical_score, semantic_hint_score, chunk) in enumerate(scored[:top_k])
    )


def _allowed_tokens(incident: IncidentRecord, hits: tuple[RetrievalHit, ...]) -> set[str]:
    evidence = [
        incident.incident_id,
        incident.rule_id.value,
        incident.status.value,
        incident.reason_code,
        incident.basis,
        incident.severity,
        incident.canonical_track_id or "",
        incident.observation_text,
        incident.action_code,
        incident.action_text,
        " ".join(incident.references),
    ]
    evidence.extend(_document_text(hit.chunk) for hit in hits)
    return set(_tokens(" ".join(evidence)))


def _is_grounded(sentence: CitedSentence, allowed_tokens: set[str]) -> bool:
    sentence_tokens = set(_tokens(sentence.text))
    if not sentence_tokens:
        return False
    return len(sentence_tokens.intersection(allowed_tokens)) >= 2


def build_grounded_briefing(incident: IncidentRecord) -> GroundedBriefing:
    hits = retrieve_clauses(build_incident_query(incident), rule_id=incident.rule_id, top_k=2)
    if not hits:
        return GroundedBriefing(
            incident_id=incident.incident_id,
            rule_id=incident.rule_id,
            mode="deterministic-refusal",
            model_id=MODEL_ID,
            retrieval_mode=RETRIEVAL_MODE,
            sentences=(
                CitedSentence(
                    text=incident.observation_text,
                    citation_ids=(),
                ),
            ),
            retrieved_chunks=(),
            refused=True,
            refusal_reason="no_retrieved_clause",
        )

    primary = hits[0].chunk
    sentences = (
        CitedSentence(
            text=(
                f"{incident.rule_id.value} {incident.status.value}: "
                f"{incident.observation_text}"
            ),
            citation_ids=(primary.chunk_id,),
        ),
        CitedSentence(
            text=f"Relevant clause: {primary.text}",
            citation_ids=(primary.chunk_id,),
        ),
        CitedSentence(
            text=(
                f"Corrective action: {incident.action_text} "
                f"Check the site controls against {primary.title.lower()}."
            ),
            citation_ids=(primary.chunk_id,),
        ),
    )
    allowed_tokens = _allowed_tokens(incident, hits)
    ungrounded = [
        sentence.text for sentence in sentences if not _is_grounded(sentence, allowed_tokens)
    ]
    if ungrounded:
        return GroundedBriefing(
            incident_id=incident.incident_id,
            rule_id=incident.rule_id,
            mode="deterministic-refusal",
            model_id=MODEL_ID,
            retrieval_mode=RETRIEVAL_MODE,
            sentences=(CitedSentence(text=incident.observation_text, citation_ids=()),),
            retrieved_chunks=hits,
            refused=True,
            refusal_reason="ungrounded_sentence",
        )

    return GroundedBriefing(
        incident_id=incident.incident_id,
        rule_id=incident.rule_id,
        mode="deterministic-template",
        model_id=MODEL_ID,
        retrieval_mode=RETRIEVAL_MODE,
        sentences=sentences,
        retrieved_chunks=hits,
    )
