from __future__ import annotations

from pydantic import Field

from shared.coordinates import DistanceInterval, StrictModel
from shared.enums import DistanceBand, RuleId, RuleStatus
from shared.schemas.tracks import HelmetRecord, VestRecord


class RuleResult(StrictModel):
    rule_id: RuleId
    status: RuleStatus
    reason_code: str
    basis: str
    track_id: str | None = None
    object_id: str | None = None
    proposal_ids: tuple[str, ...] = ()
    observed_from_s: float | None = None
    observed_to_s: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    distance: DistanceInterval | None = None
    relative_band: DistanceBand | None = None
    references: tuple[str, ...] = ()


class TracePoint(StrictModel):
    """The rule's view of one subject at one moment: the condition and its key signal."""

    t: float = Field(ge=0.0)
    state: str  # holds | clear | unknown
    value: float | None = None  # PPE confidence (R1/R2) or median distance in WH (R4/R5)
    lower: float | None = None
    upper: float | None = None


class IncidentTrace(StrictModel):
    """Why an incident fired: the condition over time, from 2 s before it began to 2 s
    after it ended, thinned to at most a few points per second (state changes always kept)."""

    metric: str  # confidence | distance_wh | state
    debounce_s: float = Field(ge=0.0)
    observed_fraction: float = Field(ge=0.0, le=1.0)
    points: tuple[TracePoint, ...]


class IncidentNarration(StrictModel):
    """Readable briefing for an incident (L4), shown only after the L5 guardrail passed.

    `source` is "model" when the fine-tuned narrator's text passed all eight checks and
    "template" when it fell back to the deterministic text.
    """

    summary: str
    caveat: str
    action: str
    source: str
    model: str | None = None
    failed_checks: tuple[str, ...] = ()


class IncidentRecord(StrictModel):
    schema_version: int = 1
    incident_id: str
    run_id: str
    shot_id: str
    catalogue_sha256: str
    rule_id: RuleId
    status: RuleStatus
    reason_code: str
    basis: str
    severity: str
    canonical_track_id: str | None = None
    object_id: str | None = None
    proposal_ids: tuple[str, ...] = ()
    first_seen_s: float = Field(ge=0.0)
    confirmed_at_s: float = Field(ge=0.0)
    resolved_at_s: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    distance: DistanceInterval | None = None
    relative_band: DistanceBand | None = None
    title: str = ""
    observation_text: str
    action_code: str
    action_text: str
    references: tuple[str, ...] = ()
    evidence_path: str
    source_frame_index: int = Field(ge=0)
    # Original-resolution person crop at the evidence frame (L1 vision adjudication input).
    evidence_crop_path: str | None = None
    # Smoothed PPE state at the evidence frame, shown beside the rule verdict.
    helmet: HelmetRecord | None = None
    vest: VestRecord | None = None
    # True when a PPE head was unknown or near the confidence floor at the evidence
    # frame, so the cloud service should queue the crop for L1 adjudication.
    adjudication_candidate: bool = False
    # Why the episode ended: condition_cleared | evidence_lost | shot_boundary | end_of_clip.
    resolution_reason: str | None = None
    narration: IncidentNarration | None = None
    # v3: explainability and triage.
    trace: IncidentTrace | None = None
    # strong | moderate | weak: how well the video supports the alert (see the engine).
    evidence_quality: str | None = None
    evidence_clip_path: str | None = None
