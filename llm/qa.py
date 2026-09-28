from __future__ import annotations

from collections import Counter

from shared.enums import RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.llm import GroundedBriefing, RunQuestionAnswer
from shared.schemas.run import RuleCoverageEntry

LEGAL_VERDICT_TERMS = ("legal", "illegal", "compliant", "compliance", "violation", "liable")
RULE_TERMS: dict[RuleId, tuple[str, ...]] = {
    RuleId.R1: ("r1", "helmet", "head"),
    RuleId.R2: ("r2", "vest", "hi-vis", "visibility"),
    RuleId.R3: ("r3", "restricted", "zone"),
    RuleId.R4: ("r4", "machine", "machinery", "plant", "excavator", "near"),
    RuleId.R5: ("r5", "edge", "fall", "height"),
}


def _matches_rule(question: str) -> RuleId | None:
    lowered = question.lower()
    for rule_id, terms in RULE_TERMS.items():
        if any(term in lowered for term in terms):
            return rule_id
    return None


def _briefing_clause_ids(briefings: tuple[GroundedBriefing, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for briefing in briefings:
        for hit in briefing.retrieved_chunks:
            if hit.chunk.chunk_id not in seen:
                seen.append(hit.chunk.chunk_id)
    return tuple(seen)


def _clause_refs(briefings: tuple[GroundedBriefing, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for briefing in briefings:
        for hit in briefing.retrieved_chunks:
            if hit.chunk.clause_ref not in refs:
                refs.append(hit.chunk.clause_ref)
    return tuple(refs)


def _incident_ids(incidents: tuple[IncidentRecord, ...]) -> tuple[str, ...]:
    return tuple(incident.incident_id for incident in incidents)


def answer_run_question(
    *,
    question: str,
    coverage: tuple[RuleCoverageEntry, ...],
    incidents: tuple[IncidentRecord, ...],
    briefings: tuple[GroundedBriefing, ...],
) -> RunQuestionAnswer:
    clean_question = question.strip()
    lowered = clean_question.lower()
    if not clean_question:
        return RunQuestionAnswer(
            question=question,
            answer="Ask a question about this run's incidents, rule coverage, or cited clauses.",
            tool_trace=("validate_question",),
            refused=True,
            refusal_reason="empty_question",
        )
    if any(term in lowered for term in LEGAL_VERDICT_TERMS):
        return RunQuestionAnswer(
            question=clean_question,
            answer=(
                "I cannot decide legality or compliance. I can summarize visual findings and show "
                "the retrieved clauses for a human reviewer."
            ),
            tool_trace=("guardrail_refuse_legal_verdict",),
            refused=True,
            refusal_reason="legal_verdict_request",
        )

    rule_id = _matches_rule(lowered)
    if rule_id is not None:
        matching_incidents = tuple(
            incident for incident in incidents if incident.rule_id is rule_id
        )
        matching_coverage = tuple(entry for entry in coverage if entry.rule_id is rule_id)
        matching_briefings = tuple(
            briefing for briefing in briefings if briefing.rule_id is rule_id
        )
        if matching_incidents:
            first = matching_incidents[0]
            return RunQuestionAnswer(
                question=clean_question,
                answer=(
                    f"{rule_id.value} has {len(matching_incidents)} alert(s). "
                    f"First evidence: {first.observation_text}"
                ),
                tool_trace=("query_incidents", "retrieve_briefings"),
                cited_incident_ids=_incident_ids(matching_incidents),
                cited_clause_ids=_briefing_clause_ids(matching_briefings),
            )
        status = (
            matching_coverage[0].status.value
            if matching_coverage
            else RuleStatus.INCONCLUSIVE.value
        )
        reason = matching_coverage[0].reason_code if matching_coverage else "not_in_coverage"
        return RunQuestionAnswer(
            question=clean_question,
            answer=(
                f"{rule_id.value} has no alert in this run. Coverage status: {status} ({reason})."
            ),
            tool_trace=("summarize_coverage",),
        )

    if "clause" in lowered or "cite" in lowered or "reference" in lowered:
        refs = _clause_refs(briefings)
        answer = "Retrieved clauses: " + "; ".join(refs) if refs else "No clauses were retrieved."
        return RunQuestionAnswer(
            question=clean_question,
            answer=answer,
            tool_trace=("retrieve_briefings",),
            cited_incident_ids=_incident_ids(incidents),
            cited_clause_ids=_briefing_clause_ids(briefings),
        )

    counts = Counter(incident.rule_id.value for incident in incidents)
    if counts:
        summary = ", ".join(f"{rule}: {count}" for rule, count in sorted(counts.items()))
        answer = f"This run has {len(incidents)} alert(s): {summary}."
    else:
        answer = "This run has no alert incidents. Check rule coverage for unsupported rules."
    return RunQuestionAnswer(
        question=clean_question,
        answer=answer,
        tool_trace=("query_incidents", "summarize_coverage"),
        cited_incident_ids=_incident_ids(incidents),
        cited_clause_ids=_briefing_clause_ids(briefings),
    )
