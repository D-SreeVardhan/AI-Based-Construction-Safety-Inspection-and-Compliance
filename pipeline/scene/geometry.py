"""2D geometry helpers shared by scene consensus and the R3/R5 rules (pixels or WH)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import cv2
import numpy as np

Point = tuple[float, float]


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    d1, d2 = _cross(p3, p4, p1), _cross(p3, p4, p2)
    d3, d4 = _cross(p1, p2, p3), _cross(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def polygon_self_intersects(points: Sequence[Point]) -> bool:
    n = len(points)
    for i in range(n):
        a1, a2 = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            if _segments_intersect(a1, a2, points[j], points[(j + 1) % n]):
                return True
    return False


def polyline_self_intersects(points: Sequence[Point]) -> bool:
    for i in range(len(points) - 1):
        for j in range(i + 2, len(points) - 1):
            if _segments_intersect(points[i], points[i + 1], points[j], points[j + 1]):
                return True
    return False


def polygon_area(points: Sequence[Point]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(points, [*points[1:], points[0]], strict=True):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def rasterise(points: Sequence[Point], width: int, height: int, scale: float) -> np.ndarray:
    """Binary mask of a polygon drawn on a ``scale``-reduced canvas."""
    mask = np.zeros((round(height * scale), round(width * scale)), np.uint8)
    pts = np.round(np.array(points) * scale).astype(np.int32)
    cv2.fillPoly(mask, [pts], 1)
    return mask


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    union = int(np.logical_or(a, b).sum())
    return 0.0 if union == 0 else float(np.logical_and(a, b).sum()) / union


def _densify(points: Sequence[Point], spacing: float) -> np.ndarray:
    out: list[Point] = []
    for (x1, y1), (x2, y2) in zip(points[:-1], points[1:], strict=True):
        steps = max(1, math.ceil(math.hypot(x2 - x1, y2 - y1) / spacing))
        out.extend((x1 + (x2 - x1) * t / steps, y1 + (y2 - y1) * t / steps) for t in range(steps))
    out.append(points[-1])
    return np.array(out)


def chamfer_distance(a: Sequence[Point], b: Sequence[Point], spacing: float = 8.0) -> float:
    """Symmetric mean nearest-point distance between two polylines."""
    pa, pb = _densify(a, spacing), _densify(b, spacing)
    d = np.linalg.norm(pa[:, None, :] - pb[None, :, :], axis=2)
    return float((d.min(axis=1).mean() + d.min(axis=0).mean()) / 2)


def signed_distance_to_polygon(point: Point, polygon: Sequence[Point]) -> float:
    """Positive inside, negative outside, in the polygon's units."""
    contour = np.array(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return float(cv2.pointPolygonTest(contour, (float(point[0]), float(point[1])), True))


def point_to_segment_distance(point: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0
    if length_sq > 0:
        t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / length_sq))
    return math.hypot(point[0] - (ax + t * dx), point[1] - (ay + t * dy))


def point_to_polyline_distance(point: Point, polyline: Sequence[Point]) -> float:
    segments = zip(polyline[:-1], polyline[1:], strict=True)
    return min(point_to_segment_distance(point, a, b) for a, b in segments)
