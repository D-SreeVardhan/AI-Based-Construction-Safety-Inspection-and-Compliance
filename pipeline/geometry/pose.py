"""Pose sampling for relative geometry (v7 §34.8).

Detector boxes cannot supply trustworthy head and foot points, so a pretrained pose model is
run on a sparse sample of upright worker crops. This is a geometry sampling pass, not a
per-frame runtime stage: at most ``maximum_samples_per_track`` frames per worker.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from pipeline.intake import FrameSampler
from shared.config import PoseConfig, RelativePlaneConfig
from shared.coordinates import Point2
from shared.enums import CoordinateSpace
from shared.schemas.geometry import VerticalObservation
from shared.schemas.tracks import Pass1TrackObservation

try:
    from ultralytics import YOLO as _YOLO
except ImportError:  # pragma: no cover - exercised only without the vision extra
    _YOLO = None  # type: ignore[assignment,misc]

# COCO keypoint indices.
_NOSE, _L_EYE, _R_EYE, _L_EAR, _R_EAR = 0, 1, 2, 3, 4
_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP = 5, 6, 11, 12
_L_ANKLE, _R_ANKLE = 15, 16
_HEAD_POINTS = (_NOSE, _L_EYE, _R_EYE, _L_EAR, _R_EAR)

# Anthropometric proportions (fractions of standing height): eye level sits 0.064 H below
# the crown, so the crown lies 0.54 of the shoulder-to-eye distance above the eyes; the ankle
# joint sits 0.039 H above the sole.
_CROWN_ABOVE_EYES = 0.54
_SOLE_BELOW_ANKLE = 0.039 / 0.961
_OCCLUSION_CONFIDENCE = 0.5
_CROP_PADDING = 0.15
_MIN_UPRIGHT_ASPECT = 1.4
_EDGE_MARGIN_PX = 3.0


@dataclass(frozen=True)
class PoseSampling:
    observations: list[VerticalObservation]
    candidate_count: int
    # Greyscale content-region thumbnails of the frames read, for camera-motion estimation.
    thumbnails: dict[int, np.ndarray]


class PoseEstimator:
    """Thin wrapper over the ultralytics pose model returning keypoints per crop."""

    def __init__(self, model_path: Path, image_size: int) -> None:
        if _YOLO is None:
            raise ImportError("ultralytics is required for pose sampling (uv sync --extra vision)")
        self.model_id = model_path.name
        self._image_size = image_size
        self._model = _YOLO(str(model_path))

    def keypoints(self, crops: Sequence[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray] | None]:
        """``(xy (17, 2), confidence (17,))`` in crop pixels for the most confident person."""
        if not crops:
            return []
        outputs: list[tuple[np.ndarray, np.ndarray] | None] = []
        for result in self._model(list(crops), imgsz=self._image_size, verbose=False):
            if result.keypoints is None or len(result.keypoints) == 0:
                outputs.append(None)
                continue
            best = int(np.argmax(result.boxes.conf.cpu().numpy()))
            xy = result.keypoints.xy[best].cpu().numpy()
            conf = result.keypoints.conf[best].cpu().numpy()
            outputs.append((xy, conf))
        return outputs


def select_candidates(
    observations: Sequence[Pass1TrackObservation],
    pose_cfg: PoseConfig,
    plane_cfg: RelativePlaneConfig,
    *,
    canvas_width: float,
    canvas_height: float,
) -> list[Pass1TrackObservation]:
    """Upright, untruncated, large-enough worker observations, spaced and capped per track."""
    by_track: dict[str, list[Pass1TrackObservation]] = defaultdict(list)
    for obs in observations:
        if obs.object_class != "person":
            continue
        box = obs.box_reference
        height, width = box.height(), box.width()
        if height < plane_cfg.minimum_pixel_height or width <= 0:
            continue
        if height / width < _MIN_UPRIGHT_ASPECT:
            continue
        if (
            box.y1 < _EDGE_MARGIN_PX
            or box.y2 > canvas_height - _EDGE_MARGIN_PX
            or box.x1 < _EDGE_MARGIN_PX
            or box.x2 > canvas_width - _EDGE_MARGIN_PX
        ):
            continue
        by_track[obs.canonical_track_id].append(obs)

    chosen: list[Pass1TrackObservation] = []
    for items in by_track.values():
        spaced: list[Pass1TrackObservation] = []
        for obs in sorted(items, key=lambda o: o.video_time_s):
            if (
                not spaced
                or obs.video_time_s - spaced[-1].video_time_s >= pose_cfg.sample_spacing_seconds
            ):
                spaced.append(obs)
        limit = pose_cfg.maximum_samples_per_track
        if len(spaced) > limit:
            picks = np.linspace(0, len(spaced) - 1, limit).round().astype(int)
            spaced = [spaced[i] for i in picks]
        chosen.extend(spaced)
    if len(chosen) > pose_cfg.maximum_total_samples:
        # Thin evenly across time rather than favouring whichever tracks come first.
        chosen.sort(key=lambda o: o.video_time_s)
        picks = np.linspace(0, len(chosen) - 1, pose_cfg.maximum_total_samples).round().astype(int)
        chosen = [chosen[i] for i in sorted(set(picks.tolist()))]
    return chosen


def _midpoint(
    xy: np.ndarray, conf: np.ndarray, indices: Sequence[int], floor: float
) -> np.ndarray | None:
    usable = [i for i in indices if conf[i] >= floor]
    if not usable:
        return None
    weights = conf[usable]
    return (xy[usable] * weights[:, None]).sum(axis=0) / weights.sum()


def standing_probability(shoulder: np.ndarray, hip: np.ndarray, ankle: np.ndarray) -> float:
    """Shoulder-hip-ankle alignment combined with a leg-to-torso length check."""
    torso, legs = hip - shoulder, ankle - hip
    torso_len, leg_len = float(np.linalg.norm(torso)), float(np.linalg.norm(legs))
    if torso_len < 1e-6 or leg_len < 1e-6:
        return 0.0
    alignment = float(np.dot(torso, legs) / (torso_len * leg_len))
    upright = float(np.clip((alignment - 0.80) / 0.15, 0.0, 1.0))
    extended = float(np.clip((leg_len / torso_len - 0.8) / 0.6, 0.0, 1.0))
    return min(upright, extended)


def vertical_from_keypoints(
    xy: np.ndarray,
    conf: np.ndarray,
    obs: Pass1TrackObservation,
    *,
    confidence_floor: float,
    head_sigma_fraction: float,
    foot_sigma_fraction: float,
) -> VerticalObservation | None:
    """Paired head-crown and sole points from one worker's keypoints, or None if unusable."""
    ankles = _midpoint(xy, conf, (_L_ANKLE, _R_ANKLE), confidence_floor)
    shoulders = _midpoint(xy, conf, (_L_SHOULDER, _R_SHOULDER), confidence_floor)
    hips = _midpoint(xy, conf, (_L_HIP, _R_HIP), confidence_floor)
    eyes = _midpoint(xy, conf, _HEAD_POINTS, confidence_floor)
    if ankles is None or shoulders is None or hips is None or eyes is None:
        return None

    crown = eyes + _CROWN_ABOVE_EYES * (eyes - shoulders)
    sole = ankles + _SOLE_BELOW_ANKLE * (ankles - crown)
    standing = standing_probability(shoulders, hips, ankles)
    occlusion = float(np.mean(conf < _OCCLUSION_CONFIDENCE))
    pixel_height = float(np.linalg.norm(crown - sole))
    if pixel_height <= 0 or not np.isfinite([crown, sole]).all():
        return None

    head_conf = float(np.mean([conf[i] for i in _HEAD_POINTS if conf[i] >= confidence_floor]))
    foot_conf = float(
        np.mean([conf[i] for i in (_L_ANKLE, _R_ANKLE) if conf[i] >= confidence_floor])
    )
    head_var = (head_sigma_fraction * pixel_height / max(head_conf, 0.5)) ** 2
    foot_var = (foot_sigma_fraction * pixel_height / max(foot_conf, 0.5)) ** 2
    covariance = (
        (head_var, 0.0, 0.0, 0.0),
        (0.0, head_var, 0.0, 0.0),
        (0.0, 0.0, foot_var, 0.0),
        (0.0, 0.0, 0.0, foot_var),
    )
    space = CoordinateSpace.REFERENCE
    return VerticalObservation(
        observation_id=f"{obs.canonical_track_id}-{obs.frame_index}",
        shot_id=obs.shot_id,
        frame_index=obs.frame_index,
        video_time_s=obs.video_time_s,
        canonical_track_id=obs.canonical_track_id,
        track_id=obs.track_id,
        head_reference=Point2(x=float(crown[0]), y=float(crown[1]), space=space),
        foot_reference=Point2(x=float(sole[0]), y=float(sole[1]), space=space),
        head_confidence=head_conf,
        foot_confidence=foot_conf,
        standing_probability=standing,
        occlusion_fraction=occlusion,
        covariance_4x4=covariance,
    )


