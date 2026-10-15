"""Where on site the exposure happened: worker-seconds in a hazard condition, as a map.

Accumulated from each worker's ground-contact point while any rule's condition holds for
them (confirmed or not), then smoothed and laid over a dimmed frame of the camera's view.
Image space, so it needs no calibration and reads directly against the scene. One hue
from light to dark (a sequential scale): more colour means more exposure.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np

from pipeline.rules.temporal import Predicate, predicate_for
from shared.enums import PERSON_CLASS
from shared.schemas.frame import FrameRuleOutput
from shared.schemas.tracks import Pass1TrackObservation

GRID_SCALE = 0.25  # accumulate on a quarter-resolution grid
SIGMA_PX = 7.0  # smoothing on that grid (~28 px on the 1080p canvas)
HIGH = np.array([59, 59, 208], np.float32)  # critical red #d03b3b (BGR)
LOW = np.array([118, 186, 250], np.float32)  # warm amber, the light end of the ramp


class ExposureHeatmap:
    def __init__(self, canvas: tuple[int, int]) -> None:
        self.canvas = canvas
        self.size = (max(1, round(canvas[0] * GRID_SCALE)), max(1, round(canvas[1] * GRID_SCALE)))
        self.exposure = np.zeros((self.size[1], self.size[0]), np.float32)
        self.background: np.ndarray | None = None
        self.total_s = 0.0

    def add(
        self,
        image: np.ndarray,
        observations: Iterable[Pass1TrackObservation],
        output: FrameRuleOutput | None,
        dt: float,
    ) -> None:
        if self.background is None:
            self.background = cv2.resize(image, self.canvas, interpolation=cv2.INTER_AREA)
        if output is None or dt <= 0:
            return
        exposed = {
            r.track_id
            for r in output.results
            if r.track_id is not None and predicate_for(r.status) is Predicate.HOLDS
        }
        if not exposed:
            return
        width, height = self.size
        for o in observations:
            if o.object_class != PERSON_CLASS or o.canonical_track_id not in exposed:
                continue
            x = int(o.anchor_reference.x * GRID_SCALE)
            y = int(o.anchor_reference.y * GRID_SCALE)
            if 0 <= x < width and 0 <= y < height:
                self.exposure[y, x] += dt
                self.total_s += dt

    def render(self, width: int = 1280) -> np.ndarray | None:
        if self.background is None or self.total_s <= 0:
            return None
        height = round(width * self.canvas[1] / self.canvas[0])
        density = cv2.GaussianBlur(self.exposure, (0, 0), SIGMA_PX)
        density = cv2.resize(density, (width, height), interpolation=cv2.INTER_CUBIC)
        peak = float(np.percentile(density[density > 0], 99.5)) if (density > 0).any() else 0.0
        level = np.clip(density / peak, 0.0, 1.0) if peak > 0 else density
        base = cv2.resize(self.background, (width, height), interpolation=cv2.INTER_AREA)
        grey = cv2.cvtColor(cv2.cvtColor(base, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        out = (grey.astype(np.float32) * 0.55).astype(np.float32)
        colour = LOW[None, None, :] + (HIGH - LOW)[None, None, :] * level[..., None]
        alpha = np.clip(level * 1.4, 0.0, 0.85)[..., None]
        out = out * (1 - alpha) + colour * alpha
        return out.clip(0, 255).astype(np.uint8)

    def save(self, path: Path, width: int = 1280) -> Path | None:
        image = self.render(width)
        if image is None:
            return None
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return path
