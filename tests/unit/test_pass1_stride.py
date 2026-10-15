"""Pass one with a detector stride: keyframes detected, frames between interpolated."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ultralytics")

from pipeline.cache.pass1_store import Pass1Store  # noqa: E402
from pipeline.intake.frames import DecodedFrame  # noqa: E402
from pipeline.intake.geometry_gate import CameraMode  # noqa: E402
from pipeline.vision.detector import Detection  # noqa: E402
from pipeline.vision.pass1 import VisionPass, interpolate_tracks  # noqa: E402
from pipeline.vision.tracker import TrackedObject  # noqa: E402
from shared.config import load_config  # noqa: E402


def _box(index: int) -> Detection:
    """A worker walking right 10 px per frame."""
    return Detection(
        x1=100.0 + 10 * index,
        y1=200.0,
        x2=140.0 + 10 * index,
        y2=320.0,
        confidence=0.9,
        class_name="person",
    )


class FakeDetector:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def predict(self, images):
        out = []
        for image in images:
            index = int(image[0, 0, 0])  # the frame index is painted into the pixel
            self.seen.append(index)
            out.append([_box(index)])
        return out


class FakeTracker:
    def update(self, detections):
        return [TrackedObject(track_id=1, detection=d) for d in detections]

    def reset(self) -> None:
        pass


def _frames(count: int) -> list[DecodedFrame]:
    frames = []
    for index in range(count):
        image = np.full((90, 160, 3), 128, np.uint8)
        image[0, 0, 0] = index
        frames.append(
            DecodedFrame(frame_index=index, source_index=index, time_s=index / 15, image=image)
        )
    return frames


def test_detector_stride_interpolates_the_frames_between(tmp_path: Path) -> None:
    config = load_config()
    config = config.model_copy(
        update={"stage1": config.stage1.model_copy(update={"detect_every_frames": 2})}
    )
    detector = FakeDetector()
    store = Pass1Store(tmp_path / "pass1.sqlite")
    summary = VisionPass(detector, FakeTracker(), config, camera_mode=CameraMode.FIXED).run(
        _frames(9), store
    )
    assert detector.seen == [0, 2, 4, 6, 8]
    assert summary.frames == 9
    rows = {record.frame_index: obs for record, obs in store.frames_with_observations()}
    assert len(rows) == 9
    for index in range(9):
        [observation] = rows[index]
        assert observation.interpolated is (index % 2 == 1)
        # Linear motion: the interpolated box is exactly where the worker was.
        assert observation.box_reference.x1 == pytest.approx(100.0 + 10 * index)


def test_interpolation_only_bridges_tracks_seen_on_both_sides() -> None:
    a = [TrackedObject(1, _box(0)), TrackedObject(2, _box(0))]
    b = [TrackedObject(1, _box(2)), TrackedObject(3, _box(2))]
    [middle] = interpolate_tracks(a, b, 0.5)
    assert middle.track_id == 1
    assert middle.detection.x1 == pytest.approx(110.0)
