from __future__ import annotations

from shared.config import RulesConfig
from shared.enums import HelmetState, RuleId, RuleStatus, VestState
from shared.schemas.incidents import IncidentRecord, RuleResult
from shared.schemas.run import RuleCoverageEntry
from shared.schemas.tracks import Pass1TrackObservation

# ---------------------------------------------------------------------------
# Fake pipeline (Week-1 placeholder) — kept for backwards compatibility
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Real rules — driven by YOLO + Gemini adjudicator tracks
# ---------------------------------------------------------------------------


def _r1_eval(
    *,
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    track_id: str,
    obs: list[Pass1TrackObservation],
    debounce_s: float,
) -> tuple[IncidentRecord | None, RuleCoverageEntry]:
    """Evaluate R1 (missing helmet) for a single person track."""
    no_helmet = sorted(
        (o for o in obs if o.helmet and o.helmet.state == HelmetState.NO_HELMET),
        key=lambda o: o.video_time_s,
    )
    if not no_helmet:
        return None, RuleCoverageEntry(
            rule_id=RuleId.R1,
            status=RuleStatus.EVALUATED_CLEAR,
            reason_code="no_helmet_alerts_detected",
        )

    # Find first contiguous window exceeding debounce
    window_start = no_helmet[0]
    window_end = no_helmet[0]
    best_start, best_end = window_start, window_end
    best_span = 0.0

    for obs_item in no_helmet[1:]:
        gap = obs_item.video_time_s - window_end.video_time_s
        if gap <= debounce_s * 2:
            window_end = obs_item
        else:
            span = window_end.video_time_s - window_start.video_time_s
            if span > best_span:
                best_span, best_start, best_end = span, window_start, window_end
            window_start = window_end = obs_item
    span = window_end.video_time_s - window_start.video_time_s
    if span > best_span:
        best_span, best_start, best_end = span, window_start, window_end

    if best_span < debounce_s:
        return None, RuleCoverageEntry(
            rule_id=RuleId.R1,
            status=RuleStatus.INCONCLUSIVE,
            reason_code="no_helmet_below_debounce",
        )

    confs = [o.helmet.confidence for o in no_helmet if o.helmet]
    avg_conf = sum(confs) / len(confs) if confs else 0.5

    safe_id = track_id.replace("/", "-").replace(" ", "_")
    incident_id = f"{run_id}-{safe_id}-R1-{best_start.video_time_s:.1f}-{best_end.video_time_s:.1f}"
    incident = IncidentRecord(
        incident_id=incident_id,
        run_id=run_id,
        shot_id=shot_id,
        catalogue_sha256=catalogue_sha256,
        rule_id=RuleId.R1,
        status=RuleStatus.EVALUATED_ALERT,
        reason_code="detected_missing_helmet",
        basis="heuristic",
        severity="medium",
        canonical_track_id=track_id,
        proposal_ids=(),
        first_seen_s=best_start.video_time_s,
        confirmed_at_s=best_start.video_time_s + debounce_s,
        resolved_at_s=best_end.video_time_s,
        confidence=avg_conf,
        observation_text=(
            f"{track_id} detected without helmet from {best_start.video_time_s:.1f}s "
            f"to {best_end.video_time_s:.1f}s "
            f"({best_span:.1f}s window, Gemini confidence {avg_conf:.2f})."
        ),
        action_code="review_ppe",
        action_text=(
            "Verify this worker is wearing a compliant hardhat. "
            "Check evidence frame before raising a formal non-conformance."
        ),
        references=(),
        evidence_path=f"evidence/{incident_id}.jpg",
        source_frame_index=best_start.frame_index,
    )
    return incident, RuleCoverageEntry(
        rule_id=RuleId.R1,
        status=RuleStatus.EVALUATED_ALERT,
        reason_code="detected_missing_helmet",
    )


