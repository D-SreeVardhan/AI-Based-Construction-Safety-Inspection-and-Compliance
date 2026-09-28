from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np


class FrameSampler:
    """Sample frames from a video at a target FPS using cv2.VideoCapture.

    Yields ``(sample_index, video_time_s, frame_bgr)`` at approximately
    *target_fps*, letterboxed to *target_width* × *target_height*.
    """

    def __init__(
        self,
        video_path: Path,
        *,
        target_fps: float = 15.0,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> None:
        self.video_path = video_path
        self.target_fps = target_fps
        self.target_width = target_width
        self.target_height = target_height

    @property
    def effective_fps(self) -> float:
        return self.target_fps

    def __iter__(self) -> Iterator[tuple[int, float, np.ndarray]]:
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")
        try:
            native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            step = max(1, round(native_fps / self.target_fps))
            native_index = 0
            sample_index = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if native_index % step == 0:
                    video_time_s = native_index / native_fps
                    yield sample_index, video_time_s, self._letterbox(frame)
                    sample_index += 1
                native_index += 1
        finally:
            cap.release()

    def _letterbox(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w == self.target_width and h == self.target_height:
            return frame
        scale = min(self.target_width / w, self.target_height / h)
        new_w = round(w * scale)
        new_h = round(h * scale)
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((self.target_height, self.target_width, 3), dtype=np.uint8)
        x_off = (self.target_width - new_w) // 2
        y_off = (self.target_height - new_h) // 2
        canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
        return canvas
