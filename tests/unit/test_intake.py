from __future__ import annotations

import numpy as np
import pytest

from pipeline.intake import FrameSampler


class MockCapture:
    """Minimal cv2.VideoCapture stand-in that yields synthetic frames."""

    def __init__(self, frame_count: int = 60, fps: float = 30.0) -> None:
        self._frames_left = frame_count
        self._fps = fps
        self._index = 0
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def get(self, prop_id: int) -> float:
        # cv2.CAP_PROP_FPS == 5
        return self._fps

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._frames_left <= 0:
            return False, None
        self._frames_left -= 1
        self._index += 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        return True, frame

    def release(self) -> None:
        self._opened = False


def test_frame_sampler_yields_correct_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """FrameSampler at 15 fps from 30 fps source should yield every other frame."""
    mock = MockCapture(frame_count=60, fps=30.0)
    monkeypatch.setattr("cv2.VideoCapture", lambda *_a, **_k: mock)

    from pathlib import Path

    sampler = FrameSampler(Path("fake.mp4"), target_fps=15.0, target_width=640, target_height=480)
    frames = list(sampler)
    # 60 native frames / step=2 → 30 samples
    assert len(frames) == 30
    for idx, (si, _ts, frame) in enumerate(frames):
        assert si == idx
        assert frame.shape == (480, 640, 3)


def test_frame_sampler_letterbox_pads_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Letterbox should pad a 4:3 source into a 16:9 canvas with black bars."""
    mock = MockCapture(frame_count=1, fps=15.0)
    monkeypatch.setattr("cv2.VideoCapture", lambda *_a, **_k: mock)

    from pathlib import Path

    sampler = FrameSampler(Path("fake.mp4"), target_fps=15.0, target_width=1920, target_height=1080)
    frames = list(sampler)
    assert len(frames) == 1
    _, _, frame = frames[0]
    assert frame.shape == (1080, 1920, 3)
