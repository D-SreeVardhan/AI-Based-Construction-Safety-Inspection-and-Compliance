from __future__ import annotations

import math
import re
from collections import Counter

from llm.embeddings import cosine_similarity, rrf_fuse
from llm.regulations import BOOTSTRAP_CLAUSES
from shared.enums import RuleId
from shared.schemas.incidents import IncidentRecord
from shared.schemas.llm import CitedSentence, ClauseChunk, GroundedBriefing, RetrievalHit

TOKEN_RE = re.compile(r"[a-z0-9]+")
MODEL_ID = "deterministic-grounded-briefing-v1"
RETRIEVAL_MODE = "hybrid-bm25-dense-rrf-mmr-v1"

# MMR trade-off: 0 = pure diversity, 1 = pure relevance
MMR_LAMBDA = 0.6
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
    RuleId.R1: ("helmet", "head", "ppe", "protection", "impact", "hardhat"),
    RuleId.R2: ("vest", "visibility", "conspicuous", "traffic", "plant", "hiviz", "fluorescent"),
    RuleId.R3: ("restricted", "zone", "barrier", "access", "authorised", "permit"),
    RuleId.R4: ("machinery", "plant", "separation", "danger", "movement", "excavator", "crane"),
    RuleId.R5: ("edge", "fall", "height", "guardrail", "net", "harness", "scaffold"),
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


