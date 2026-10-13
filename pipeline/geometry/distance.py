"""Distances in Worker-Heights with bootstrap intervals (v7 §37.3).

Every distance is evaluated under each bootstrap camera, with the worker and target pixels
perturbed by their own localisation noise, so the interval reflects both the plane fit and
the detections.
"""

from __future__ import annotations

import numpy as np

from pipeline.geometry.plane import PlaneEnsemble
from shared.config import UncertaintyConfig
from shared.coordinates import DistanceInterval
from shared.enums import DistanceBand


def point_to_polyline(points: np.ndarray, polyline: np.ndarray) -> np.ndarray:
    """Distance from ``points (..., 2)`` to ``polyline (..., K, 2)``; one point if ``K == 1``."""
    if polyline.shape[-2] == 1:
        return np.linalg.norm(points - polyline[..., 0, :], axis=-1)
    start, end = polyline[..., :-1, :], polyline[..., 1:, :]
    segment = end - start
    length_sq = np.sum(segment**2, axis=-1)
    offset = points[..., None, :] - start
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.clip(np.sum(offset * segment, axis=-1) / length_sq, 0.0, 1.0)
    t = np.where(length_sq > 0, t, 0.0)
    nearest = start + t[..., None] * segment
    return np.min(np.linalg.norm(points[..., None, :] - nearest, axis=-1), axis=-1)


def distance_interval(
    ensemble: PlaneEnsemble,
    worker_px: np.ndarray,
    target_px: np.ndarray,
    *,
    worker_sigma_px: float,
    target_sigma_px: float,
    inflation_wh: float,
    uncertainty: UncertaintyConfig,
    rng: np.random.Generator,
) -> DistanceInterval | None:
    """Interval of the worker-to-target distance, or None when too few replicates map."""
    count = len(ensemble.focal)
    worker = worker_px[None, :] + rng.normal(0.0, worker_sigma_px, (count, 2))
    target = target_px[None, :, :] + rng.normal(0.0, target_sigma_px, (count, *target_px.shape))
    worker_ground = ensemble.ground_samples(worker[:, None, :])[:, 0, :]
    target_ground = np.stack(
        [
            ensemble.ground_samples(target[:, k : k + 1, :])[:, 0, :]
            for k in range(target_px.shape[0])
        ],
        axis=1,
    )
    distance = np.maximum(point_to_polyline(worker_ground, target_ground) - inflation_wh, 0.0)
    valid = distance[np.isfinite(distance)]
    if len(valid) < uncertainty.minimum_successful_samples:
        return None
    tail = (1.0 - uncertainty.confidence_level) / 2.0
    lower, median, upper = np.quantile(valid, [tail, 0.5, 1.0 - tail])
    return DistanceInterval(
        lower_wh=float(lower),
        median_wh=float(median),
        upper_wh=float(upper),
        confidence_level=uncertainty.confidence_level,
        successful_bootstraps=len(valid),
        total_bootstraps=count,
    )


def classify_band(
    interval: DistanceInterval | None, near_max: float, caution_max: float
) -> DistanceBand:
    """Band from the whole interval, never the median alone (v7 §37.3)."""
    if interval is None:
        return DistanceBand.INDETERMINATE
    if interval.upper_wh <= near_max:
        return DistanceBand.NEAR
    if interval.lower_wh > caution_max:
        return DistanceBand.CLEAR
    if interval.lower_wh > near_max and interval.upper_wh <= caution_max:
        return DistanceBand.CAUTION
    return DistanceBand.INDETERMINATE
