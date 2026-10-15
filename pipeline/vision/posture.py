"""Worker posture for R6 (worker down): box shape first, pose keypoints to confirm (v3).

Most workers are upright (box at least `UPRIGHT_ASPECT` times taller than wide) and need
nothing more. A box that is wider than it is tall is a lying candidate. Bending over rebar
or kneeling makes squat boxes too, so candidates are checked with the pose model: lying
means the shoulder-to-hip axis is within `LYING_ANGLE` of horizontal. Without the pose
model, only very flat boxes count (`NO_POSE_LYING_ASPECT`), which misses more but rarely
cries wolf.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from shared.enums import Posture

UPRIGHT_ASPECT = 1.6
LYING_CANDIDATE_ASPECT = 0.8
NO_POSE_LYING_ASPECT = 0.5
MIN_WIDTH_PX = 40.0
LYING_ANGLE = 35.0  # degrees from horizontal for the shoulder-hip axis
KEYPOINT_CONFIDENCE = 0.4
SHOULDERS, HIPS = (5, 6), (11, 12)  # COCO keypoint indices


def posture_from_box(width: float, height: float) -> Posture | None:
    """Upright / crouched straight from the box; None marks a lying candidate."""
    aspect = height / max(width, 1e-6)
    if aspect >= UPRIGHT_ASPECT:
        return Posture.UPRIGHT
    if aspect >= LYING_CANDIDATE_ASPECT or width < MIN_WIDTH_PX:
        return Posture.CROUCHED
    return None


def lying_from_keypoints(keypoints: np.ndarray) -> bool | None:
    """keypoints: (17, 3) x, y, confidence. True lying, False not, None undecidable."""
    if keypoints.shape[0] < 13:
        return None
    shoulder = [keypoints[i] for i in SHOULDERS if keypoints[i, 2] >= KEYPOINT_CONFIDENCE]
    hip = [keypoints[i] for i in HIPS if keypoints[i, 2] >= KEYPOINT_CONFIDENCE]
    if not shoulder or not hip:
        return None
    s = np.mean([p[:2] for p in shoulder], axis=0)
    h = np.mean([p[:2] for p in hip], axis=0)
    dx, dy = abs(float(s[0] - h[0])), abs(float(s[1] - h[1]))
    if dx + dy < 2.0:
        return None
    angle_from_horizontal = math.degrees(math.atan2(dy, dx))
    return angle_from_horizontal <= LYING_ANGLE


class PoseVerifier:
    """yolo26n-pose on lying candidates only (rare, so cheap)."""

    def __init__(self, weights: Path, device: str) -> None:
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.device = device

    def lying(self, crops: Sequence[np.ndarray]) -> list[bool | None]:
        if not crops:
            return []
        results = self.model.predict(list(crops), imgsz=320, device=self.device, verbose=False)
        verdicts: list[bool | None] = []
        for result in results:
            if result.keypoints is None or len(result.keypoints) == 0:
                verdicts.append(None)
                continue
            data = result.keypoints.data.cpu().numpy()  # (people, 17, 3)
            confidence = result.boxes.conf.cpu().numpy() if result.boxes is not None else None
            best = int(np.argmax(confidence)) if confidence is not None and len(confidence) else 0
            verdicts.append(lying_from_keypoints(data[best]))
        return verdicts


def resolve_pose_weights(configured: str, root: Path) -> Path | None:
    for candidate in (root / configured, root / "artifacts/models/pretrained/yolo26n-pose.pt"):
        if candidate.is_file():
            return candidate
    return None


def decide(box_posture: Posture | None, verdict: bool | None, aspect: float) -> Posture:
    """Final posture for a lying candidate given the pose verdict (None = no pose)."""
    if box_posture is not None:
        return box_posture
    if verdict is True:
        return Posture.LYING
    if verdict is False:
        return Posture.CROUCHED
    return Posture.LYING if aspect < NO_POSE_LYING_ASPECT else Posture.CROUCHED
