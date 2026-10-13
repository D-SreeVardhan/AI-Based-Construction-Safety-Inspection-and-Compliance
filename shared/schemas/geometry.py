"""Relative ground-plane geometry (v7 §37).

Distances are in Worker-Heights (WH): the median accepted standing height is exactly 1 WH.
They are relative to the workers in this video, never metres.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from shared.coordinates import Point2, StrictModel


class VerticalObservation(StrictModel):
    """Head and foot of one upright worker in one frame, paired and never averaged apart."""

    observation_id: str
    shot_id: str
    frame_index: int = Field(ge=0)
    video_time_s: float = Field(ge=0.0)
    canonical_track_id: str
    track_id: int
    head_reference: Point2
    foot_reference: Point2
    head_confidence: float = Field(ge=0.0, le=1.0)
    foot_confidence: float = Field(ge=0.0, le=1.0)
    standing_probability: float = Field(ge=0.0, le=1.0)
    occlusion_fraction: float = Field(ge=0.0, le=1.0)
    covariance_4x4: tuple[tuple[float, ...], ...]


class GroundPlane(StrictModel):
    plane_id: str
    focal_px: float = Field(gt=0.0)
    focal_width_ratio: float = Field(gt=0.0)
    pitch_deg: float
    camera_height_wh: float = Field(gt=0.0)
    principal_point: tuple[float, float]
    horizon_y: float
    # Convex region (X, Z in WH) covered by accepted footpoints, widened for tolerance. It is
    # only the validity region of this fit, never a physical slab edge.
    support_polygon_wh: tuple[tuple[float, float], ...]
    observation_count: int = Field(ge=0)
    track_count: int = Field(ge=0)
    inlier_ratio: float = Field(ge=0.0, le=1.0)
    reprojection_rms_px: float = Field(ge=0.0)
    condition_number: float = Field(ge=0.0)
    temporal_horizon_shift_px: float | None = None
    bootstrap_successes: int = Field(ge=0)
    bootstrap_total: int = Field(ge=0)


class GeometryModel(StrictModel):
    schema_version: int = 1
    status: Literal["ok", "unavailable"]
    # Machine-readable reason when unavailable.
    status_reason: str | None = None
    # True when the feed itself defeats a static ground plane (moving camera or an
    # unstable fit), as opposed to simply too little evidence.
    feed_unstable: bool = False
    pose_model_id: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    max_camera_shift_px: float | None = None
    plane: GroundPlane | None = None
    observations: tuple[VerticalObservation, ...] = ()
