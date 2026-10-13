from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from pipeline.geometry import content_rect
from pipeline.geometry.camera import CameraParams, ImageFrame, backproject, project
from pipeline.geometry.context import GeometryContext
from pipeline.geometry.distance import classify_band, distance_interval, point_to_polyline
from pipeline.geometry.machinery import contact_visible, operating_states
from pipeline.geometry.plane import PlaneEnsemble, PlaneFitError, fit_plane
from pipeline.geometry.pose import (
    estimate_camera_shift,
    select_candidates,
    standing_probability,
    vertical_from_keypoints,
)
from pipeline.rules.edge_rules import evaluate_r5
from pipeline.rules.proximity_rules import evaluate_r4
from shared.config import load_config
from shared.coordinates import Box2, DistanceInterval, Point2
from shared.enums import CoordinateSpace, DistanceBand, OperatingState, RuleStatus
from shared.schemas.geometry import GeometryModel, GroundPlane, VerticalObservation
from shared.schemas.scene import SceneModel, SceneProposal
from shared.schemas.tracks import Pass1TrackObservation

CONFIG = load_config()
FRAME = ImageFrame(cx=960.0, cy=540.0, width=1920.0, height=1080.0)
TRUE = CameraParams(focal_px=1700.0, pitch_rad=math.radians(28.0), height_wh=3.4)
REF = CoordinateSpace.REFERENCE


def _px(ground: tuple[float, float], lift: float = 0.0, camera: CameraParams = TRUE) -> np.ndarray:
    return project(
        np.array(ground), FRAME, camera.focal_px, camera.pitch_rad, camera.height_wh, lift
    )


# --- camera model -----------------------------------------------------------


def test_backproject_inverts_project() -> None:
    ground = np.array([[1.5, 7.0], [-2.0, 12.0]])
    pixels = project(ground, FRAME, TRUE.focal_px, TRUE.pitch_rad, TRUE.height_wh)
    recovered = backproject(pixels, FRAME, TRUE.focal_px, TRUE.pitch_rad, TRUE.height_wh)
    assert recovered == pytest.approx(ground, abs=1e-6)


def test_backproject_is_nan_at_or_above_the_horizon() -> None:
    horizon = FRAME.cy - TRUE.focal_px * math.tan(TRUE.pitch_rad)
    above = np.array([[960.0, horizon - 5.0]])
    assert np.isnan(backproject(above, FRAME, TRUE.focal_px, TRUE.pitch_rad, TRUE.height_wh)).all()


def test_content_rect_centres_portrait_video() -> None:
    assert content_rect(2160, 3840, 1920, 1080) == (656, 0, 608, 1080)
    assert content_rect(1920, 1080, 1920, 1080) == (0, 0, 1920, 1080)


# --- plane fit --------------------------------------------------------------