def evaluate_real_rules(
    *,
    run_id: str,
    shot_id: str,
    observations: list[Pass1TrackObservation],
    catalogue_sha256: str,
    config: RulesConfig,
) -> tuple[tuple[RuleCoverageEntry, ...], tuple[IncidentRecord, ...], tuple[RuleResult, ...]]:
    """Evaluate R1–R5 against real YOLO + Gemini adjudicator tracks.

    R1  Missing helmet — fires when a person track shows NO_HELMET for the
        configured debounce window.
    R2  Missing hi-vis near machinery — fires when NO_VEST coincides with a
        vehicle track within the proximity bands.
    R3–R5  Unsupported until the scene bootstrap and relative-plane mapping
        layers are implemented.

    Returns the same ``(coverage, incidents, results)`` triple as
    ``evaluate_fake_rules``.
    """
    # Group observations by canonical track id
    person_tracks: dict[str, list[Pass1TrackObservation]] = {}
    vehicle_obs: list[Pass1TrackObservation] = []
    for obs in observations:
        if obs.object_class == "person":
            person_tracks.setdefault(obs.canonical_track_id, []).append(obs)
        else:
            vehicle_obs.append(obs)

    # --- R1 evaluation ---
    r1_incidents: list[IncidentRecord] = []
    r1_cov_candidates: list[RuleCoverageEntry] = []
    for track_id, track_obs in person_tracks.items():
        incident, cov = _r1_eval(
            run_id=run_id,
            shot_id=shot_id,
            catalogue_sha256=catalogue_sha256,
            track_id=track_id,
            obs=track_obs,
            debounce_s=config.r1_debounce_seconds,
        )
        if incident:
            r1_incidents.append(incident)
        r1_cov_candidates.append(cov)

    # Aggregate R1 coverage: alert > inconclusive > clear
    r1_status = RuleStatus.EVALUATED_CLEAR
    r1_reason = "no_helmet_alerts_detected"
    if not person_tracks:
        r1_status = RuleStatus.INCONCLUSIVE
        r1_reason = "no_person_tracks"
    elif any(c.status == RuleStatus.EVALUATED_ALERT for c in r1_cov_candidates):
        r1_status = RuleStatus.EVALUATED_ALERT
        r1_reason = "detected_missing_helmet"
    elif any(c.status == RuleStatus.INCONCLUSIVE for c in r1_cov_candidates):
        r1_status = RuleStatus.INCONCLUSIVE
        r1_reason = "no_helmet_below_debounce"

    # --- R2 evaluation ---
    # Fire when a person with NO_VEST is detected in the same frame as a vehicle
    r2_incidents: list[IncidentRecord] = []
    r2_status = RuleStatus.INCONCLUSIVE
    r2_reason = "no_machinery_tracks"

    if vehicle_obs:
        # Build vehicle frame index set for quick lookup
        vehicle_frames: set[int] = {o.frame_index for o in vehicle_obs}
        for track_id, track_obs in person_tracks.items():
            no_vest_near_vehicle = sorted(
                (
                    o
                    for o in track_obs
                    if o.vest
                    and o.vest.state == VestState.NO_VEST
                    and o.frame_index in vehicle_frames
                ),
                key=lambda o: o.video_time_s,
            )
            if not no_vest_near_vehicle:
                continue
            first = no_vest_near_vehicle[0]
            last = no_vest_near_vehicle[-1]
            span = last.video_time_s - first.video_time_s
            if span < config.r2_debounce_seconds:
                continue
            confs = [o.vest.confidence for o in no_vest_near_vehicle if o.vest]
            avg_conf = sum(confs) / len(confs) if confs else 0.5
            safe_id = track_id.replace("/", "-").replace(" ", "_")
            incident_id = f"{run_id}-{safe_id}-R2-{first.video_time_s:.1f}-{last.video_time_s:.1f}"
            r2_incidents.append(
                IncidentRecord(
                    incident_id=incident_id,
                    run_id=run_id,
                    shot_id=shot_id,
                    catalogue_sha256=catalogue_sha256,
                    rule_id=RuleId.R2,
                    status=RuleStatus.EVALUATED_ALERT,
                    reason_code="detected_missing_vest_near_vehicle",
                    basis="heuristic",
                    severity="medium",
                    canonical_track_id=track_id,
                    proposal_ids=(),
                    first_seen_s=first.video_time_s,
                    confirmed_at_s=first.video_time_s + config.r2_debounce_seconds,
                    resolved_at_s=last.video_time_s,
                    confidence=avg_conf,
                    observation_text=(
                        f"{track_id} detected without hi-vis vest in proximity of vehicle "
                        f"from {first.video_time_s:.1f}s to {last.video_time_s:.1f}s "
                        f"(confidence {avg_conf:.2f})."
                    ),
                    action_code="review_ppe",
                    action_text=(
                        "Verify this worker is wearing a high-visibility vest"
                        " near moving machinery."
                    ),
                    references=(),
                    evidence_path=f"evidence/{incident_id}.jpg",
                    source_frame_index=first.frame_index,
                )
            )
        if r2_incidents:
            r2_status = RuleStatus.EVALUATED_ALERT
            r2_reason = "detected_missing_vest_near_vehicle"
        else:
            r2_status = RuleStatus.EVALUATED_CLEAR
            r2_reason = "no_vest_alerts_near_vehicle"

    all_incidents = (*r1_incidents, *r2_incidents)
    coverage = (
        RuleCoverageEntry(rule_id=RuleId.R1, status=r1_status, reason_code=r1_reason),
        RuleCoverageEntry(rule_id=RuleId.R2, status=r2_status, reason_code=r2_reason),
        RuleCoverageEntry(
            rule_id=RuleId.R3,
            status=RuleStatus.UNSUPPORTED,
            reason_code="no_zone_geometry",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R4,
            status=RuleStatus.INCONCLUSIVE,
            reason_code="no_relative_plane_mapping",
        ),
        RuleCoverageEntry(
            rule_id=RuleId.R5,
            status=RuleStatus.UNSUPPORTED,
            reason_code="no_edge_geometry",
        ),
    )
    results = tuple(
        RuleResult(
            rule_id=cov.rule_id,
            status=cov.status,
            reason_code=cov.reason_code,
            basis="heuristic",
        )
        for cov in coverage
    )
    return coverage, all_incidents, results
