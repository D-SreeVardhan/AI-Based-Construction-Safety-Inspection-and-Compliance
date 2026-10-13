"""R3: restricted-zone intrusion (v7 §11 R3, §40.4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pipeline.rules.incidents import make_incident
from pipeline.rules.windows import longest_window
from pipeline.scene.geometry import signed_distance_to_polygon
from shared.enums import RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.run import RuleCoverageEntry
from shared.schemas.scene import SceneModel
from shared.schemas.tracks import Pass1TrackObservation

# The foot anchor is the box bottom-centre, uncertain by a few percent of the worker's height.
_ANCHOR_UNCERTAINTY = 0.05


def evaluate_r3(
    *,
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    scene: SceneModel | None,
    person_tracks: Mapping[str, Sequence[Pass1TrackObservation]],
    debounce_s: float,
) -> tuple[list[IncidentRecord], RuleCoverageEntry]:
    def coverage(status: RuleStatus, reason: str) -> RuleCoverageEntry:
        return RuleCoverageEntry(rule_id=RuleId.R3, status=status, reason_code=reason)

    if scene is None or scene.status != "ok":
        return [], coverage(RuleStatus.INCONCLUSIVE, "restricted_zone_scene_state_unavailable")
    zones = scene.of_type("restricted_zone")
    if not zones:
        return [], coverage(RuleStatus.NOT_APPLICABLE, "no_supported_restricted_zone")
    if not person_tracks:
        return [], coverage(RuleStatus.NOT_APPLICABLE, "no_person_tracks")

    incidents: list[IncidentRecord] = []
    boundary_uncertain = False
    for track_id, observations in person_tracks.items():
        for zone in zones:
            inside: list[Pass1TrackObservation] = []
            ambiguous: list[Pass1TrackObservation] = []
            for obs in observations:
                margin = _ANCHOR_UNCERTAINTY * obs.box_reference.height()
                distance = signed_distance_to_polygon(
                    (obs.anchor_reference.x, obs.anchor_reference.y), zone.points
                )
                if distance > margin:
                    inside.append(obs)
                elif distance >= -margin:
                    ambiguous.append(obs)
            window = longest_window(inside, debounce_s * 2)
            if window is not None and window[2] >= debounce_s:
                first, last, span = window
                incidents.append(
                    make_incident(
                        run_id=run_id,
                        shot_id=shot_id,
                        catalogue_sha256=catalogue_sha256,
                        rule_id=RuleId.R3,
                        reason_code="restricted_zone_entry",
                        severity="high",
                        track_id=track_id,
                        first=first,
                        last=last,
                        debounce_s=debounce_s,
                        confidence=zone.agreement_score,
                        proposal_ids=(zone.proposal_id,),
                        observation_text=(
                            f"{track_id} appears inside inferred restricted zone "
                            f"{zone.proposal_id} from {first.video_time_s:.1f}s to "
                            f"{last.video_time_s:.1f}s ({span:.1f}s; zone agreed by "
                            f"{len(zone.supporting_keyframes)} of {zone.eligible_keyframes} "
                            "keyframes)."
                        ),
                        action_code="review_zone_access",
                        action_text=(
                            "Check on site whether this region is restricted and whether the "
                            "worker is authorised to be there. The zone is inferred from "
                            "video, not surveyed."
                        ),
                    )
                )
            elif ambiguous:
                near_boundary = longest_window([*inside, *ambiguous], debounce_s * 2)
                if near_boundary is not None and near_boundary[2] >= debounce_s:
                    boundary_uncertain = True

    if incidents:
        return incidents, coverage(RuleStatus.EVALUATED_ALERT, "restricted_zone_entry")
    if boundary_uncertain:
        return [], coverage(RuleStatus.INCONCLUSIVE, "zone_boundary_uncertain")
    return [], coverage(RuleStatus.EVALUATED_CLEAR, "worker_outside_restricted_zone")
