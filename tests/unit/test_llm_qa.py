from __future__ import annotations

from llm.qa import answer_run_question
from llm.regulations import CATALOGUE_SHA256
from llm.retrieval import build_grounded_briefing
from pipeline.rules.engine import evaluate_fake_rules
from shared.schemas.llm import RunQuestionAnswer


def _fake_run_payload():
    coverage, incidents, _ = evaluate_fake_rules(
        run_id="run-qa",
        shot_id="shot-0",
        catalogue_sha256=CATALOGUE_SHA256,
    )
    briefings = tuple(build_grounded_briefing(incident) for incident in incidents)
    return coverage, incidents, briefings


def test_answer_run_question_summarizes_rule_alert() -> None:
    coverage, incidents, briefings = _fake_run_payload()
    answer = answer_run_question(
        question="Which helmet alerts were found?",
        coverage=coverage,
        incidents=incidents,
        briefings=briefings,
    )
    RunQuestionAnswer.model_validate(answer.model_dump())
    assert answer.refused is False
    assert "R1 has 1 alert" in answer.answer
    assert answer.cited_incident_ids == (incidents[0].incident_id,)
    assert answer.cited_clause_ids == ("bocw-ppe-helmet-r1",)


def test_answer_run_question_refuses_legal_verdict() -> None:
    coverage, incidents, briefings = _fake_run_payload()
    answer = answer_run_question(
        question="Is this legally compliant?",
        coverage=coverage,
        incidents=incidents,
        briefings=briefings,
    )
    assert answer.refused is True
    assert answer.refusal_reason == "legal_verdict_request"
