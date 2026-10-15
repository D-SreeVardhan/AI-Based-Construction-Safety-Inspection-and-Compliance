"""v3 leading indicators and decision traces recorded alongside the rule engine."""

from __future__ import annotations

import pytest
from rule_frames import (
    FPS,
    frame,
    helmet,
    interval,
    machine,
    proximity,
    rules_config,
    times,
    vest,
    worker,
)

from pipeline.rules.engine import RuleEngine
from pipeline.rules.insights import BRIEF_MINIMUM_S, evidence_quality, thin
from shared.enums import DistanceBand, HelmetState, OperatingState, RuleId, VestState
from shared.schemas.incidents import TracePoint

NO_HELMET = helmet(HelmetState.NO_HELMET, 0.9)
WITH_HELMET = helmet(HelmetState.HELMET, 0.95)
WITH_VEST = vest(VestState.VEST, 0.95)


def _run(contexts):
    engine = RuleEngine(run_id="run-test", config=rules_config())
    for context in contexts:
        engine.evaluate_frame(context)
    return engine.finalize()


def _helmet_frames(spans: list[tuple[float, float]], end_s: float = 10.0):
    contexts = []
    for t in times(0.0, end_s):
        missing = any(a <= t < b for a, b in spans)
        record = NO_HELMET if missing else WITH_HELMET
        contexts.append(frame(t, tracks=(worker(7, helmet_record=record, vest_record=WITH_VEST),)))
    return contexts


def _exposure(result, rule_id: RuleId):
    return next(e for e in result.insights.exposure if e.rule_id is rule_id)


def test_exposure_counts_every_held_second_confirmed_or_not() -> None:
    # 0.6 s lapse (below R1's 1.5 s debounce), then a 3 s one that becomes an incident.
    result = _run(_helmet_frames([(1.0, 1.6), (4.0, 7.0)]))
    r1 = _exposure(result, RuleId.R1)
    assert r1.confirmed_incidents == 1
    assert r1.brief_exposures == 1
    assert r1.workers_exposed == 1
    # 9 + 45 holding frames, each worth one frame interval (the first counts from its own start)
    assert r1.exposure_s == pytest.approx((9 - 1 + 45 - 1) / FPS + 2 / FPS, abs=0.15)
    [brief] = result.insights.brief_exposures
    assert brief.rule_id is RuleId.R1 and brief.start_s == pytest.approx(1.0)
    assert brief.end_s == pytest.approx(1.6 - 1 / FPS, abs=1e-3)
    assert result.insights.observed_s == pytest.approx(10.0 - 1 / FPS, abs=0.01)


def test_single_frame_flicker_is_not_a_brief_exposure() -> None:
    flicker = 1.0 / FPS
    assert flicker < BRIEF_MINIMUM_S
    result = _run(_helmet_frames([(2.0, 2.0 + flicker)]))
    assert result.insights.brief_exposures == ()
    assert _exposure(result, RuleId.R1).brief_exposures == 0


def test_closest_approach_is_kept_without_any_alert() -> None:
    contexts = []
    for index, t in enumerate(times(0.0, 2.0)):
        upper = 3.0 - 0.05 * index
        pair = proximity(
            3,
            "shot:s0/track:9",
            DistanceBand.CAUTION,
            OperatingState.ACTIVE,
            distance=interval(upper - 0.5, upper),
        )
        contexts.append(
            frame(
                t,
                tracks=(worker(3, helmet_record=WITH_HELMET, vest_record=WITH_VEST),),
                machinery=(machine("shot:s0/track:9", class_name="excavator"),),
                proximities=(pair,),
            )
        )
    result = _run(contexts)
    assert not [i for i in result.incidents if i.rule_id is RuleId.R4]
    [closest] = result.insights.closest_approaches
    assert closest.target_id == "shot:s0/track:9"
    assert closest.distance.upper_wh == pytest.approx(3.0 - 0.05 * 29)
    assert closest.time_s == pytest.approx(29 / FPS, abs=1e-3)


def test_incident_carries_a_trace_from_before_onset_to_after_resolution() -> None:
    result = _run(_helmet_frames([(4.0, 7.0)]))
    [incident] = result.incidents
    trace = incident.trace
    assert trace is not None and trace.metric == "confidence"
    assert trace.debounce_s == pytest.approx(1.5)
    assert trace.points[0].t <= 2.1  # 2 s of pre-roll before the 4.0 s onset
    assert trace.points[-1].t >= 8.9  # 2 s after the 7.0 s resolution
    states = [p.state for p in trace.points]
    assert "holds" in states and states[0] == "clear"
    assert trace.observed_fraction == 1.0
    assert incident.evidence_quality == "strong"


def test_evidence_quality_grades_visibility_confidence_and_duration() -> None:
    common = {"duration_s": 4.0, "debounce_s": 1.5, "confidence_floor": 0.7, "margin": 0.1}
    assert evidence_quality(observed_fraction=0.95, mean_confidence=0.9, **common) == "strong"
    assert evidence_quality(observed_fraction=0.95, mean_confidence=0.75, **common) == "weak"
    assert evidence_quality(observed_fraction=0.4, mean_confidence=None, **common) == "weak"
    assert evidence_quality(observed_fraction=0.7, mean_confidence=None, **common) == "moderate"
    short = {**common, "duration_s": 2.0}
    assert evidence_quality(observed_fraction=0.95, mean_confidence=0.9, **short) == "moderate"


def test_thinning_keeps_state_changes_and_the_last_point() -> None:
    points = [TracePoint(t=i / 15, state="clear") for i in range(15)]
    points[7] = TracePoint(t=7 / 15, state="holds")
    kept = thin(points)
    assert [p.t for p in kept if p.state == "holds"] == [7 / 15]
    assert kept[-1].t == points[-1].t
    assert len(kept) < len(points)
