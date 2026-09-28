from __future__ import annotations

from pipeline.rules.engine import evaluate_real_rules
from shared.config import load_config
from shared.coordinates import Box2, Point2
from shared.enums import (
    CoordinateSpace,
    HelmetState,
    RuleId,
    RuleStatus,
    VestState,
)
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation, VestRecord


def _make_obs(
    *,
    shot_id: str,
    track_id: int,
    canonical: str,
    object_class: str,
    frame_index: int,
    video_time_s: float,
    helmet_state: HelmetState | None = None,
    vest_state: VestState | None = None,
) -> Pass1TrackObservation:
    box = Box2(x1=10.0, y1=10.0, x2=80.0, y2=180.0, space=CoordinateSpace.REFERENCE)
    anchor = Point2(x=45.0, y=180.0, space=CoordinateSpace.REFERENCE)
    return Pass1TrackObservation(
        shot_id=shot_id,
        frame_index=frame_index,
        video_time_s=video_time_s,
        track_id=track_id,
        canonical_track_id=canonical,
        object_class=object_class,
        box_reference=box,
        anchor_reference=anchor,
        helmet=HelmetRecord(state=helmet_state, confidence=0.9, visible=True)
        if helmet_state is not None
        else None,
        vest=VestRecord(state=vest_state, confidence=0.88, visible=True)
        if vest_state is not None
        else None,
    )


CONFIG = load_config().rules


def test_r1_fires_when_no_helmet_above_debounce() -> None:
    obs = [
        _make_obs(
            shot_id="s0",
            track_id=1,
            canonical="s0/person-1",
            object_class="person",
            frame_index=i,
            video_time_s=i * 0.1,
            helmet_state=HelmetState.NO_HELMET,
            vest_state=VestState.VEST,
        )
        for i in range(20)  # 2 seconds → above 1.5s debounce
    ]
    coverage, incidents, _ = evaluate_real_rules(
        run_id="test-run",
        shot_id="s0",
        observations=obs,
        catalogue_sha256="abc123",
        config=CONFIG,
    )
    r1_cov = next(c for c in coverage if c.rule_id == RuleId.R1)
    assert r1_cov.status == RuleStatus.EVALUATED_ALERT
    assert len(incidents) == 1
    assert incidents[0].rule_id == RuleId.R1


def test_r1_clear_when_all_wearing_helmet() -> None:
    obs = [
        _make_obs(
            shot_id="s0",
            track_id=1,
            canonical="s0/person-1",
            object_class="person",
            frame_index=i,
            video_time_s=float(i),
            helmet_state=HelmetState.HELMET,
            vest_state=VestState.VEST,
        )
        for i in range(5)
    ]
    coverage, incidents, _ = evaluate_real_rules(
        run_id="test-run",
        shot_id="s0",
        observations=obs,
        catalogue_sha256="abc",
        config=CONFIG,
    )
    r1_cov = next(c for c in coverage if c.rule_id == RuleId.R1)
    assert r1_cov.status == RuleStatus.EVALUATED_CLEAR
    assert len(incidents) == 0


def test_r1_inconclusive_when_below_debounce() -> None:
    obs = [
        _make_obs(
            shot_id="s0",
            track_id=1,
            canonical="s0/person-1",
            object_class="person",
            frame_index=0,
            video_time_s=0.0,
            helmet_state=HelmetState.NO_HELMET,
            vest_state=VestState.VEST,
        )
    ]
    coverage, incidents, _ = evaluate_real_rules(
        run_id="test-run",
        shot_id="s0",
        observations=obs,
        catalogue_sha256="abc",
        config=CONFIG,
    )
    r1_cov = next(c for c in coverage if c.rule_id == RuleId.R1)
    assert r1_cov.status == RuleStatus.INCONCLUSIVE
    assert len(incidents) == 0


def test_r2_fires_when_no_vest_near_vehicle() -> None:
    vehicle_obs = [
        _make_obs(
            shot_id="s0",
            track_id=10,
            canonical="s0/vehicle-10",
            object_class="vehicle",
            frame_index=i,
            video_time_s=float(i),
        )
        for i in range(5)
    ]
    person_obs = [
        _make_obs(
            shot_id="s0",
            track_id=1,
            canonical="s0/person-1",
            object_class="person",
            frame_index=i,
            video_time_s=float(i),
            helmet_state=HelmetState.HELMET,
            vest_state=VestState.NO_VEST,
        )
        for i in range(5)
    ]
    coverage, incidents, _ = evaluate_real_rules(
        run_id="test-run",
        shot_id="s0",
        observations=[*vehicle_obs, *person_obs],
        catalogue_sha256="abc",
        config=CONFIG,
    )
    r2_cov = next(c for c in coverage if c.rule_id == RuleId.R2)
    assert r2_cov.status == RuleStatus.EVALUATED_ALERT
    assert any(i.rule_id == RuleId.R2 for i in incidents)


def test_no_person_tracks_gives_inconclusive_r1() -> None:
    coverage, incidents, _ = evaluate_real_rules(
        run_id="test-run",
        shot_id="s0",
        observations=[],
        catalogue_sha256="abc",
        config=CONFIG,
    )
    r1_cov = next(c for c in coverage if c.rule_id == RuleId.R1)
    assert r1_cov.status == RuleStatus.INCONCLUSIVE
    assert len(incidents) == 0


def test_r3_r5_always_unsupported() -> None:
    coverage, _, _ = evaluate_real_rules(
        run_id="test-run",
        shot_id="s0",
        observations=[],
        catalogue_sha256="abc",
        config=CONFIG,
    )
    r3 = next(c for c in coverage if c.rule_id == RuleId.R3)
    r5 = next(c for c in coverage if c.rule_id == RuleId.R5)
    assert r3.status == RuleStatus.UNSUPPORTED
    assert r5.status == RuleStatus.UNSUPPORTED
