from __future__ import annotations

from llm.regulations import CATALOGUE_SHA256
from llm.retrieval import build_grounded_briefing, retrieve_clauses
from pipeline.rules.engine import evaluate_fake_rules
from shared.enums import RuleId
from shared.schemas.llm import GroundedBriefing


def test_retrieve_clauses_prefers_rule_specific_chunk() -> None:
    hits = retrieve_clauses("worker without helmet needs head protection", rule_id=RuleId.R1)
    assert hits
    assert hits[0].chunk.chunk_id == "bocw-ppe-helmet-r1"
    assert hits[0].score > 0


def test_grounded_briefing_has_citations() -> None:
    _, incidents, _ = evaluate_fake_rules(
        run_id="run-rag",
        shot_id="shot-0",
        catalogue_sha256=CATALOGUE_SHA256,
    )
    briefing = build_grounded_briefing(incidents[0])
    GroundedBriefing.model_validate(briefing.model_dump())
    assert briefing.refused is False
    assert briefing.sentences
    assert all(sentence.citation_ids for sentence in briefing.sentences)
    assert briefing.retrieved_chunks[0].chunk.chunk_id == "bocw-ppe-helmet-r1"
