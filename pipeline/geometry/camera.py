"""Pinhole camera over one ground plane, in Worker-Height units (v7 §37.2).

Axes: world X right, Z forward along the ground, camera at height ``c`` WH above the plane
and pitched down by ``theta``. Image rows grow downward. Roll is assumed to be zero.

Everything is vectorised so a bootstrap ensemble of cameras (arrays of shape ``(B, 1)``)
can map the same pixel set in one call.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ImageFrame:
    """The visible image inside the reference canvas; the principal point is its centre."""

    cx: float
    cy: float
    width: float
    height: float


@dataclass(frozen=True)
class CameraParams:
    focal_px: float
    pitch_rad: float
    height_wh: float

    def as_array(self) -> np.ndarray:
        return np.array([self.pitch_rad, np.log(self.focal_px), self.height_wh])

    @classmethod
    def from_array(cls, values: np.ndarray) -> CameraParams:
        return cls(
            focal_px=float(np.exp(values[1])),
            pitch_rad=float(values[0]),
            height_wh=float(values[2]),
        )


def horizon_y(params: CameraParams, frame: ImageFrame) -> float:
    return frame.cy - params.focal_px * float(np.tan(params.pitch_rad))


def backproject(
    pixels: np.ndarray,
    frame: ImageFrame,
    focal: np.ndarray | float,
    pitch: np.ndarray | float,
    height: np.ndarray | float,
) -> np.ndarray:
    """Ground ``(X, Z)`` in WH for pixels on the plane; NaN at or above the horizon.

    ``pixels`` has shape ``(..., 2)`` and broadcasts against the camera parameters.
    """
    dx = (pixels[..., 0] - frame.cx) / focal
    dy = (pixels[..., 1] - frame.cy) / focal
    tan_p, cos_p, sin_p = np.tan(pitch), np.cos(pitch), np.sin(pitch)
    denom = dy + tan_p
    with np.errstate(divide="ignore", invalid="ignore"):
        depth = np.where(denom > 1e-9, height / (cos_p * denom), np.nan)
        z = (depth - height * sin_p) / cos_p
    return np.stack([depth * dx, z], axis=-1)


def project(
    ground: np.ndarray,
    frame: ImageFrame,
    focal: np.ndarray | float,
    pitch: np.ndarray | float,
    height: np.ndarray | float,
    above_plane_wh: float = 0.0,
) -> np.ndarray:
    """Pixels of ground points ``(X, Z)`` lifted ``above_plane_wh`` along the vertical."""
    x, z = ground[..., 0], ground[..., 1]
    y_rel = above_plane_wh - height
    cos_p, sin_p = np.cos(pitch), np.sin(pitch)
    y_c = -y_rel * cos_p - z * sin_p
    z_c = -y_rel * sin_p + z * cos_p
    with np.errstate(divide="ignore", invalid="ignore"):
        u = frame.cx + focal * x / z_c
        v = frame.cy + focal * y_c / z_c
    return np.stack([u, v], axis=-1)


def homography(params: CameraParams, frame: ImageFrame) -> np.ndarray:
    """Plane ``(X, Z, 1)`` to pixel homography; used for its conditioning."""
    sin_p, cos_p = np.sin(params.pitch_rad), np.cos(params.pitch_rad)
    k = np.array([[params.focal_px, 0, frame.cx], [0, params.focal_px, frame.cy], [0, 0, 1.0]])
    m = np.array(
        [[1.0, 0, 0], [0, -sin_p, params.height_wh * cos_p], [0, cos_p, params.height_wh * sin_p]]
    )
    return k @ m
