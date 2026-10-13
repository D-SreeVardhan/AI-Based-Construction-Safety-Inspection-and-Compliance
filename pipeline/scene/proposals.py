"""Validation of Gemini scene proposals (v7 §39.2). Model output is untrusted input."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from pipeline.scene.geometry import (
    Point,
    polygon_area,
    polygon_self_intersects,
    polyline_self_intersects,
)
from shared.schemas.scene import POLYGON_TYPES, POLYLINE_TYPES

_BOX_ALIASES = {"box"}
_PROTECTION_VISIBILITY = {"sufficient", "insufficient", "unknown"}
_PROTECTION_STATE = {"guarded", "unguarded_or_inadequate", "unknown"}
_MIN_POLYGON_AREA_FRACTION = 0.001  # smaller than 0.1% of the frame is noise


class SceneParseError(ValueError):
    """The reply is structurally unusable, as opposed to containing some bad proposals."""


@dataclass(frozen=True)
class FrameProposal:
    """One validated proposal from one keyframe, in reference-canvas pixels."""

    keyframe_ordinal: int
    proposal_type: str
    geometry_type: str
    points: tuple[Point, ...]
    visible_drop_or_open_side: bool | None
    protection_visibility: str | None
    protection_state: str | None
    rationale: str


def _points(raw: Any, width: int, height: int) -> list[Point] | None:
    if not isinstance(raw, list):
        return None
    out: list[Point] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        y, x = item.get("y"), item.get("x")
        if isinstance(y, bool) or isinstance(x, bool):
            return None
        if not isinstance(y, (int, float)) or not isinstance(x, (int, float)):
            return None
        if not (math.isfinite(y) and math.isfinite(x)) or not (0 <= y <= 1000 and 0 <= x <= 1000):
            return None
        out.append((x / 1000 * width, y / 1000 * height))
    return out


def _bounding_box(points: list[Point]) -> list[Point]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def parse_response(
    raw: str, *, keyframe_count: int, width: int, height: int
) -> tuple[list[FrameProposal], list[str]]:
    """Validated proposals plus a reason for every proposal that was discarded.

    Raises ``SceneParseError`` when the reply is not the expected structure at all.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SceneParseError(f"response is not JSON: {exc}") from exc
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, list):
        raise SceneParseError("response has no 'frames' list")

    accepted: list[FrameProposal] = []
    rejected: list[str] = []
    seen: set[int] = set()
    for frame in frames:
        ordinal = frame.get("keyframe_index") if isinstance(frame, dict) else None
        if not isinstance(ordinal, int) or not 0 <= ordinal < keyframe_count:
            rejected.append(f"unknown keyframe_index {ordinal!r}")
            continue
        if ordinal in seen:
            rejected.append(f"duplicate keyframe_index {ordinal}")
            continue
        seen.add(ordinal)
        for position, item in enumerate(frame.get("proposals") or []):
            label = f"keyframe {ordinal} proposal {position}"
            proposal = _validate(item, ordinal, width, height, label, rejected)
            if proposal is not None:
                accepted.append(proposal)
    return accepted, rejected


def _validate(
    item: Any, ordinal: int, width: int, height: int, label: str, rejected: list[str]
) -> FrameProposal | None:
    if not isinstance(item, dict):
        rejected.append(f"{label}: not an object")
        return None
    proposal_type = item.get("proposal_type")
    if proposal_type not in POLYGON_TYPES | POLYLINE_TYPES:
        rejected.append(f"{label}: unrecognised type {proposal_type!r}")
        return None
    points = _points(item.get("points"), width, height)
    if points is None:
        rejected.append(f"{label}: coordinates missing, non-finite or outside 0-1000")
        return None
    geometry = item.get("geometry_type")
    if geometry in _BOX_ALIASES and len(points) >= 2:
        points, geometry = _bounding_box(points), "polygon"
    expected = "polygon" if proposal_type in POLYGON_TYPES else "polyline"
    if geometry != expected:
        rejected.append(f"{label}: {proposal_type} must be a {expected}, got {geometry!r}")
        return None
    if expected == "polygon":
        if len(points) < 3:
            rejected.append(f"{label}: polygon needs 3+ points")
            return None
        if polygon_self_intersects(points):
            rejected.append(f"{label}: polygon self-intersects")
            return None
        if polygon_area(points) < _MIN_POLYGON_AREA_FRACTION * width * height:
            rejected.append(f"{label}: polygon too small")
            return None
    else:
        if len(points) < 2:
            rejected.append(f"{label}: polyline needs 2+ points")
            return None
        if polyline_self_intersects(points):
            rejected.append(f"{label}: polyline self-intersects")
            return None

    drop = item.get("visible_drop_or_open_side")
    visibility = item.get("protection_visibility")
    state = item.get("protection_state")
    if proposal_type == "open_edge" and not isinstance(drop, bool):
        rejected.append(f"{label}: open_edge without visible_drop_or_open_side")
        return None
    return FrameProposal(
        keyframe_ordinal=ordinal,
        proposal_type=proposal_type,
        geometry_type=expected,
        points=tuple(points),
        visible_drop_or_open_side=drop if isinstance(drop, bool) else None,
        protection_visibility=visibility if visibility in _PROTECTION_VISIBILITY else None,
        protection_state=state if state in _PROTECTION_STATE else None,
        rationale=str(item.get("rationale") or "")[:300],
    )
