from __future__ import annotations

from shared.enums import RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord, RuleResult
from shared.schemas.run import RuleCoverageEntry


def evaluate_fake_rules(
    *,
    run_id: str,
    shot_id: str,
    catalogue_sha256: str = "synthetic-catalogue-unversioned",
) -> tuple[tuple[RuleCoverageEntry, ...], tuple[IncidentRecord, ...], tuple[RuleResult, ...]]:
    """Thin R1–R5 vertical slice for Week-1 placeholder runs.

    Every rule appears in coverage. One synthetic R1 alert is emitted so the
    output folder always contains a demonstrable incident card.
    """
    coverage = (
        RuleCoverageEntry(
            rule_id=RuleId.R1,
            status=RuleStatus.EVALUATED_ALERT,
            reason_code="fake_missing_helmet",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R2,
            status=RuleStatus.EVALUATED_CLEAR,
            reason_code="fake_vest_ok",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R3,
            status=RuleStatus.UNSUPPORTED,
            reason_code="fake_no_zone_geometry",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R4,
            status=RuleStatus.INCONCLUSIVE,
            reason_code="fake_no_machinery_tracks",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R5,
            status=RuleStatus.UNSUPPORTED,
            reason_code="fake_no_edge_geometry",
        ),
    )

    results = tuple(
        RuleResult(
            rule_id=entry.rule_id,
            status=entry.status,
            reason_code=entry.reason_code,
            basis="heuristic",
            track_id="shot/person-1" if entry.rule_id == RuleId.R1 else None,
            confidence=0.72 if entry.rule_id == RuleId.R1 else None,
            observed_from_s=1.0 if entry.rule_id == RuleId.R1 else None,
            observed_to_s=2.5 if entry.rule_id == RuleId.R1 else None,
        )
        for entry in coverage
    )

    incident = IncidentRecord(
        incident_id=f"{run_id}-person-1-R1-1.0-2.5",
        run_id=run_id,
        shot_id=shot_id,
        catalogue_sha256=catalogue_sha256,
        rule_id=RuleId.R1,
        status=RuleStatus.EVALUATED_ALERT,
        reason_code="fake_missing_helmet",
        basis="heuristic",
        severity="medium",
        canonical_track_id="shot/person-1",
        proposal_ids=(),
        first_seen_s=1.0,
        confirmed_at_s=1.5,
        resolved_at_s=2.5,
        confidence=0.72,
        observation_text=(
            "Placeholder alert: person-1 appears without a helmet between 1.0s and 2.5s "
            "(synthetic Week-1 fixture; not a real detector output)."
        ),
        action_code="review_ppe",
        action_text="Review PPE on the evidence frame. This is a heuristic placeholder.",
        references=(),
        evidence_path=f"evidence/{run_id}-person-1-R1-1.0-2.5.jpg",
        source_frame_index=30,
    )
    return coverage, (incident,), results
