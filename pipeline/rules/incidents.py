"""Shared construction of incident records for the geometry-driven rules."""

from __future__ import annotations

from shared.coordinates import DistanceInterval
from shared.enums import DistanceBand, RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.tracks import Pass1TrackObservation


def make_incident(
    *,
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    rule_id: RuleId,
    reason_code: str,
    severity: str,
    track_id: str,
    first: Pass1TrackObservation,
    last: Pass1TrackObservation,
    debounce_s: float,
    confidence: float,
    observation_text: str,
    action_code: str,
    action_text: str,
    proposal_ids: tuple[str, ...] = (),
    object_id: str | None = None,
    distance: DistanceInterval | None = None,
    relative_band: DistanceBand | None = None,
) -> IncidentRecord:
    safe_id = track_id.replace("/", "-").replace(" ", "_")
    incident_id = (
        f"{run_id}-{safe_id}-{rule_id.value}-{first.video_time_s:.1f}-{last.video_time_s:.1f}"
    )
    return IncidentRecord(
        incident_id=incident_id,
        run_id=run_id,
        shot_id=shot_id,
        catalogue_sha256=catalogue_sha256,
        rule_id=rule_id,
        status=RuleStatus.EVALUATED_ALERT,
        reason_code=reason_code,
        basis="heuristic",
        severity=severity,
        canonical_track_id=track_id,
        object_id=object_id,
        proposal_ids=proposal_ids,
        first_seen_s=first.video_time_s,
        confirmed_at_s=first.video_time_s + debounce_s,
        resolved_at_s=last.video_time_s,
        confidence=max(0.0, min(1.0, confidence)),
        distance=distance,
        relative_band=relative_band,
        observation_text=observation_text,
        action_code=action_code,
        action_text=action_text,
        evidence_path=f"evidence/{incident_id}.jpg",
        source_frame_index=first.frame_index,
    )
