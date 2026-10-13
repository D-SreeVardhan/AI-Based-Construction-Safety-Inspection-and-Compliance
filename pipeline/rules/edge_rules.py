"""R5: worker near a visibly unprotected open edge (v7 §11 R5, §40.6).

Absence of a detected guardrail is never read as "unguarded": the scene bootstrap must have
positively reported an exposed edge, sufficient visibility of its protection, and an
unguarded or inadequate state before a worker's distance to it can raise an alert.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

import numpy as np

from pipeline.geometry.context import GeometryContext
from pipeline.geometry.distance import classify_band, distance_interval, point_to_polyline
from pipeline.rules.incidents import make_incident
from pipeline.rules.windows import longest_window
from shared.config import RulesConfig
from shared.coordinates import DistanceInterval
from shared.enums import DistanceBand, RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.run import RuleCoverageEntry
from shared.schemas.scene import SceneModel, SceneProposal
from shared.schemas.tracks import Pass1TrackObservation

_LOCALISATION_FRACTION = 0.02
# Edge geometry comes from a keyframe proposal, so give it a looser pixel tolerance.
_EDGE_SIGMA_FRACTION = 0.005
# Reported when several edges are blocked, most fundamental first.
_BLOCKER_ORDER = (
    "edge_semantics_unknown",
    "protection_visibility_insufficient",
    "protection_state_unknown",
)


def _coverage(status: RuleStatus, reason: str) -> RuleCoverageEntry:
    return RuleCoverageEntry(rule_id=RuleId.R5, status=status, reason_code=reason)


def _blocker(edge: SceneProposal) -> str | None:
    """Why an edge cannot support an alert, or None when it is positively unguarded."""
    if edge.visible_drop_or_open_side is not True:
        return "edge_semantics_unknown"
    if edge.protection_visibility != "sufficient":
        return "protection_visibility_insufficient"
    if edge.protection_state == "unguarded_or_inadequate":
        return None
    return "guarded" if edge.protection_state == "guarded" else "protection_state_unknown"


def evaluate_r5(
    *,
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    context: GeometryContext | None,
    scene: SceneModel | None,
    person_tracks: Mapping[str, Sequence[Pass1TrackObservation]],
    config: RulesConfig,
) -> tuple[list[IncidentRecord], RuleCoverageEntry]:
    if context is not None and context.feed_unstable:
        return [], _coverage(RuleStatus.UNSUPPORTED, "geometry_unstable_for_feed")
    if scene is None or scene.status != "ok":
        return [], _coverage(RuleStatus.INCONCLUSIVE, "scene_state_unavailable")
    edges = scene.of_type("open_edge")
    if not edges:
        return [], _coverage(RuleStatus.NOT_APPLICABLE, "no_visible_open_edge_candidate")

    blockers = {_blocker(e) for e in edges} - {None, "guarded"}
    unguarded = [e for e in edges if _blocker(e) is None]
    if not unguarded:
        for reason in _BLOCKER_ORDER:
            if reason in blockers:
                return [], _coverage(RuleStatus.INCONCLUSIVE, reason)
        return [], _coverage(RuleStatus.EVALUATED_CLEAR, "guarded_or_outside_edge_band")
    if not person_tracks:
        return [], _coverage(RuleStatus.NOT_APPLICABLE, "no_person_tracks")
    if context is None or not context.plane_ready:
        return [], _coverage(RuleStatus.INCONCLUSIVE, "relative_plane_unavailable")

    ensemble = context.ensemble
    assert ensemble is not None  # plane_ready guarantees it
    rng = np.random.default_rng(context.uncertainty.seed)
    usable: list[tuple[SceneProposal, np.ndarray]] = []
    for edge in unguarded:
        pixels = np.array(edge.points, dtype=float)
        if ensemble.in_support(ensemble.ground(pixels)).all():
            usable.append((edge, pixels))
    if not usable:
        return [], _coverage(RuleStatus.INCONCLUSIVE, "target_plane_incompatible")

    alerts: dict[tuple[str, str], list[tuple[Pass1TrackObservation, DistanceInterval]]] = (
        defaultdict(list)
    )
    unresolved: dict[tuple[str, str], list[Pass1TrackObservation]] = defaultdict(list)
    for track_id, observations in person_tracks.items():
        for worker in observations:
            anchor = np.array([worker.anchor_reference.x, worker.anchor_reference.y])
            worker_ground = ensemble.ground(anchor[None, :])
            if not ensemble.in_support(worker_ground).all():
                continue
            for edge, pixels in usable:
                edge_ground = ensemble.ground(pixels)
                if point_to_polyline(worker_ground[0], edge_ground) > config.r4_candidate_max_wh:
                    continue
                interval = distance_interval(
                    ensemble,
                    anchor,
                    pixels,
                    worker_sigma_px=_LOCALISATION_FRACTION * worker.box_reference.height(),
                    target_sigma_px=_EDGE_SIGMA_FRACTION * context.image_diagonal_px,
                    inflation_wh=0.0,
                    uncertainty=context.uncertainty,
                    rng=rng,
                )
                band = classify_band(interval, config.r5_edge_max_wh, config.r5_edge_max_wh)
                key = (track_id, edge.proposal_id)
                if band is DistanceBand.NEAR and interval is not None:
                    alerts[key].append((worker, interval))
                elif band is DistanceBand.INDETERMINATE:
                    unresolved[key].append(worker)

    debounce = config.r5_debounce_seconds
    incidents = _incidents(
        alerts, run_id, shot_id, catalogue_sha256, debounce, ensemble.plane.inlier_ratio, config
    )
    if incidents:
        return incidents, _coverage(RuleStatus.EVALUATED_ALERT, "visible_unguarded_edge")
    for workers in unresolved.values():
        window = longest_window(workers, debounce * 2)
        if window is not None and window[2] >= debounce:
            return [], _coverage(RuleStatus.INCONCLUSIVE, "inconclusive_distance")
    if blockers:
        for reason in _BLOCKER_ORDER:
            if reason in blockers:
                return [], _coverage(RuleStatus.INCONCLUSIVE, reason)
    return [], _coverage(RuleStatus.EVALUATED_CLEAR, "guarded_or_outside_edge_band")


def _incidents(
    alerts: Mapping[tuple[str, str], Sequence[tuple[Pass1TrackObservation, DistanceInterval]]],
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    debounce: float,
    confidence: float,
    config: RulesConfig,
) -> list[IncidentRecord]:
    incidents: list[IncidentRecord] = []
    for (track_id, edge_id), pairs in alerts.items():
        window = longest_window([obs for obs, _ in pairs], debounce * 2)
        if window is None or window[2] < debounce:
            continue
        first, last, span = window
        closest = min(
            (i for o, i in pairs if first.video_time_s <= o.video_time_s <= last.video_time_s),
            key=lambda i: i.median_wh,
        )
        incidents.append(
            make_incident(
                run_id=run_id,
                shot_id=shot_id,
                catalogue_sha256=catalogue_sha256,
                rule_id=RuleId.R5,
                reason_code="visible_unguarded_edge",
                severity="high",
                track_id=track_id,
                first=first,
                last=last,
                debounce_s=debounce,
                confidence=confidence,
                proposal_ids=(edge_id,),
                distance=closest,
                relative_band=DistanceBand.NEAR,
                observation_text=(
                    f"{track_id} stayed within {config.r5_edge_max_wh:.1f} worker-heights of "
                    f"{edge_id}, an open edge reported as unguarded or inadequately protected "
                    f"(95% interval {closest.lower_wh:.1f}-{closest.upper_wh:.1f} WH), from "
                    f"{first.video_time_s:.1f}s to {last.video_time_s:.1f}s ({span:.1f}s)."
                ),
                action_code="review_edge_protection",
                action_text=(
                    "Check on site whether this edge is exposed and what protection is in "
                    "place. The edge is inferred from video and distances are relative."
                ),
            )
        )
    return incidents