def _bigrams(tokens: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    if len(tokens) < 2:
        return frozenset()
    return frozenset(zip(tokens, tokens[1:], strict=False))


def _lexical_similarity(a: ClauseChunk, b: ClauseChunk) -> float:
    """Bigram Jaccard similarity between two clause texts (lexical proxy for MMR)."""
    ta = _bigrams(_tokens(_document_text(a)))
    tb = _bigrams(_tokens(_document_text(b)))
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union if union else 0.0


def _mmr_rerank(
    candidates: list[RetrievalHit],
    *,
    top_k: int,
    embeddings: dict[str, list[float]] | None = None,
    mmr_lambda: float = MMR_LAMBDA,
) -> list[RetrievalHit]:
    """Maximal Marginal Relevance re-ranking to diversify retrieval results.

    Uses dense cosine similarity when embeddings are available; falls back to
    lexical bigram Jaccard similarity otherwise.
    Modifies rank numbers in-place on the returned hits.
    """
    if not candidates or top_k <= 0:
        return candidates[:top_k]

    remaining = list(candidates)
    selected: list[RetrievalHit] = []

    while remaining and len(selected) < top_k:
        best_idx = -1
        best_score = float("-inf")

        for idx, hit in enumerate(remaining):
            relevance = hit.score

            if not selected:
                mmr_score = relevance
            else:
                # Max similarity to any already-selected chunk
                max_sim = 0.0
                for sel in selected:
                    hit_vec = embeddings.get(hit.chunk.chunk_id) if embeddings else None
                    sel_vec = embeddings.get(sel.chunk.chunk_id) if embeddings else None
                    if hit_vec is not None and sel_vec is not None:
                        sim = cosine_similarity(hit_vec, sel_vec)
                    else:
                        sim = _lexical_similarity(hit.chunk, sel.chunk)
                    max_sim = max(max_sim, sim)

                mmr_score = mmr_lambda * relevance - (1.0 - mmr_lambda) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        if best_idx < 0:
            break

        winner = remaining.pop(best_idx)
        selected.append(winner)

    # Re-number ranks
    return [
        RetrievalHit(
            chunk=h.chunk,
            score=h.score,
            lexical_score=h.lexical_score,
            semantic_hint_score=h.semantic_hint_score,
            rank=i + 1,
        )
        for i, h in enumerate(selected)
    ]


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


def retrieve_clauses_lexical(
    query: str,
    *,
    rule_id: RuleId | None = None,
    top_k: int = 5,
    corpus: tuple[ClauseChunk, ...] = BOOTSTRAP_CLAUSES,
) -> tuple[RetrievalHit, ...]:
    """BM25-style lexical retrieval over the local clause corpus.

    Returns up to *top_k* hits sorted by descending score.
    """
    query_tokens = _tokens(query)
    scored: list[tuple[float, float, float, ClauseChunk]] = []
    for chunk in corpus:
        if rule_id is not None and rule_id not in chunk.rule_ids:
            continue
        document_tokens = _tokens(_document_text(chunk))
        lexical_score = _bm25_like(query_tokens, document_tokens)
        hint_score = _semantic_hint_score(rule_id, document_tokens)
        score = lexical_score + hint_score
        if score > 0.0:
            scored.append((score, lexical_score, hint_score, chunk))

    scored.sort(key=lambda item: (-item[0], item[3].chunk_id))
    return tuple(
        RetrievalHit(
            chunk=chunk,
            score=score,
            lexical_score=lexical_score,
            semantic_hint_score=hint_score,
            rank=index + 1,
        )
        for index, (score, lexical_score, hint_score, chunk) in enumerate(scored[:top_k])
    )


def retrieve_clauses_dense(
    query_embedding: list[float],
    *,
    rule_id: RuleId | None = None,
    top_k: int = 5,
    corpus: tuple[ClauseChunk, ...] = BOOTSTRAP_CLAUSES,
    embeddings: dict[str, list[float]] | None = None,
) -> tuple[RetrievalHit, ...]:
    """Cosine-similarity dense retrieval over pre-computed chunk embeddings.

    *embeddings* maps chunk_id → embedding vector. Chunks with no embedding
    entry are silently skipped (they fall through to lexical retrieval).
    """
    if not embeddings:
        return ()
    scored: list[tuple[float, ClauseChunk]] = []
    for chunk in corpus:
        if rule_id is not None and rule_id not in chunk.rule_ids:
            continue
        vec = embeddings.get(chunk.chunk_id)
        if vec is None:
            continue
        sim = cosine_similarity(query_embedding, vec)
        if sim > 0.0:
            scored.append((sim, chunk))

    scored.sort(key=lambda x: (-x[0], x[1].chunk_id))
    return tuple(
        RetrievalHit(
            chunk=chunk,
            score=sim,
            lexical_score=0.0,
            semantic_hint_score=sim,
            rank=index + 1,
        )
        for index, (sim, chunk) in enumerate(scored[:top_k])
    )


def retrieve_clauses_hybrid(
    query: str,
    *,
    rule_id: RuleId | None = None,
    top_k: int = 3,
    corpus: tuple[ClauseChunk, ...] = BOOTSTRAP_CLAUSES,
    query_embedding: list[float] | None = None,
    embeddings: dict[str, list[float]] | None = None,
    rrf_k: int = 60,
) -> tuple[RetrievalHit, ...]:
    """Hybrid BM25 + dense retrieval fused via Reciprocal Rank Fusion.

    When *query_embedding* / *embeddings* are absent, falls back to lexical-only.
    The returned ``RetrievalHit.score`` is the RRF score (or the lexical score
    in fallback mode).
    """
    lex_hits = retrieve_clauses_lexical(query, rule_id=rule_id, top_k=top_k * 2, corpus=corpus)

    if query_embedding and embeddings:
        dense_hits = retrieve_clauses_dense(
            query_embedding,
            rule_id=rule_id,
            top_k=top_k * 2,
            corpus=corpus,
            embeddings=embeddings,
        )
        lex_ranked = [h.chunk.chunk_id for h in lex_hits]
        dense_ranked = [h.chunk.chunk_id for h in dense_hits]
        fused = rrf_fuse([lex_ranked, dense_ranked], k=rrf_k)
        chunk_by_id = {c.chunk_id: c for c in corpus}
        results: list[RetrievalHit] = []
        for rank, (chunk_id, rrf_score) in enumerate(fused[:top_k], start=1):
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            # Look up individual scores for transparency
            lex_score = next(
                (h.lexical_score for h in lex_hits if h.chunk.chunk_id == chunk_id), 0.0
            )
            dense_score = next(
                (h.semantic_hint_score for h in dense_hits if h.chunk.chunk_id == chunk_id), 0.0
            )
            results.append(
                RetrievalHit(
                    chunk=chunk,
                    score=rrf_score,
                    lexical_score=lex_score,
                    semantic_hint_score=dense_score,
                    rank=rank,
                )
            )
        return tuple(_mmr_rerank(results, top_k=top_k, embeddings=embeddings))

    return tuple(_mmr_rerank(list(lex_hits[: top_k * 2]), top_k=top_k, embeddings=embeddings))


# Backwards-compatible alias used by FakePipelineJob and cloud handlers
def retrieve_clauses(
    query: str,
    *,
    rule_id: RuleId | None = None,
    top_k: int = 3,
    corpus: tuple[ClauseChunk, ...] = BOOTSTRAP_CLAUSES,
) -> tuple[RetrievalHit, ...]:
    return retrieve_clauses_hybrid(query, rule_id=rule_id, top_k=top_k, corpus=corpus)


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
    hits = retrieve_clauses(build_incident_query(incident), rule_id=incident.rule_id, top_k=3)
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
            text=(f"{incident.rule_id.value} {incident.status.value}: {incident.observation_text}"),
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
