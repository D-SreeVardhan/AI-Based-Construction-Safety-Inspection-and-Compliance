"""Robust ground-plane fit from paired head/foot observations, with bootstrap (v7 §37).

The camera model has three unknowns (focal length, pitch, camera height). Each worker's
foot pixel fixes a point on the ground; the same worker standing 1 WH tall must then land
on the observed head pixel. Huber loss absorbs workers who are not average height or whose
pose estimate is poor. Fixing the standing height to 1 WH sets the unit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import least_squares

from pipeline.geometry.camera import (
    CameraParams,
    ImageFrame,
    backproject,
    homography,
    horizon_y,
    project,
)
from shared.config import RelativePlaneConfig, UncertaintyConfig
from shared.schemas.geometry import GroundPlane, VerticalObservation

_PITCH_BOUNDS = (math.radians(-5.0), math.radians(85.0))
_HEIGHT_BOUNDS = (0.5, 60.0)
_FOCAL_RATIO_BOUNDS = (0.3, 6.0)
_HUBER_SCALE = 2.0
_MIN_BOOTSTRAP_BLOCK_OBS = 1


class PlaneFitError(Exception):
    """The plane could not be accepted; ``reason`` is a stable machine-readable code."""

    def __init__(self, reason: str, *, feed_unstable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.feed_unstable = feed_unstable


@dataclass(frozen=True)
class FitInputs:
    head: np.ndarray  # (N, 2)
    foot: np.ndarray  # (N, 2)
    sigma: np.ndarray  # (N,) head noise in px
    track: np.ndarray  # (N,) track labels
    time_s: np.ndarray  # (N,)

    def take(self, index: np.ndarray) -> FitInputs:
        return FitInputs(
            self.head[index],
            self.foot[index],
            self.sigma[index],
            self.track[index],
            self.time_s[index],
        )

    def __len__(self) -> int:
        return len(self.head)


def inputs_from_observations(
    observations: list[VerticalObservation], head_sigma_fraction: float
) -> FitInputs:
    head = np.array([[o.head_reference.x, o.head_reference.y] for o in observations])
    foot = np.array([[o.foot_reference.x, o.foot_reference.y] for o in observations])
    pixel_height = np.linalg.norm(head - foot, axis=1)
    sigma = np.maximum(2.0, head_sigma_fraction * pixel_height)
    return FitInputs(
        head,
        foot,
        sigma,
        np.array([o.canonical_track_id for o in observations]),
        np.array([o.video_time_s for o in observations]),
    )


def _residuals(x: np.ndarray, frame: ImageFrame, data: FitInputs) -> np.ndarray:
    params = CameraParams.from_array(x)
    ground = backproject(data.foot, frame, params.focal_px, params.pitch_rad, params.height_wh)
    predicted = project(ground, frame, params.focal_px, params.pitch_rad, params.height_wh, 1.0)
    residual = (predicted - data.head) / data.sigma[:, None]
    return np.nan_to_num(residual, nan=1e3, posinf=1e3, neginf=-1e3).ravel()


def _solve(x0: np.ndarray, frame: ImageFrame, data: FitInputs) -> tuple[np.ndarray, float] | None:
    lower = np.array(
        [_PITCH_BOUNDS[0], math.log(_FOCAL_RATIO_BOUNDS[0] * frame.width), _HEIGHT_BOUNDS[0]]
    )
    upper = np.array(
        [_PITCH_BOUNDS[1], math.log(_FOCAL_RATIO_BOUNDS[1] * frame.width), _HEIGHT_BOUNDS[1]]
    )
    try:
        result = least_squares(
            _residuals,
            np.clip(x0, lower + 1e-6, upper - 1e-6),
            args=(frame, data),
            bounds=(lower, upper),
            loss="huber",
            f_scale=_HUBER_SCALE,
            max_nfev=200,
        )
    except (ValueError, FloatingPointError):
        return None
    if not np.all(np.isfinite(result.x)):
        return None
    return result.x, float(result.cost)


def fit_camera(frame: ImageFrame, data: FitInputs) -> CameraParams | None:
    """Multi-start robust fit; the lowest-cost solution wins."""
    best: tuple[np.ndarray, float] | None = None
    for pitch in (0.1, 0.4, 0.8, 1.2):
        for focal_ratio in (0.7, 1.2, 2.0):
            for height in (2.0, 4.0, 8.0):
                x0 = np.array([pitch, math.log(focal_ratio * frame.width), height])
                solved = _solve(x0, frame, data)
                if solved is not None and (best is None or solved[1] < best[1]):
                    best = solved
    return CameraParams.from_array(best[0]) if best is not None else None


def _refit(base: CameraParams, frame: ImageFrame, data: FitInputs) -> CameraParams | None:
    solved = _solve(base.as_array(), frame, data)
    return CameraParams.from_array(solved[0]) if solved is not None else None


def _expand_hull(points: np.ndarray, margin: float) -> np.ndarray:
    angles = np.linspace(0, 2 * math.pi, 12, endpoint=False)
    ring = np.stack([np.cos(angles), np.sin(angles)], axis=1) * margin
    cloud = (points[:, None, :] + ring[None, :, :]).reshape(-1, 2).astype(np.float32)
    return cv2.convexHull(cloud).reshape(-1, 2)


@dataclass(frozen=True)
class PlaneEnsemble:
    """The accepted plane plus bootstrap cameras for propagating uncertainty."""

    plane: GroundPlane
    frame: ImageFrame
    base: CameraParams
    focal: np.ndarray  # (B,)
    pitch: np.ndarray  # (B,)
    height: np.ndarray  # (B,)

    def ground(self, pixels: np.ndarray) -> np.ndarray:
        """Point-estimate ground coordinates for ``(N, 2)`` pixels."""
        return backproject(
            pixels, self.frame, self.base.focal_px, self.base.pitch_rad, self.base.height_wh
        )

    def ground_samples(self, pixels: np.ndarray) -> np.ndarray:
        """Ground coordinates under every bootstrap camera: ``(B, N, 2)``.

        ``pixels`` is ``(N, 2)`` shared by all cameras or ``(B, N, 2)`` with one set each.
        """
        shared = pixels[None, ...] if pixels.ndim == 2 else pixels
        return backproject(
            shared,
            self.frame,
            self.focal[:, None],
            self.pitch[:, None],
            self.height[:, None],
        )

    def in_support(self, ground: np.ndarray) -> np.ndarray:
        polygon = np.array(self.plane.support_polygon_wh, dtype=np.float32).reshape(-1, 1, 2)
        return np.array(
            [
                bool(np.isfinite(g).all())
                and cv2.pointPolygonTest(polygon, (float(g[0]), float(g[1])), False) >= 0
                for g in ground
            ]
        )


def _is_multimodal(horizons: np.ndarray, frame: ImageFrame) -> bool:
    """True when bootstrap horizons split into two well separated groups."""
    if len(horizons) < 20:
        return False
    ordered = np.sort(horizons)
    gaps = np.diff(ordered)
    split = int(np.argmax(gaps)) + 1
    low, high = ordered[:split], ordered[split:]
    if min(len(low), len(high)) < 0.1 * len(ordered):
        return False
    spread = max(float(np.std(low)), float(np.std(high)), 1.0)
    return bool(gaps[split - 1] > max(4 * spread, 0.1 * frame.height))


def _bootstrap_indices(data: FitInputs, block_s: float, rng: np.random.Generator) -> np.ndarray:
    tracks = np.unique(data.track)
    drawn = rng.choice(tracks, size=len(tracks), replace=True)
    chosen: list[int] = []
    for track in drawn:
        members = np.flatnonzero(data.track == track)
        blocks = np.floor(data.time_s[members] / block_s).astype(int)
        labels = np.unique(blocks)
        for label in rng.choice(labels, size=len(labels), replace=True):
            chosen.extend(members[blocks == label].tolist())
    return np.array(chosen, dtype=int)


def fit_plane(
    observations: list[VerticalObservation],
    frame: ImageFrame,
    plane_cfg: RelativePlaneConfig,
    uncertainty_cfg: UncertaintyConfig,
) -> PlaneEnsemble:
    """Fit, gate and bootstrap the ground plane. Raises ``PlaneFitError`` when rejected."""
    if len(observations) < plane_cfg.minimum_pairs:
        raise PlaneFitError("insufficient_vertical_observations")
    if len({o.canonical_track_id for o in observations}) < plane_cfg.minimum_distinct_tracks:
        raise PlaneFitError("insufficient_distinct_tracks")

    data = inputs_from_observations(observations, plane_cfg.head_sigma_fraction)
    base = fit_camera(frame, data)
    if base is None:
        raise PlaneFitError("fit_did_not_converge")

    ratio = base.focal_px / frame.width
    if not plane_cfg.minimum_focal_width_ratio <= ratio <= plane_cfg.maximum_focal_width_ratio:
        raise PlaneFitError("focal_length_out_of_range", feed_unstable=True)

    residual = _residuals(base.as_array(), frame, data).reshape(-1, 2)
    normalised = np.linalg.norm(residual, axis=1)
    inliers = normalised <= plane_cfg.inlier_sigma
    inlier_ratio = float(inliers.mean())
    if inlier_ratio < plane_cfg.minimum_vertical_inlier_ratio:
        raise PlaneFitError("low_inlier_ratio", feed_unstable=True)
    pixel_error = residual * data.sigma[:, None]
    rms = float(np.sqrt(np.mean(np.sum(pixel_error[inliers] ** 2, axis=1))))
    if rms > plane_cfg.maximum_reprojection_rms_px:
        raise PlaneFitError("reprojection_error_too_high", feed_unstable=True)

    ground = backproject(data.foot, frame, base.focal_px, base.pitch_rad, base.height_wh)
    accepted = ground[inliers]
    if not np.isfinite(accepted).all() or (accepted[:, 1] <= 0).any():
        raise PlaneFitError("plane_not_in_front_of_camera", feed_unstable=True)
    condition = float(np.linalg.cond(homography(base, frame)))
    if condition > plane_cfg.maximum_condition_number:
        raise PlaneFitError("homography_ill_conditioned", feed_unstable=True)

    shift = _temporal_horizon_shift(frame, data, base, plane_cfg)
    if shift is not None and shift > plane_cfg.maximum_temporal_horizon_shift_px:
        raise PlaneFitError("horizon_unstable_over_time", feed_unstable=True)

    ensemble_params = _bootstrap(base, frame, data, plane_cfg, uncertainty_cfg)
    horizons = frame.cy - ensemble_params[:, 1] * np.tan(ensemble_params[:, 0])
    if _is_multimodal(horizons, frame):
        raise PlaneFitError("multimodal_bootstrap_solution", feed_unstable=True)

    hull = _expand_hull(accepted, plane_cfg.support_expansion_wh)
    plane = GroundPlane(
        plane_id="plane-1",
        focal_px=base.focal_px,
        focal_width_ratio=ratio,
        pitch_deg=math.degrees(base.pitch_rad),
        camera_height_wh=base.height_wh,
        principal_point=(frame.cx, frame.cy),
        horizon_y=horizon_y(base, frame),
        support_polygon_wh=tuple((float(x), float(z)) for x, z in hull),
        observation_count=len(data),
        track_count=len(np.unique(data.track)),
        inlier_ratio=inlier_ratio,
        reprojection_rms_px=rms,
        condition_number=condition,
        temporal_horizon_shift_px=shift,
        bootstrap_successes=len(ensemble_params),
        bootstrap_total=uncertainty_cfg.bootstrap_samples,
    )
    return PlaneEnsemble(
        plane=plane,
        frame=frame,
        base=base,
        focal=ensemble_params[:, 1],
        pitch=ensemble_params[:, 0],
        height=ensemble_params[:, 2],
    )


def _temporal_horizon_shift(
    frame: ImageFrame, data: FitInputs, base: CameraParams, cfg: RelativePlaneConfig
) -> float | None:
    middle = float(np.median(data.time_s))
    halves = [
        data.take(np.flatnonzero(data.time_s <= middle)),
        data.take(np.flatnonzero(data.time_s > middle)),
    ]
    if any(len(h) < cfg.minimum_pairs for h in halves):
        return None
    horizons = []
    for half in halves:
        fitted = _refit(base, frame, half)
        if fitted is None:
            return None
        horizons.append(horizon_y(fitted, frame))
    return abs(horizons[0] - horizons[1])


def _bootstrap(
    base: CameraParams,
    frame: ImageFrame,
    data: FitInputs,
    plane_cfg: RelativePlaneConfig,
    cfg: UncertaintyConfig,
) -> np.ndarray:
    """Columns: pitch, focal_px, height_wh of each successful replicate."""
    rng = np.random.default_rng(cfg.seed)
    replicates: list[tuple[float, float, float]] = []
    for _ in range(cfg.bootstrap_samples):
        index = _bootstrap_indices(data, cfg.temporal_block_seconds, rng)
        if len(index) < 6:
            continue
        fitted = _refit(base, frame, data.take(index))
        if fitted is None:
            continue
        ratio = fitted.focal_px / frame.width
        if not plane_cfg.minimum_focal_width_ratio <= ratio <= plane_cfg.maximum_focal_width_ratio:
            continue
        replicates.append((fitted.pitch_rad, fitted.focal_px, fitted.height_wh))
    if len(replicates) < cfg.minimum_successful_samples:
        raise PlaneFitError("bootstrap_failed", feed_unstable=True)
    return np.array(replicates)