def _observations(
    seed: int = 1, tracks: int = 8, per_track: int = 7, noise: float = 0.5
) -> list[VerticalObservation]:
    rng = np.random.default_rng(seed)
    out = []
    for t in range(tracks):
        x, z = rng.uniform(-3, 3), rng.uniform(6, 16)
        for k in range(per_track):
            ground = (x + rng.normal(0, 0.05), z + k * 0.1)
            foot = _px(ground) + rng.normal(0, noise, 2)
            head = _px(ground, lift=1.0) + rng.normal(0, noise, 2)
            out.append(
                VerticalObservation(
                    observation_id=f"t{t}-{k}",
                    shot_id="s0",
                    frame_index=t * 100 + k,
                    video_time_s=k * 2.0,
                    canonical_track_id=f"s0/person-{t}",
                    track_id=t,
                    head_reference=Point2(x=float(head[0]), y=float(head[1]), space=REF),
                    foot_reference=Point2(x=float(foot[0]), y=float(foot[1]), space=REF),
                    head_confidence=0.9,
                    foot_confidence=0.9,
                    standing_probability=0.95,
                    occlusion_fraction=0.05,
                    covariance_4x4=((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
                )
            )
    return out


def _fast_uncertainty():  # noqa: ANN202
    return CONFIG.uncertainty.model_copy(
        update={"bootstrap_samples": 60, "minimum_successful_samples": 40}
    )


def test_fit_recovers_camera_from_synthetic_workers() -> None:
    ensemble = fit_plane(_observations(), FRAME, CONFIG.relative_plane, _fast_uncertainty())
    plane = ensemble.plane
    assert plane.focal_px == pytest.approx(TRUE.focal_px, rel=0.10)
    assert plane.pitch_deg == pytest.approx(28.0, abs=3.0)
    assert plane.camera_height_wh == pytest.approx(TRUE.height_wh, rel=0.12)
    assert plane.inlier_ratio >= 0.95
    assert plane.bootstrap_successes >= 40


def test_fit_rejects_too_little_evidence() -> None:
    with pytest.raises(PlaneFitError) as few_pairs:
        fit_plane(
            _observations(tracks=8, per_track=1), FRAME, CONFIG.relative_plane, _fast_uncertainty()
        )
    assert few_pairs.value.reason == "insufficient_vertical_observations"
    with pytest.raises(PlaneFitError) as few_tracks:
        fit_plane(
            _observations(tracks=3, per_track=8), FRAME, CONFIG.relative_plane, _fast_uncertainty()
        )
    assert few_tracks.value.reason == "insufficient_distinct_tracks"


def test_fit_rejects_inconsistent_heads_as_unstable() -> None:
    rng = np.random.default_rng(3)
    scrambled = [
        o.model_copy(
            update={
                "head_reference": Point2(
                    x=o.foot_reference.x + float(rng.normal(0, 40)),
                    y=o.foot_reference.y - float(rng.uniform(5, 400)),
                    space=REF,
                )
            }
        )
        for o in _observations()
    ]
    with pytest.raises(PlaneFitError) as caught:
        fit_plane(scrambled, FRAME, CONFIG.relative_plane, _fast_uncertainty())
    assert caught.value.feed_unstable


# --- distances --------------------------------------------------------------


def _ensemble(spread: float = 0.01, count: int = 500) -> PlaneEnsemble:
    rng = np.random.default_rng(5)
    plane = GroundPlane(
        plane_id="plane-1",
        focal_px=TRUE.focal_px,
        focal_width_ratio=TRUE.focal_px / FRAME.width,
        pitch_deg=28.0,
        camera_height_wh=TRUE.height_wh,
        principal_point=(FRAME.cx, FRAME.cy),
        horizon_y=0.0,
        support_polygon_wh=((-40.0, 1.0), (40.0, 1.0), (40.0, 80.0), (-40.0, 80.0)),
        observation_count=60,
        track_count=8,
        inlier_ratio=0.95,
        reprojection_rms_px=1.0,
        condition_number=1e3,
        bootstrap_successes=count,
        bootstrap_total=count,
    )
    return PlaneEnsemble(
        plane=plane,
        frame=FRAME,
        base=TRUE,
        focal=TRUE.focal_px * (1 + rng.normal(0, spread, count)),
        pitch=TRUE.pitch_rad * (1 + rng.normal(0, spread, count)),
        height=TRUE.height_wh * (1 + rng.normal(0, spread, count)),
    )


def test_point_to_polyline_handles_points_and_segments() -> None:
    assert point_to_polyline(np.array([0.0, 3.0]), np.array([[0.0, 0.0]])) == pytest.approx(3.0)
    segment = np.array([[0.0, 0.0], [10.0, 0.0]])
    assert point_to_polyline(np.array([4.0, 2.0]), segment) == pytest.approx(2.0)
    assert point_to_polyline(np.array([13.0, 4.0]), segment) == pytest.approx(5.0)


def test_distance_interval_brackets_the_true_distance() -> None:
    worker = _px((0.0, 8.0))
    target = np.array([_px((2.0, 8.0)), _px((2.0, 12.0))])
    interval = distance_interval(
        _ensemble(),
        worker,
        target,
        worker_sigma_px=1.0,
        target_sigma_px=1.0,
        inflation_wh=0.5,
        uncertainty=CONFIG.uncertainty,
        rng=np.random.default_rng(0),
    )
    assert interval is not None
    assert interval.lower_wh <= 1.5 <= interval.upper_wh
    assert interval.successful_bootstraps >= CONFIG.uncertainty.minimum_successful_samples


def test_wider_uncertainty_widens_the_interval() -> None:
    kwargs = {
        "worker_px": _px((0.0, 8.0)),
        "target_px": np.array([_px((3.0, 8.0))]),
        "worker_sigma_px": 1.0,
        "target_sigma_px": 1.0,
        "inflation_wh": 0.0,
        "uncertainty": CONFIG.uncertainty,
    }
    tight = distance_interval(_ensemble(0.005), rng=np.random.default_rng(1), **kwargs)  # type: ignore[arg-type]
    loose = distance_interval(_ensemble(0.08), rng=np.random.default_rng(1), **kwargs)  # type: ignore[arg-type]
    assert tight is not None and loose is not None
    assert loose.upper_wh - loose.lower_wh > tight.upper_wh - tight.lower_wh


def _interval(lower: float, median: float, upper: float) -> DistanceInterval:
    return DistanceInterval(lower_wh=lower, median_wh=median, upper_wh=upper)


@pytest.mark.parametrize(
    ("interval", "band"),
    [
        (_interval(0.2, 0.8, 1.4), DistanceBand.NEAR),
        (_interval(1.6, 2.0, 2.9), DistanceBand.CAUTION),
        (_interval(3.1, 4.0, 5.0), DistanceBand.CLEAR),
        (_interval(0.9, 1.6, 2.2), DistanceBand.INDETERMINATE),
        (_interval(1.6, 2.5, 3.5), DistanceBand.INDETERMINATE),
        (None, DistanceBand.INDETERMINATE),
    ],
)
def test_band_uses_the_whole_interval(
    interval: DistanceInterval | None, band: DistanceBand
) -> None:
    assert classify_band(interval, 1.5, 3.0) is band


# --- pose keypoints ---------------------------------------------------------


def _skeleton(crouch: bool = False) -> tuple[np.ndarray, np.ndarray]:
    xy = np.zeros((17, 2))
    conf = np.full(17, 0.9)
    xy[0] = (100, 20)
    xy[1], xy[2] = (95, 16), (105, 16)
    xy[3], xy[4] = (88, 18), (112, 18)
    xy[5], xy[6] = (80, 45), (120, 45)
    xy[11], xy[12] = (88, 100), (112, 100)
    ankle_y = 130 if crouch else 190
    xy[15], xy[16] = (90, ankle_y), (110, ankle_y)
    if crouch:
        xy[11], xy[12] = (88, 112), (112, 112)
    return xy, conf


def _track_obs(frame: int = 0, t: float = 0.0, box: tuple[float, ...] = (50, 10, 150, 200)):  # noqa: ANN202
    return Pass1TrackObservation(
        shot_id="s0",
        frame_index=frame,
        video_time_s=t,
        track_id=1,
        canonical_track_id="s0/person-1",
        object_class="person",
        box_reference=Box2(x1=box[0], y1=box[1], x2=box[2], y2=box[3], space=REF),
        anchor_reference=Point2(x=(box[0] + box[2]) / 2, y=box[3], space=REF),
    )


def test_keypoints_give_crown_above_head_and_sole_below_ankle() -> None:
    xy, conf = _skeleton()
    vertical = vertical_from_keypoints(
        xy,
        conf,
        _track_obs(),
        confidence_floor=0.6,
        head_sigma_fraction=0.03,
        foot_sigma_fraction=0.015,
    )
    assert vertical is not None
    assert vertical.head_reference.y < 16
    assert vertical.foot_reference.y > 190
    assert vertical.standing_probability >= 0.8


def test_crouching_worker_is_not_standing() -> None:
    xy, _ = _skeleton(crouch=True)
    probability = standing_probability(
        (xy[5] + xy[6]) / 2, (xy[11] + xy[12]) / 2, (xy[15] + xy[16]) / 2
    )
    assert probability < 0.8


def test_missing_ankles_reject_the_observation() -> None:
    xy, conf = _skeleton()
    conf[15] = conf[16] = 0.2
    assert (
        vertical_from_keypoints(
            xy,
            conf,
            _track_obs(),
            confidence_floor=0.6,
            head_sigma_fraction=0.03,
            foot_sigma_fraction=0.015,
        )
        is None
    )


def test_candidates_are_upright_spaced_and_capped() -> None:
    upright = [_track_obs(i, i * 0.1) for i in range(100)]
    squat = [_track_obs(500 + i, i * 0.1, (50, 100, 250, 200)) for i in range(10)]
    clipped = [_track_obs(700 + i, i * 0.1, (50, 0, 150, 200)) for i in range(10)]
    picked = select_candidates(
        [*upright, *squat, *clipped],
        CONFIG.pose,
        CONFIG.relative_plane,
        canvas_width=1920,
        canvas_height=1080,
    )
    times = sorted(o.video_time_s for o in picked)
    assert all(
        b - a >= CONFIG.pose.sample_spacing_seconds - 1e-9
        for a, b in zip(times, times[1:], strict=False)
    )
    assert {o.frame_index for o in picked} <= {o.frame_index for o in upright}
    assert len(picked) <= CONFIG.pose.maximum_samples_per_track


# --- camera motion ----------------------------------------------------------


def test_camera_shift_detects_a_panning_feed() -> None:
    rng = np.random.default_rng(0)
    base = cv_blur(rng.integers(0, 255, (270, 480), dtype=np.uint8))
    still = {0: base, 1: base.copy(), 2: base.copy()}
    panned = {0: base, 1: np.roll(base, 12, axis=1), 2: np.roll(base, 20, axis=1)}
    assert estimate_camera_shift(still, scale_to_reference=4.0) < 1.0
    assert estimate_camera_shift(panned, scale_to_reference=4.0) > 40.0


def cv_blur(image: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(image, (0, 0), 3)


# --- machinery state --------------------------------------------------------


def _vehicle(frame: int, t: float, ground: tuple[float, float]) -> Pass1TrackObservation:
    left, right = _px((ground[0] - 0.8, ground[1])), _px((ground[0] + 0.8, ground[1]))
    return Pass1TrackObservation(
        shot_id="s0",
        frame_index=frame,
        video_time_s=t,
        track_id=50,
        canonical_track_id="s0/vehicle-50",
        object_class="vehicle",
        box_reference=Box2(
            x1=float(left[0]),
            y1=float(left[1]) - 120,
            x2=float(right[0]),
            y2=float(left[1]),
            space=REF,
        ),
        anchor_reference=Point2(x=float((left[0] + right[0]) / 2), y=float(left[1]), space=REF),
    )


def _worker(frame: int, t: float, ground: tuple[float, float]) -> Pass1TrackObservation:
    foot, head = _px(ground), _px(ground, lift=1.0)
    return Pass1TrackObservation(
        shot_id="s0",
        frame_index=frame,
        video_time_s=t,
        track_id=1,
        canonical_track_id="s0/person-1",
        object_class="person",
        box_reference=Box2(
            x1=float(foot[0]) - 20,
            y1=float(head[1]),
            x2=float(foot[0]) + 20,
            y2=float(foot[1]),
            space=REF,
        ),
        anchor_reference=Point2(x=float(foot[0]), y=float(foot[1]), space=REF),
    )


def _moving_vehicle(speed: float, seconds: float = 4.0) -> list[Pass1TrackObservation]:
    return [
        _vehicle(i, i * 0.1, (3.0, 10.0 + speed * i * 0.1)) for i in range(int(seconds * 10) + 1)
    ]


def test_moving_machine_is_active_and_idle_machine_stays_unknown() -> None:
    ensemble = _ensemble()
    moving = operating_states(_moving_vehicle(0.4), ensemble, CONFIG.rules)
    idle = operating_states(_moving_vehicle(0.0), ensemble, CONFIG.rules)
    assert moving[30] is OperatingState.ACTIVE
    # No articulation measure, so a machine that is not translating is never called stationary.
    assert set(idle.values()) == {OperatingState.UNKNOWN}


def test_contact_visibility_requires_the_box_bottom_inside_the_image() -> None:
    vehicle = _vehicle(0, 0.0, (3.0, 10.0))
    assert contact_visible(vehicle, content_bottom=1080.0)
    assert not contact_visible(vehicle, content_bottom=vehicle.box_reference.y2 + 1.0)


# --- R4 ---------------------------------------------------------------------


def _context(
    ensemble: PlaneEnsemble | None = None, *, unstable: bool = False, ok: bool = True
) -> GeometryContext:
    ensemble = ensemble or _ensemble()
    if unstable:
        model = GeometryModel(
            status="unavailable", status_reason="camera_motion_detected", feed_unstable=True
        )
        ensemble = None
    elif not ok:
        model = GeometryModel(status="unavailable", status_reason="insufficient_distinct_tracks")
        ensemble = None
    else:
        model = GeometryModel(status="ok", plane=ensemble.plane if ensemble else None)
    return GeometryContext(
        geometry=model,
        ensemble=ensemble,
        uncertainty=CONFIG.uncertainty,
        content_bottom=1080.0,
        image_diagonal_px=math.hypot(1920, 1080),
    )


def _r4(context: GeometryContext | None, workers, vehicles):  # noqa: ANN001, ANN202
    return evaluate_r4(
        run_id="r",
        shot_id="s0",
        catalogue_sha256="c",
        context=context,
        person_tracks=workers,
        vehicle_tracks=vehicles,
        config=CONFIG.rules,
    )


def _beside(offset: float, seconds: float = 4.0, speed: float = 0.4):  # noqa: ANN202
    n = int(seconds * 10) + 1
    workers = {
        "s0/person-1": [
            _worker(i, i * 0.1, (3.0 - offset, 10.0 + speed * i * 0.1)) for i in range(n)
        ]
    }
    vehicles = {"s0/vehicle-50": _moving_vehicle(speed, seconds)}
    return workers, vehicles


def test_r4_alerts_for_worker_beside_moving_machine() -> None:
    workers, vehicles = _beside(offset=1.4)
    incidents, coverage = _r4(_context(), workers, vehicles)
    assert coverage.status == RuleStatus.EVALUATED_ALERT
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.relative_band is DistanceBand.NEAR
    assert incident.distance is not None and incident.distance.upper_wh <= 1.5
    assert incident.object_id == "s0/vehicle-50"


def test_r4_clear_when_worker_is_far() -> None:
    workers, vehicles = _beside(offset=9.0)
    incidents, coverage = _r4(_context(), workers, vehicles)
    assert incidents == [] and coverage.status == RuleStatus.EVALUATED_CLEAR


def test_r4_is_inconclusive_when_machine_state_is_unknown() -> None:
    workers, vehicles = _beside(offset=1.4, speed=0.0)
    incidents, coverage = _r4(_context(), workers, vehicles)
    assert incidents == []
    assert coverage.status == RuleStatus.INCONCLUSIVE
    assert coverage.reason_code == "operating_state_unknown"


def test_r4_degrades_without_a_plane() -> None:
    workers, vehicles = _beside(offset=1.4)
    assert _r4(_context(unstable=True), workers, vehicles)[1].status == RuleStatus.UNSUPPORTED
    assert (
        _r4(_context(unstable=True), workers, vehicles)[1].reason_code
        == "geometry_unstable_for_feed"
    )
    unavailable = _r4(_context(ok=False), workers, vehicles)[1]
    assert unavailable.status == RuleStatus.INCONCLUSIVE
    assert unavailable.reason_code == "relative_plane_unavailable"
    assert _r4(None, workers, vehicles)[1].reason_code == "relative_plane_unavailable"
    assert _r4(_context(), workers, {})[1].status == RuleStatus.NOT_APPLICABLE
    later = {"s0/person-1": [_worker(900, 90.0, (0.0, 10.0))]}
    assert _r4(_context(), later, vehicles)[1].reason_code == "no_worker_machinery_overlap"


def test_r4_target_outside_the_plane_support_is_incompatible() -> None:
    ensemble = _ensemble()
    small = ensemble.plane.model_copy(
        update={"support_polygon_wh": ((-1.0, 1.0), (1.0, 1.0), (1.0, 2.0), (-1.0, 2.0))}
    )
    workers, vehicles = _beside(offset=1.4)
    context = _context(
        PlaneEnsemble(small, FRAME, TRUE, ensemble.focal, ensemble.pitch, ensemble.height)
    )
    _, coverage = _r4(context, workers, vehicles)
    assert coverage.reason_code == "target_plane_incompatible"


# --- R5 ---------------------------------------------------------------------


def _edge(**fields: object) -> SceneProposal:
    left, right = _px((-2.0, 11.0)), _px((6.0, 11.0))
    base: dict[str, object] = {
        "proposal_id": "open_edge-1",
        "proposal_type": "open_edge",
        "geometry_type": "polyline",
        "points": ((float(left[0]), float(left[1])), (float(right[0]), float(right[1]))),
        "visible_drop_or_open_side": True,
        "protection_visibility": "sufficient",
        "protection_state": "unguarded_or_inadequate",
        "source": "gemini_consensus",
        "agreement_score": 0.9,
        "supporting_keyframes": (0, 1, 2, 3, 4, 5, 6),
        "eligible_keyframes": 8,
    }
    return SceneProposal(**{**base, **fields})  # type: ignore[arg-type]


def _r5(context: GeometryContext | None, scene: SceneModel | None, worker_z: float = 10.85):  # noqa: ANN202
    workers = {"s0/person-1": [_worker(i, i * 0.1, (2.0, worker_z)) for i in range(41)]}
    return evaluate_r5(
        run_id="r",
        shot_id="s0",
        catalogue_sha256="c",
        context=context,
        scene=scene,
        person_tracks=workers,
        config=CONFIG.rules,
    )


def _scene(*edges: SceneProposal) -> SceneModel:
    return SceneModel(cache_key="k", status="ok", proposals=edges)


def test_r5_alerts_for_worker_at_visibly_unguarded_edge() -> None:
    incidents, coverage = _r5(_context(), _scene(_edge()))
    assert coverage.status == RuleStatus.EVALUATED_ALERT
    assert len(incidents) == 1
    assert incidents[0].proposal_ids == ("open_edge-1",)
    assert incidents[0].distance is not None and incidents[0].distance.upper_wh <= 0.8


def test_r5_clear_when_worker_is_far_from_edge() -> None:
    incidents, coverage = _r5(_context(), _scene(_edge()), worker_z=6.0)
    assert incidents == [] and coverage.status == RuleStatus.EVALUATED_CLEAR


def test_r5_never_alerts_without_positive_edge_semantics() -> None:
    cases = [
        (_edge(visible_drop_or_open_side=None), "edge_semantics_unknown"),
        (_edge(protection_visibility="insufficient"), "protection_visibility_insufficient"),
        (_edge(protection_state="unknown"), "protection_state_unknown"),
    ]
    for edge, reason in cases:
        incidents, coverage = _r5(_context(), _scene(edge))
        assert incidents == []
        assert coverage.status == RuleStatus.INCONCLUSIVE and coverage.reason_code == reason


def test_r5_guarded_edge_is_clear_and_scene_gaps_are_explicit() -> None:
    assert (
        _r5(_context(), _scene(_edge(protection_state="guarded")))[1].status
        == RuleStatus.EVALUATED_CLEAR
    )
    assert _r5(_context(), _scene())[1].reason_code == "no_visible_open_edge_candidate"
    assert _r5(_context(), None)[1].reason_code == "scene_state_unavailable"
    assert _r5(_context(unstable=True), _scene(_edge()))[1].status == RuleStatus.UNSUPPORTED
    assert _r5(_context(ok=False), _scene(_edge()))[1].reason_code == "relative_plane_unavailable"
