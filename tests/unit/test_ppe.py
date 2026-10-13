"""PPE label association and temporal smoothing (the model itself is tested by training)."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.data.ppe_crops import IGNORE, Box, HeadLabel, TorsoLabel, associate
from shared.config import load_config
from shared.coordinates import Box2
from shared.enums import CoordinateSpace, HelmetState, VestState

ppe_temporal = pytest.importorskip("pipeline.vision.ppe_temporal")  # needs torch
PPEPrediction = pytest.importorskip("pipeline.vision.ppe_model").PPEPrediction

WORKER_A = Box(100, 100, 160, 300)
WORKER_B = Box(300, 100, 360, 300)


def test_ppe_boxes_go_to_the_right_body_region() -> None:
    labels = associate(
        persons=[WORKER_A, WORKER_B],
        helmets=[Box(115, 100, 145, 125)],  # on A's head
        no_helmets=[Box(315, 100, 345, 125)],  # on B's head
        vests=[Box(105, 150, 155, 220)],  # on A's torso
        no_vests=[],
    )
    assert (labels[0].head, labels[0].torso) == (HeadLabel.HELMET, TorsoLabel.VEST)
    assert (labels[1].head, labels[1].torso) == (HeadLabel.NO_HELMET, IGNORE)


def test_missing_annotation_is_ignored_not_negative() -> None:
    [label] = associate([WORKER_A], [], [], [], [])
    assert (label.head, label.torso) == (IGNORE, IGNORE)


def test_item_in_the_wrong_region_is_not_assigned() -> None:
    boots_height_helmet = Box(115, 270, 145, 295)  # a "helmet" at foot level
    [label] = associate([WORKER_A], [boots_height_helmet], [], [], [])
    assert label.head == IGNORE


def test_conflicting_evidence_is_ignored() -> None:
    [label] = associate([WORKER_A], [Box(115, 100, 145, 125)], [Box(118, 102, 142, 124)], [], [])
    assert label.head == IGNORE


def test_nested_people_take_the_smallest_containing_box() -> None:
    child = Box(110, 110, 150, 290)
    labels = associate([WORKER_A, child], [Box(120, 112, 140, 130)], [], [], [])
    assert labels[1].head == HeadLabel.HELMET and labels[0].head == IGNORE


def test_padding_follows_v7_and_stays_inside_the_image() -> None:
    padded = Box(10, 10, 110, 210).padded(width=115, height=500)
    assert (padded.x1, padded.y1) == (0.0, 0.0)
    assert padded.x2 == 115.0  # clipped at the image edge
    assert padded.y2 == pytest.approx(216.0)


def _prediction(head: tuple[float, float, float], torso=(0.9, 0.05, 0.05)):
    return PPEPrediction(np.array(head), np.array(torso))


def _filter():
    return ppe_temporal.TemporalPPEFilter(alpha=0.35, minimum_observations=4, confidence_floor=0.70)


def test_state_needs_minimum_observations() -> None:
    smoother = _filter()
    states = [smoother.update("t1", _prediction((0.05, 0.9, 0.05)))[0] for _ in range(4)]
    assert [s.state for s in states[:3]] == [HelmetState.UNKNOWN] * 3
    assert states[3].state is HelmetState.NO_HELMET
    assert states[3].confidence == pytest.approx(0.947, abs=0.01)


def test_unknown_predictions_never_vote() -> None:
    smoother = _filter()
    for _ in range(4):
        smoother.update("t1", _prediction((0.9, 0.05, 0.05)))
    helmet, _ = smoother.update("t1", _prediction((0.02, 0.18, 0.80)))
    assert helmet.state is HelmetState.HELMET  # history kept …
    assert helmet.visible is False  # … but this frame is flagged not assessable


def test_flicker_is_smoothed_but_persistent_change_wins() -> None:
    smoother = _filter()
    for _ in range(6):
        smoother.update("t1", _prediction((0.95, 0.03, 0.02)))
    blip, _ = smoother.update("t1", _prediction((0.1, 0.88, 0.02)))
    # One contrary frame may create doubt (unknown) but never flips to a violation.
    assert blip.state is not HelmetState.NO_HELMET
    for _ in range(6):
        latest, _ = smoother.update("t1", _prediction((0.05, 0.93, 0.02)))
    assert latest.state is HelmetState.NO_HELMET


def test_low_confidence_mix_stays_unknown() -> None:
    smoother = _filter()
    for index in range(8):
        head = (0.55, 0.40, 0.05) if index % 2 else (0.40, 0.55, 0.05)
        helmet, vest = smoother.update("t1", _prediction(head))
    assert helmet.state is HelmetState.UNKNOWN
    assert vest.state is VestState.VEST


def test_tracks_are_independent_and_reset_clears() -> None:
    smoother = _filter()
    for _ in range(4):
        smoother.update("a", _prediction((0.05, 0.9, 0.05)))
    assert smoother.update("b", _prediction((0.05, 0.9, 0.05)))[0].state is HelmetState.UNKNOWN
    smoother.reset()
    assert smoother.update("a", _prediction((0.05, 0.9, 0.05)))[0].state is HelmetState.UNKNOWN


class _CountingClassifier:
    def __init__(self, head: tuple[float, float, float]) -> None:
        self.head = head
        self.crop_shapes: list[tuple[int, ...]] = []

    def predict(self, crops):
        self.crop_shapes += [crop.shape for crop in crops]
        return [_prediction(self.head) for _ in crops]


def _stage(classifier: _CountingClassifier, *, every: int = 2):
    PPEStage = pytest.importorskip("pipeline.vision.ppe_stage").PPEStage
    return PPEStage(
        classifier,
        alpha=0.35,
        minimum_observations=2,
        confidence_floor=0.70,
        minimum_height_px=40,
        minimum_upright_aspect=1.6,
        classify_every_frames=every,
    )


def _box(x1: float, y1: float, x2: float, y2: float) -> Box2:
    return Box2(x1=x1, y1=y1, x2=x2, y2=y2, space=CoordinateSpace.REFERENCE)


FRAME = np.zeros((480, 640, 3), np.uint8)
UPRIGHT = _box(100, 100, 160, 300)


def test_stage_classifies_every_nth_frame_and_carries_state_between() -> None:
    classifier = _CountingClassifier((0.05, 0.9, 0.05))
    stage = _stage(classifier, every=2)
    states = [stage.assess(FRAME, [("w", UPRIGHT)])["w"][0].state for _ in range(6)]
    assert len(classifier.crop_shapes) == 3  # frames 0, 2, 4
    # Two accepted observations (frames 0 and 2) before a verdict; frame 3 carries it.
    assert states[:2] == [HelmetState.UNKNOWN, HelmetState.UNKNOWN]
    assert states[2:] == [HelmetState.NO_HELMET] * 4


def test_stage_crops_with_training_padding() -> None:
    classifier = _CountingClassifier((0.9, 0.05, 0.05))
    _stage(classifier).assess(FRAME, [("w", UPRIGHT)])
    # 60x200 box padded 10% each side, 5% top, 3% bottom → 72x216.
    assert classifier.crop_shapes == [(216, 72, 3)]


@pytest.mark.parametrize(
    "box",
    [_box(100, 100, 160, 130), _box(100, 100, 260, 260)],  # too short, crouching
    ids=["too-short", "not-upright"],
)
def test_stage_skips_unassessable_people(box: Box2) -> None:
    classifier = _CountingClassifier((0.05, 0.9, 0.05))
    helmet, vest = _stage(classifier).assess(FRAME, [("w", box)])["w"]
    assert classifier.crop_shapes == []
    assert (helmet.state, helmet.visible) == (HelmetState.UNKNOWN, False)
    assert vest.state is VestState.UNKNOWN


def test_stage_hides_stale_verdict_when_view_turns_unknown() -> None:
    classifier = _CountingClassifier((0.05, 0.9, 0.05))
    stage = _stage(classifier, every=1)
    for _ in range(3):
        stage.assess(FRAME, [("w", UPRIGHT)])
    classifier.head = (0.05, 0.05, 0.9)  # head turned away / occluded
    helmet, _ = stage.assess(FRAME, [("w", UPRIGHT)])["w"]
    assert (helmet.state, helmet.visible) == (HelmetState.UNKNOWN, False)


def test_stage_without_weights_is_none(tmp_path) -> None:
    PPEStage = pytest.importorskip("pipeline.vision.ppe_stage").PPEStage
    config = load_config().ppe.model_copy(update={"model_path": tmp_path / "missing.pt"})
    assert PPEStage.from_config(config, "cpu") is None
