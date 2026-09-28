from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from llm.qa import answer_run_question
from shared.enums import RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.run import RuleCoverageEntry


def _coverage() -> tuple[RuleCoverageEntry, ...]:
    return (
        RuleCoverageEntry(
            rule_id=RuleId.R1,
            status=RuleStatus.EVALUATED_ALERT,
            reason_code="detected_missing_helmet",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R2,
            status=RuleStatus.EVALUATED_CLEAR,
            reason_code="no_vest_alerts_near_vehicle",
        ),
    )


def _incident() -> IncidentRecord:
    return IncidentRecord(
        incident_id="test-run-person-1-R1-1.0-3.0",
        run_id="test-run",
        shot_id="s0",
        catalogue_sha256="abc",
        rule_id=RuleId.R1,
        status=RuleStatus.EVALUATED_ALERT,
        reason_code="detected_missing_helmet",
        basis="heuristic",
        severity="medium",
        canonical_track_id="s0/person-1",
        proposal_ids=(),
        first_seen_s=1.0,
        confirmed_at_s=2.5,
        resolved_at_s=3.0,
        confidence=0.88,
        observation_text="s0/person-1 detected without helmet from 1.0s to 3.0s.",
        action_code="review_ppe",
        action_text="Verify worker is wearing a hardhat.",
        references=(),
        evidence_path="evidence/test.jpg",
        source_frame_index=15,
    )


def test_empty_question_refused():
    result = answer_run_question(
        question="",
        coverage=_coverage(),
        incidents=(_incident(),),
        briefings=(),
    )
    assert result.refused is True
    assert result.refusal_reason == "empty_question"


def test_legal_verdict_refused():
    result = answer_run_question(
        question="Is this legal?",
        coverage=_coverage(),
        incidents=(_incident(),),
        briefings=(),
    )
    assert result.refused is True
    assert result.refusal_reason == "legal_verdict_request"


def test_deterministic_r1_alert_answer():
    result = answer_run_question(
        question="How many helmet violations?",
        coverage=_coverage(),
        incidents=(_incident(),),
        briefings=(),
        gemini_api_key=None,
    )
    assert result.refused is False
    assert "R1" in result.answer
    assert "1 alert" in result.answer


def test_deterministic_no_incident_clear_coverage():
    clear_cov = (
        RuleCoverageEntry(
            rule_id=RuleId.R1,
            status=RuleStatus.EVALUATED_CLEAR,
            reason_code="no_helmet_alerts_detected",
        ),
    )
    result = answer_run_question(
        question="Any helmet issues?",
        coverage=clear_cov,
        incidents=(),
        briefings=(),
        gemini_api_key=None,
    )
    assert "no alert" in result.answer.lower()
    assert "evaluated_clear" in result.answer.lower()


def test_gemini_qa_path_called_when_key_present():
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "Worker lacked helmet protection."}]}}]}
    ).encode()

    with (
        patch("llm.qa.urlopen", return_value=mock_response),
        patch(
            "llm.qa.embed_query",
            return_value=[0.1] * 768,
        ),
    ):
        result = answer_run_question(
            question="What happened with the helmet?",
            coverage=_coverage(),
            incidents=(_incident(),),
            briefings=(),
            gemini_api_key="fake-key",
        )
    assert result.refused is False
    assert "gemini_qa" in result.tool_trace
    assert "helmet" in result.answer.lower()


def test_gemini_qa_falls_back_on_error():
    with (
        patch("llm.qa.urlopen", side_effect=TimeoutError("timeout")),
        patch("llm.qa.embed_query", return_value=[0.0] * 768),
    ):
        result = answer_run_question(
            question="How many helmet violations?",
            coverage=_coverage(),
            incidents=(_incident(),),
            briefings=(),
            gemini_api_key="fake-key",
        )
    # Should fall through to deterministic
    assert result.refused is False
    assert "R1" in result.answer