def _crop_window(obs: Pass1TrackObservation, width: int, height: int) -> tuple[int, int, int, int]:
    box = obs.box_reference
    pad_x, pad_y = _CROP_PADDING * box.width(), _CROP_PADDING * box.height()
    x1 = max(0, math.floor(box.x1 - pad_x))
    y1 = max(0, math.floor(box.y1 - pad_y))
    x2 = min(width, math.ceil(box.x2 + pad_x))
    y2 = min(height, math.ceil(box.y2 + pad_y))
    return x1, y1, x2, y2


def collect_vertical_observations(
    sampler: FrameSampler,
    observations: Sequence[Pass1TrackObservation],
    estimator: PoseEstimator,
    pose_cfg: PoseConfig,
    plane_cfg: RelativePlaneConfig,
    *,
    content_rect: tuple[int, int, int, int],
    thumbnail_width: int = 480,
) -> PoseSampling:
    """Run pose on the selected crops and keep observations that pass the §37.1 gates."""
    candidates = select_candidates(
        observations,
        pose_cfg,
        plane_cfg,
        canvas_width=sampler.target_width,
        canvas_height=sampler.target_height,
    )
    frames = sampler.frames_at([c.frame_index for c in candidates])
    cx, cy, cw, ch = content_rect

    thumbnails: dict[int, np.ndarray] = {}
    for index, (_, frame) in frames.items():
        grey = cv2.cvtColor(frame[cy : cy + ch, cx : cx + cw], cv2.COLOR_BGR2GRAY)
        scale = thumbnail_width / max(cw, 1)
        thumbnails[index] = cv2.resize(
            grey, (thumbnail_width, max(8, round(ch * scale))), interpolation=cv2.INTER_AREA
        )

    jobs: list[tuple[Pass1TrackObservation, tuple[int, int, int, int], np.ndarray]] = []
    for obs in candidates:
        if obs.frame_index not in frames:
            continue
        frame = frames[obs.frame_index][1]
        window = _crop_window(obs, frame.shape[1], frame.shape[0])
        crop = frame[window[1] : window[3], window[0] : window[2]]
        if crop.size:
            jobs.append((obs, window, crop))

    accepted: list[VerticalObservation] = []
    keypoints = estimator.keypoints([crop for _, _, crop in jobs])
    for (obs, window, _), result in zip(jobs, keypoints, strict=True):
        if result is None:
            continue
        xy, conf = result
        shifted = xy + np.array([window[0], window[1]], dtype=float)
        vertical = vertical_from_keypoints(
            shifted,
            conf,
            obs,
            confidence_floor=pose_cfg.confidence_floor,
            head_sigma_fraction=plane_cfg.head_sigma_fraction,
            foot_sigma_fraction=plane_cfg.foot_sigma_fraction,
        )
        if (
            vertical is not None
            and vertical.standing_probability >= plane_cfg.minimum_standing_probability
            and vertical.occlusion_fraction <= plane_cfg.maximum_occlusion_fraction
            and min(vertical.head_confidence, vertical.foot_confidence)
            >= plane_cfg.minimum_keypoint_confidence
            and abs(vertical.head_reference.y - vertical.foot_reference.y)
            >= plane_cfg.minimum_pixel_height
        ):
            accepted.append(vertical)
    return PoseSampling(accepted, len(candidates), thumbnails)


def estimate_camera_shift(thumbnails: dict[int, np.ndarray], *, scale_to_reference: float) -> float:
    """90th-percentile background translation, in reference px, relative to the first frame.

    Phase correlation on content-region thumbnails. Reference-frame translation is a proxy for
    camera motion; frames whose correlation peak is weak are skipped as unreliable.
    """
    if len(thumbnails) < 2:
        return 0.0
    ordered = [thumbnails[i] for i in sorted(thumbnails)]
    first = ordered[0].astype(np.float32)
    window = cv2.createHanningWindow((first.shape[1], first.shape[0]), cv2.CV_32F)
    shifts: list[float] = []
    for image in ordered[1:]:
        if image.shape != first.shape:
            continue
        (dx, dy), response = cv2.phaseCorrelate(first, image.astype(np.float32), window)
        if response >= 0.05:
            shifts.append(math.hypot(dx, dy) * scale_to_reference)
    return float(np.percentile(shifts, 90)) if shifts else 0.0
