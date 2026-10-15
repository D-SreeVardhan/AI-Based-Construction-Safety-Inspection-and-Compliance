"""v3 hazard rules: R6 worker down, R7 under a suspended load, R8 fire or smoke."""

from __future__ import annotations

import numpy as np
from rule_frames import frame, rules_config, times, worker

from pipeline.rules.engine import RuleEngine
from pipeline.rules.r6 import R6WorkerDown
from pipeline.rules.r7 import R7SuspendedLoad
from pipeline.rules.r8 import R8FireSmoke
from pipeline.vision.posture import decide, lying_from_keypoints, posture_from_box
from shared.coordinates import Box2
from shared.enums import CoordinateSpace, Posture, RuleId, RuleStatus
from shared.schemas.frame import FeedCapabilities, HazardObject

CAPS = FeedCapabilities(posture=True, hazard_classes=("suspended_load", "fire", "smoke"))


def _box(x1, y1, x2, y2) -> Box2:
    return Box2(x1=x1, y1=y1, x2=x2, y2=y2, space=CoordinateSpace.REFERENCE)


def _worker(local_id: int, *, posture: str | None = "upright", box=(100, 300, 140, 420)):
    return worker(local_id).model_copy(update={"posture": posture, "box_reference": _box(*box)})


def _hazard(object_id: str, cls: str, box, confidence: float = 0.8) -> HazardObject:
    return HazardObject(
        object_id=object_id, class_name=cls, box_reference=_box(*box), confidence=confidence
    )


# ---------------------------------------------------------------------- posture


def test_posture_from_box_and_pose() -> None:
    assert posture_from_box(40, 120) is Posture.UPRIGHT
    assert posture_from_box(80, 80) is Posture.CROUCHED  # bending over rebar
    assert posture_from_box(150, 50) is None  # lying candidate, needs a closer look
    assert decide(None, True, 0.3) is Posture.LYING
    assert decide(None, False, 0.3) is Posture.CROUCHED
    assert decide(None, None, 0.4) is Posture.LYING  # no pose model: only very flat boxes
    assert decide(None, None, 0.7) is Posture.CROUCHED


def test_lying_is_a_near_horizontal_body_axis() -> None:
    keypoints = np.zeros((17, 3))
    keypoints[[5, 6], :] = [[10, 50, 0.9], [12, 52, 0.9]]  # shoulders
    keypoints[[11, 12], :] = [[80, 58, 0.9], [82, 60, 0.9]]  # hips, same height: lying
    assert lying_from_keypoints(keypoints) is True
    keypoints[[11, 12], 1] = [140, 142]  # hips well below shoulders: bent or upright
    keypoints[[11, 12], 0] = [20, 22]
    assert lying_from_keypoints(keypoints) is False
    keypoints[:, 2] = 0.1
    assert lying_from_keypoints(keypoints) is None


# ---------------------------------------------------------------------- R6


def test_r6_alerts_only_on_lying_and_never_clears_on_unknown() -> None:
    rule = R6WorkerDown(basis="heuristic")
    context = frame(
        1.0,
        capabilities=CAPS,
        tracks=(
            _worker(1, posture="lying"),
            _worker(2, posture="crouched"),
            _worker(3, posture=None),
        ),
    )
    statuses = {r.track_id.split(":")[-1]: r.status for r in rule.evaluate(context)}
    assert statuses == {
        "1": RuleStatus.EVALUATED_ALERT,
        "2": RuleStatus.EVALUATED_CLEAR,
        "3": RuleStatus.INCONCLUSIVE,
    }
    unsupported = rule.evaluate(frame(1.0, tracks=(_worker(1, posture="lying"),)))
    assert unsupported[0].status is RuleStatus.UNSUPPORTED


def test_r6_needs_three_seconds_lying_to_become_an_incident() -> None:
    def run(lying_s: float):
        engine = RuleEngine(run_id="run-test", config=rules_config())
        for t in times(0.0, 8.0):
            posture = "lying" if 1.0 <= t < 1.0 + lying_s else "upright"
            engine.evaluate_frame(
                frame(t, capabilities=CAPS, tracks=(_worker(4, posture=posture),))
            )
        return [i for i in engine.finalize().incidents if i.rule_id is RuleId.R6]

    assert run(2.0) == []  # reaching down, not a worker down
    [incident] = run(5.0)
    assert incident.severity == "critical"
    assert "lying on the ground" in incident.observation_text


# ---------------------------------------------------------------------- R7


def test_r7_flags_workers_beneath_the_load_only() -> None:
    rule = R7SuspendedLoad(basis="heuristic", min_confidence=0.35)
    load = _hazard("shot:s0/track:90", "suspended_load", (400, 100, 480, 160))
    under = _worker(1, box=(420, 300, 460, 420))  # below, overlapping horizontally
    beside = _worker(2, box=(700, 300, 740, 420))  # far to the side
    above = _worker(3, box=(420, 20, 460, 90))  # higher in the frame than the load
    results = rule.evaluate(
        frame(1.0, capabilities=CAPS, tracks=(under, beside, above), hazards=(load,))
    )
    statuses = {r.track_id.split(":")[-1]: r.status for r in results}
    assert statuses["1"] is RuleStatus.EVALUATED_ALERT
    assert statuses["2"] is RuleStatus.EVALUATED_CLEAR
    assert statuses["3"] is RuleStatus.EVALUATED_CLEAR
    assert results[0].object_id == "shot:s0/track:90"


def test_r7_without_a_confident_load_is_not_applicable() -> None:
    rule = R7SuspendedLoad(basis="heuristic", min_confidence=0.35)
    weak = _hazard("shot:s0/track:90", "suspended_load", (400, 100, 480, 160), confidence=0.2)
    result = rule.evaluate(frame(1.0, capabilities=CAPS, tracks=(_worker(1),), hazards=(weak,)))
    assert [r.status for r in result] == [RuleStatus.NOT_APPLICABLE]
    no_class = rule.evaluate(frame(1.0, tracks=(_worker(1),), hazards=(weak,)))
    assert no_class[0].status is RuleStatus.UNSUPPORTED


# ---------------------------------------------------------------------- R8


def test_r8_one_incident_per_fire_not_per_worker() -> None:
    engine = RuleEngine(run_id="run-test", config=rules_config())
    for t in times(0.0, 6.0):
        hazards = (
            (_hazard("shot:s0/track:77", "smoke", (900, 200, 1100, 400), 0.7),)
            if 1.0 <= t < 5.0
            else ()
        )
        engine.evaluate_frame(
            frame(t, capabilities=CAPS, tracks=(_worker(1), _worker(2)), hazards=hazards)
        )
    [incident] = [i for i in engine.finalize().incidents if i.rule_id is RuleId.R8]
    assert incident.canonical_track_id == "shot:s0/track:77"
    assert incident.severity == "critical"


def test_r8_low_confidence_is_inconclusive_and_nothing_seen_is_clear() -> None:
    rule = R8FireSmoke(basis="visual", min_confidence=0.45)
    weak = rule.evaluate(
        frame(1.0, capabilities=CAPS, hazards=(_hazard("h", "fire", (1, 1, 50, 50), 0.3),))
    )
    assert weak[0].status is RuleStatus.INCONCLUSIVE
    clear = rule.evaluate(frame(1.0, capabilities=CAPS))
    assert clear[0].status is RuleStatus.EVALUATED_CLEAR
