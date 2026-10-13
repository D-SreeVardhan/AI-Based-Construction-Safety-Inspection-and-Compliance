"""R4: worker near active machinery, in Worker-Heights (v7 §11 R4, §40.5)."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

import numpy as np

from pipeline.geometry.context import GeometryContext
from pipeline.geometry.distance import classify_band, distance_interval, point_to_polyline
from pipeline.geometry.machinery import contact_pixels, contact_visible, operating_states
from pipeline.rules.incidents import make_incident
from pipeline.rules.windows import longest_window
from shared.config import RulesConfig
from shared.coordinates import DistanceInterval
from shared.enums import DistanceBand, OperatingState, RuleId, RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.run import RuleCoverageEntry
from shared.schemas.tracks import Pass1TrackObservation

# Detector box edges are localised to a couple of percent of the box height.
_LOCALISATION_FRACTION = 0.02


def _coverage(status: RuleStatus, reason: str) -> RuleCoverageEntry:
    return RuleCoverageEntry(rule_id=RuleId.R4, status=status, reason_code=reason)


def evaluate_r4(
    *,
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    context: GeometryContext | None,
    person_tracks: Mapping[str, Sequence[Pass1TrackObservation]],
    vehicle_tracks: Mapping[str, Sequence[Pass1TrackObservation]],
    config: RulesConfig,
) -> tuple[list[IncidentRecord], RuleCoverageEntry]:
    if context is not None and context.feed_unstable:
        return [], _coverage(RuleStatus.UNSUPPORTED, "geometry_unstable_for_feed")
    if not vehicle_tracks:
        return [], _coverage(RuleStatus.NOT_APPLICABLE, "no_machinery_tracks")
    vehicles_by_frame: dict[int, list[tuple[str, Pass1TrackObservation]]] = defaultdict(list)
    for vehicle_id, observations in vehicle_tracks.items():
        for obs in observations:
            vehicles_by_frame[obs.frame_index].append((vehicle_id, obs))
    if not any(o.frame_index in vehicles_by_frame for obs in person_tracks.values() for o in obs):
        return [], _coverage(RuleStatus.NOT_APPLICABLE, "no_worker_machinery_overlap")
    if context is None or not context.plane_ready:
        return [], _coverage(RuleStatus.INCONCLUSIVE, "relative_plane_unavailable")

    ensemble = context.ensemble
    assert ensemble is not None  # plane_ready guarantees it
    rng = np.random.default_rng(context.uncertainty.seed)
    states = {vid: operating_states(obs, ensemble, config) for vid, obs in vehicle_tracks.items()}

    alerts: dict[tuple[str, str], list[tuple[Pass1TrackObservation, DistanceInterval]]] = (
        defaultdict(list)
    )
    unresolved: dict[tuple[str, str, str], list[Pass1TrackObservation]] = defaultdict(list)
    checked = incompatible = 0

    for track_id, observations in person_tracks.items():
        for worker in observations:
            for vehicle_id, vehicle in vehicles_by_frame.get(worker.frame_index, ()):
                if not contact_visible(vehicle, context.content_bottom):
                    incompatible += 1
                    continue
                anchor = np.array([worker.anchor_reference.x, worker.anchor_reference.y])
                contact = contact_pixels(vehicle)
                ground = ensemble.ground(np.vstack([anchor[None, :], contact]))
                if not ensemble.in_support(ground).all():
                    incompatible += 1
                    continue
                checked += 1
                inflation = config.r4_vehicle_inflation_wh
                if (
                    point_to_polyline(ground[0], ground[1:]) - inflation
                    > config.r4_candidate_max_wh
                ):
                    continue
                interval = distance_interval(
                    ensemble,
                    anchor,
                    contact,
                    worker_sigma_px=_LOCALISATION_FRACTION * worker.box_reference.height(),
                    target_sigma_px=_LOCALISATION_FRACTION * vehicle.box_reference.height(),
                    inflation_wh=inflation,
                    uncertainty=context.uncertainty,
                    rng=rng,
                )
                band = classify_band(interval, config.r4_near_max_wh, config.r4_caution_max_wh)
                if band in (DistanceBand.CLEAR, DistanceBand.CAUTION):
                    continue
                state = states[vehicle_id].get(vehicle.frame_index, OperatingState.UNKNOWN)
                if state is OperatingState.UNKNOWN:
                    unresolved[(track_id, vehicle_id, "operating_state_unknown")].append(worker)
                elif band is DistanceBand.INDETERMINATE or interval is None:
                    unresolved[(track_id, vehicle_id, "inconclusive_distance")].append(worker)
                elif state is OperatingState.ACTIVE:
                    alerts[(track_id, vehicle_id)].append((worker, interval))

    debounce = config.r4_debounce_seconds
    incidents = _incidents(
        alerts, run_id, shot_id, catalogue_sha256, debounce, ensemble.plane.inlier_ratio
    )
    if incidents:
        return incidents, _coverage(RuleStatus.EVALUATED_ALERT, "active_machine_near_band")
    reasons: Counter[str] = Counter()
    for (_, _, reason), workers in unresolved.items():
        window = longest_window(workers, debounce * 2)
        if window is not None and window[2] >= debounce:
            reasons[reason] += 1
    if reasons:
        return [], _coverage(RuleStatus.INCONCLUSIVE, reasons.most_common(1)[0][0])
    if checked == 0 and incompatible > 0:
        return [], _coverage(RuleStatus.INCONCLUSIVE, "target_plane_incompatible")
    return [], _coverage(RuleStatus.EVALUATED_CLEAR, "outside_active_near_band")


def _incidents(
    alerts: Mapping[tuple[str, str], Sequence[tuple[Pass1TrackObservation, DistanceInterval]]],
    run_id: str,
    shot_id: str,
    catalogue_sha256: str,
    debounce: float,
    confidence: float,
) -> list[IncidentRecord]:
    incidents: list[IncidentRecord] = []
    for (track_id, vehicle_id), pairs in alerts.items():
        by_obs = {id(obs): interval for obs, interval in pairs}
        window = longest_window([obs for obs, _ in pairs], debounce * 2)
        if window is None or window[2] < debounce:
            continue
        first, last, span = window
        closest = min(
            (
                by_obs[id(o)]
                for o, _ in pairs
                if first.video_time_s <= o.video_time_s <= last.video_time_s
            ),
            key=lambda i: i.median_wh,
        )
        incidents.append(
            make_incident(
                run_id=run_id,
                shot_id=shot_id,
                catalogue_sha256=catalogue_sha256,
                rule_id=RuleId.R4,
                reason_code="active_machine_near_band",
                severity="high",
                track_id=track_id,
                first=first,
                last=last,
                debounce_s=debounce,
                confidence=confidence,
                object_id=vehicle_id,
                distance=closest,
                relative_band=DistanceBand.NEAR,
                observation_text=(
                    f"{track_id} stayed within {closest.upper_wh:.1f} worker-heights (upper bound, "
                    f"{closest.confidence_level:.0%} interval {closest.lower_wh:.1f}-"
                    f"{closest.upper_wh:.1f} WH) of moving machinery {vehicle_id} from "
                    f"{first.video_time_s:.1f}s to {last.video_time_s:.1f}s ({span:.1f}s)."
                ),
                action_code="review_machinery_separation",
                action_text=(
                    "Check on site that pedestrians are kept clear of the machine's working "
                    "area. Distances are relative to worker height in this video, not metres."
                ),
            )
        )
    return incidents
