from __future__ import annotations

import json
import os
from collections import Counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from llm.embeddings import embed_query
from llm.regulations import BOOTSTRAP_CLAUSES
from llm.retrieval import retrieve_clauses_hybrid
from shared.enums import RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.llm import GroundedBriefing, RunQuestionAnswer
from shared.schemas.run import RuleCoverageEntry

LEGAL_VERDICT_TERMS = (
    "is this legal",
    "is this illegal",
    "legally compliant",
    "compliance decision",
    "are they liable",
    "who is liable",
    "legal liability",
    "certify compliance",
)
RULE_TERMS: dict[RuleId, tuple[str, ...]] = {
    RuleId.R1: ("r1", "helmet", "head", "hardhat"),
    RuleId.R2: ("r2", "vest", "hi-vis", "visibility", "hiviz"),
    RuleId.R3: ("r3", "restricted", "zone"),
    RuleId.R4: ("r4", "machine", "machinery", "plant", "excavator", "near"),
    RuleId.R5: ("r5", "edge", "fall", "height"),
}

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_SYSTEM_PROMPT = (
    "You are a construction safety analyst reviewing an automated CCTV inspection report. "
    "Answer questions about the incidents, rule coverage, and regulation clauses from this run.\n"
    "\n"
    "STRICT RULES:\n"
    "- Only answer using the context provided. Do not use outside knowledge.\n"
    "- Never make legal verdicts (compliant / non-compliant / liable / illegal).\n"
    '- If insufficient context, say: "I cannot determine this from the available run data."\n'
    '- Cite clause references when relevant (e.g. "per BOCW Central Rules r67(1)").\n'
    "- Be concise: 2-4 sentences maximum."
)


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


def _build_context(
    *,
    incidents: tuple[IncidentRecord, ...],
    briefings: tuple[GroundedBriefing, ...],
    coverage: tuple[RuleCoverageEntry, ...],
    retrieved_chunks: list,
) -> str:
    """Assemble a compact context block for the Gemini prompt."""
    lines: list[str] = []

    lines.append("=== RULE COVERAGE ===")
    for cov in coverage:
        lines.append(f"{cov.rule_id.value}: {cov.status.value} ({cov.reason_code})")

    lines.append("\n=== INCIDENTS ===")
    if incidents:
        for inc in incidents[:5]:  # cap at 5 to keep context bounded
            conf_str = f"{inc.confidence:.2f}" if inc.confidence is not None else "n/a"
            resolved = inc.resolved_at_s or inc.first_seen_s
            lines.append(
                f"[{inc.incident_id}] {inc.rule_id.value} {inc.status.value} "
                f"track={inc.canonical_track_id or 'n/a'} "
                f"t={inc.first_seen_s:.1f}s\u2013{resolved:.1f}s conf={conf_str}"
            )
            lines.append(f"  {inc.observation_text}")
            lines.append(f"  Action: {inc.action_text}")
    else:
        lines.append("No incidents detected in this run.")

    lines.append("\n=== RETRIEVED REGULATION CLAUSES ===")
    if retrieved_chunks:
        for hit in retrieved_chunks[:4]:
            lines.append(f"[{hit.chunk.clause_ref}] {hit.chunk.title}")
            lines.append(f"  {hit.chunk.text}")
    else:
        lines.append("No clauses retrieved.")

    return "\n".join(lines)


def _call_gemini_qa(
    *,
    question: str,
    context: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout_s: int = 30,
) -> str:
    url = f"{_GEMINI_BASE}/{model}:generateContent?key={api_key}"
    prompt = f"{_SYSTEM_PROMPT}\n\n{context}\n\n=== QUESTION ===\n{question}"
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 512},
        }
    ).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout_s) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini QA {exc.code}: {detail}") from exc
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    return candidates[0]["content"]["parts"][0]["text"].strip()


def answer_run_question(
    *,
    question: str,
    coverage: tuple[RuleCoverageEntry, ...],
    incidents: tuple[IncidentRecord, ...],
    briefings: tuple[GroundedBriefing, ...],
    gemini_api_key: str | None = None,
    embeddings: dict[str, list[float]] | None = None,
) -> RunQuestionAnswer:
    """Answer a question about a completed run.

    When *gemini_api_key* is provided the answer is generated by Gemini with
    retrieved regulation context (Gemini RAG path).  Without a key the system
    falls back to the deterministic pattern-matching path.
    """
    api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
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

    # ── Retrieve relevant clauses for context ───────────────────────────────
    rule_id = _matches_rule(lowered)
    try:
        query_embedding: list[float] | None = (
            embed_query(clean_question, api_key=api_key) if api_key else None
        )
    except Exception:
        query_embedding = None

    retrieved = retrieve_clauses_hybrid(
        clean_question,
        rule_id=rule_id,
        top_k=4,
        corpus=BOOTSTRAP_CLAUSES,
        query_embedding=query_embedding,
        embeddings=embeddings,
    )

    # ── Gemini RAG path ─────────────────────────────────────────────────────
    if api_key:
        context = _build_context(
            incidents=incidents,
            briefings=briefings,
            coverage=coverage,
            retrieved_chunks=list(retrieved),
        )
        try:
            answer = _call_gemini_qa(
                question=clean_question,
                context=context,
                api_key=api_key,
            )
            return RunQuestionAnswer(
                question=clean_question,
                answer=answer,
                tool_trace=("embed_query", "retrieve_hybrid", "gemini_qa"),
                cited_incident_ids=_incident_ids(incidents),
                cited_clause_ids=tuple(h.chunk.chunk_id for h in retrieved),
            )
        except (RuntimeError, OSError, TimeoutError):
            # Gemini unavailable — fall through to deterministic path
            pass

    # ── Deterministic fallback ──────────────────────────────────────────────
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
