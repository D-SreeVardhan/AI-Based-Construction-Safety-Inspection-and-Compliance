"""Relative ground-plane geometry for R4 and R5 (v7 §34.8, §37).

``build_geometry`` samples worker poses, rejects a moving feed, fits the plane and returns
the model that is persisted plus the ensemble the rules use in-process. Any failure yields an
``unavailable`` model with a stable reason, so R4 and R5 degrade to inconclusive or
unsupported instead of reporting numbers the video cannot support.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from pipeline.geometry.camera import ImageFrame
from pipeline.geometry.context import GeometryContext
from pipeline.geometry.plane import PlaneEnsemble, PlaneFitError, fit_plane
from pipeline.geometry.pose import (
    PoseEstimator,
    collect_vertical_observations,
    estimate_camera_shift,
)
from pipeline.intake import FrameSampler
from shared.config import AppConfig
from shared.schemas.geometry import GeometryModel
from shared.schemas.tracks import Pass1TrackObservation


def content_rect(
    video_width: int, video_height: int, canvas_width: int, canvas_height: int
) -> tuple[int, int, int, int]:
    """Where the source image sits inside the letterboxed reference canvas."""
    scale = min(canvas_width / video_width, canvas_height / video_height)
    width, height = round(video_width * scale), round(video_height * scale)
    return (canvas_width - width) // 2, (canvas_height - height) // 2, width, height


def _unavailable(reason: str, **fields: object) -> GeometryModel:
    return GeometryModel(status="unavailable", status_reason=reason, **fields)  # type: ignore[arg-type]


def build_geometry(
    *,
    sampler: FrameSampler,
    observations: Sequence[Pass1TrackObservation],
    video_width: int | None,
    video_height: int | None,
    config: AppConfig,
    estimator: PoseEstimator | None = None,
) -> tuple[GeometryModel, GeometryContext]:
    """Fit the plane and return the persisted model with the context the rules consume."""
    if not video_width or not video_height:
        rect = (0, 0, sampler.target_width, sampler.target_height)
    else:
        rect = content_rect(video_width, video_height, sampler.target_width, sampler.target_height)
    x_off, y_off, width, height = rect

    def finish(
        model: GeometryModel, ensemble: PlaneEnsemble | None
    ) -> tuple[GeometryModel, GeometryContext]:
        return model, GeometryContext(
            geometry=model,
            ensemble=ensemble,
            uncertainty=config.uncertainty,
            content_bottom=float(y_off + height),
            image_diagonal_px=math.hypot(width, height),
        )

    if not video_width or not video_height:
        return finish(_unavailable("video_dimensions_unknown"), None)
    frame = ImageFrame(cx=x_off + width / 2, cy=y_off + height / 2, width=width, height=height)

    if estimator is None:
        model_path = Path(config.pose.model_path)
        if not model_path.is_file():
            return finish(_unavailable("pose_model_missing"), None)
        try:
            estimator = PoseEstimator(model_path, config.pose.image_size)
        except ImportError:
            return finish(_unavailable("pose_model_unavailable"), None)

    try:
        sampling = collect_vertical_observations(
            sampler,
            observations,
            estimator,
            config.pose,
            config.relative_plane,
            content_rect=rect,
        )
    except (RuntimeError, OSError) as exc:
        return finish(_unavailable(f"pose_sampling_failed: {exc}"[:300]), None)

    thumb_width = next(iter(sampling.thumbnails.values())).shape[1] if sampling.thumbnails else 1
    shift = estimate_camera_shift(sampling.thumbnails, scale_to_reference=width / thumb_width)
    common: dict[str, object] = {
        "pose_model_id": estimator.model_id,
        "candidate_count": sampling.candidate_count,
        "observation_count": len(sampling.observations),
        "observations": tuple(sampling.observations),
        "max_camera_shift_px": shift,
    }
    if shift > config.relative_plane.maximum_camera_shift_px:
        return finish(_unavailable("camera_motion_detected", feed_unstable=True, **common), None)

    try:
        ensemble = fit_plane(
            list(sampling.observations), frame, config.relative_plane, config.uncertainty
        )
    except PlaneFitError as exc:
        return finish(_unavailable(exc.reason, feed_unstable=exc.feed_unstable, **common), None)
    return finish(GeometryModel(status="ok", plane=ensemble.plane, **common), ensemble)  # type: ignore[arg-type]
