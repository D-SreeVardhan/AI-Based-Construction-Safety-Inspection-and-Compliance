from __future__ import annotations

from llm.regulations import BOOTSTRAP_CLAUSES
from llm.retrieval import (
    _mmr_rerank,
    retrieve_clauses,
    retrieve_clauses_dense,
    retrieve_clauses_hybrid,
    retrieve_clauses_lexical,
)
from shared.enums import RuleId
from shared.schemas.llm import RetrievalHit


def _rrf_scaled_hits(count: int) -> list[RetrievalHit]:
    chunks = [c for c in BOOTSTRAP_CLAUSES if RuleId.R1 in c.rule_ids][:count]
    return [
        RetrievalHit(
            chunk=chunk,
            score=1.0 / (60 + rank),
            lexical_score=0.0,
            semantic_hint_score=0.0,
            rank=rank,
        )
        for rank, chunk in enumerate(chunks, start=1)
    ]


def test_mmr_keeps_relevance_order_at_rrf_scale_when_chunks_are_distinct():
    hits = _rrf_scaled_hits(5)
    # Orthogonal embeddings: no redundancy, so MMR must not reorder by diversity alone.
    embeddings = {
        hit.chunk.chunk_id: [1.0 if i == j else 0.0 for j in range(5)] for i, hit in enumerate(hits)
    }
    reranked = _mmr_rerank(hits, top_k=3, embeddings=embeddings)
    assert [h.chunk.chunk_id for h in reranked] == [h.chunk.chunk_id for h in hits[:3]]
    assert [h.rank for h in reranked] == [1, 2, 3]


def test_mmr_demotes_near_duplicate_of_top_hit():
    hits = _rrf_scaled_hits(3)
    top, duplicate, distinct = (h.chunk.chunk_id for h in hits)
    embeddings = {top: [1.0, 0.0], duplicate: [1.0, 0.0], distinct: [0.0, 1.0]}
    reranked = _mmr_rerank(hits, top_k=2, embeddings=embeddings)
    assert [h.chunk.chunk_id for h in reranked] == [top, distinct]


def test_lexical_retrieval_returns_correct_rule():
    hits = retrieve_clauses_lexical("helmet head protection", rule_id=RuleId.R1, top_k=3)
    assert len(hits) >= 1
    assert all(RuleId.R1 in h.chunk.rule_ids for h in hits)
    assert hits[0].rank == 1


def test_lexical_retrieval_no_cross_rule_bleed():
    hits = retrieve_clauses_lexical("helmet head protection", rule_id=RuleId.R5, top_k=3)
    assert all(RuleId.R5 in h.chunk.rule_ids for h in hits)


def test_lexical_retrieval_all_rules_no_filter():
    hits = retrieve_clauses_lexical("worker site safety", rule_id=None, top_k=10)
    rule_ids_found = {r for h in hits for r in h.chunk.rule_ids}
    # cross-cutting chunks should appear; at least 2 rules should be represented
    assert len(rule_ids_found) >= 2


def test_dense_retrieval_skips_missing_embeddings():
    # No embeddings at all — should return empty tuple
    hits = retrieve_clauses_dense(
        [0.0] * 768, rule_id=None, top_k=3, corpus=BOOTSTRAP_CLAUSES, embeddings={}
    )
    assert hits == ()


def test_dense_retrieval_ranks_by_cosine():
    # Build a fake embedding that has a very high cosine sim with the R2 hi-vis chunk
    target = [1.0] * 768
    embeddings = {
        "bocw-ppe-visibility-r2": target,
        "bocw-ppe-helmet-r1": [-1.0] * 768,
    }
    hits = retrieve_clauses_dense(
        target, rule_id=None, top_k=2, corpus=BOOTSTRAP_CLAUSES, embeddings=embeddings
    )
    assert len(hits) >= 1
    assert hits[0].chunk.chunk_id == "bocw-ppe-visibility-r2"


def test_hybrid_falls_back_to_lexical_without_embedding():
    hits = retrieve_clauses_hybrid(
        "missing helmet",
        rule_id=RuleId.R1,
        top_k=3,
        query_embedding=None,
        embeddings=None,
    )
    assert len(hits) >= 1
    assert all(RuleId.R1 in h.chunk.rule_ids for h in hits)


def test_hybrid_with_embeddings_fuses_results():
    # Provide an R2 embedding only; query is R1-related
    # Result should still prefer R1 lexically but include the R2 dense hit if no filter
    target = [1.0] * 768
    embeddings = {"bocw-hiviz-spec-r2": target}
    hits = retrieve_clauses_hybrid(
        "helmet hardhat head protection",
        rule_id=None,
        top_k=5,
        query_embedding=target,
        embeddings=embeddings,
    )
    chunk_ids = [h.chunk.chunk_id for h in hits]
    # RRF should surface the dense-only R2 hit somewhere
    assert "bocw-hiviz-spec-r2" in chunk_ids


def test_backwards_compat_retrieve_clauses():
    # The old retrieve_clauses() alias must still work unchanged
    hits = retrieve_clauses("vest visibility", rule_id=RuleId.R2, top_k=2)
    assert len(hits) >= 1
    assert all(RuleId.R2 in h.chunk.rule_ids for h in hits)


def test_corpus_expanded_to_expected_count():
    # Expanded corpus should have at least 25 clauses
    assert len(BOOTSTRAP_CLAUSES) >= 25


def test_all_chunk_ids_are_unique():
    ids = [c.chunk_id for c in BOOTSTRAP_CLAUSES]
    assert len(ids) == len(set(ids))
