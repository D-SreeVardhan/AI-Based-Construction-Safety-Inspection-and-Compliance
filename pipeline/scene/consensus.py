"""Cross-keyframe consensus for scene proposals (v7 §39.3).

A proposal survives only if enough keyframes independently agree on it. Gemini's own
confidence is never read. Agreement removes unstable proposals; it cannot make a
systematically wrong one correct, so every result stays flagged ``heuristic``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np

from pipeline.scene.geometry import (
    Point,
    chamfer_distance,
    mask_iou,
    polygon_area,
    rasterise,
)
from pipeline.scene.proposals import FrameProposal
from shared.config import SceneConfig
from shared.schemas.scene import SceneProposal

_RASTER_SCALE = 0.1
_AREA_TOLERANCE = 0.02  # simplification may change the consensus area by <2%


@dataclass
class _Cluster:
    members: list[FrameProposal] = field(default_factory=list)
    masks: list[np.ndarray] = field(default_factory=list)

    @property
    def keyframes(self) -> set[int]:
        return {m.keyframe_ordinal for m in self.members}


def _joins(
    member: FrameProposal,
    mask: np.ndarray | None,
    cluster: _Cluster,
    config: SceneConfig,
    diagonal: float,
) -> bool:
    if member.geometry_type == "polygon":
        assert mask is not None
        return any(mask_iou(mask, other) >= config.zone_cluster_iou for other in cluster.masks)
    limit = config.edge_cluster_diagonal_distance * diagonal
    return any(chamfer_distance(member.points, other.points) <= limit for other in cluster.members)


def _simplify(contour: np.ndarray) -> np.ndarray:
    """Largest approxPolyDP tolerance that keeps the area within 2%."""
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    best = contour
    for fraction in (0.002, 0.004, 0.008, 0.016, 0.03):
        approx = cv2.approxPolyDP(contour, fraction * perimeter, True)
        if len(approx) >= 3 and abs(cv2.contourArea(approx) - area) <= _AREA_TOLERANCE * area:
            best = approx
    return best


def _polygon_consensus(cluster: _Cluster, width: int, height: int) -> tuple[Point, ...] | None:
    votes = np.sum(cluster.masks, axis=0)
    agreed = (votes >= len(cluster.masks) / 2).astype(np.uint8)
    contours, _ = cv2.findContours(agreed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = _simplify(max(contours, key=cv2.contourArea))
    points = tuple(
        (float(x) / _RASTER_SCALE, float(y) / _RASTER_SCALE) for x, y in largest.reshape(-1, 2)
    )
    if len(points) < 3 or polygon_area(points) < 1.0:
        return None
    return points


def _medoid(members: Sequence[FrameProposal]) -> FrameProposal:
    if len(members) <= 2:
        return members[0]
    totals = [
        sum(chamfer_distance(a.points, b.points) for b in members if b is not a) for a in members
    ]
    return members[int(np.argmin(totals))]


def _majority(values: Sequence[object], wanted: object) -> bool:
    return sum(1 for v in values if v == wanted) * 2 > len(values)


def _semantics(members: Sequence[FrameProposal]) -> dict[str, object]:
    drops = [m.visible_drop_or_open_side for m in members]
    visibility = [m.protection_visibility for m in members]
    state = [m.protection_state for m in members]
    drop: bool | None = None
    if _majority(drops, True):
        drop = True
    elif _majority(drops, False):
        drop = False
    return {
        "visible_drop_or_open_side": drop,
        "protection_visibility": "sufficient"
        if _majority(visibility, "sufficient")
        else "insufficient"
        if _majority(visibility, "insufficient")
        else "unknown",
        "protection_state": "unguarded_or_inadequate"
        if _majority(state, "unguarded_or_inadequate")
        else "guarded"
        if _majority(state, "guarded")
        else "unknown",
    }


def build_consensus(
    proposals: Sequence[FrameProposal],
    *,
    keyframe_indices: Sequence[int],
    width: int,
    height: int,
    config: SceneConfig,
) -> tuple[list[SceneProposal], list[str]]:
    """Cluster proposals by type and keep those with enough keyframe support."""
    eligible = len(keyframe_indices)
    required = max(
        config.minimum_support_frames, math.ceil(config.minimum_support_fraction * eligible)
    )
    diagonal = math.hypot(width, height)
    results: list[SceneProposal] = []
    rejected: list[str] = []

    for proposal_type in sorted({p.proposal_type for p in proposals}):
        clusters: list[_Cluster] = []
        for member in sorted(
            (p for p in proposals if p.proposal_type == proposal_type),
            key=lambda p: p.keyframe_ordinal,
        ):
            mask = (
                rasterise(member.points, width, height, _RASTER_SCALE)
                if member.geometry_type == "polygon"
                else None
            )
            for cluster in clusters:
                if _joins(member, mask, cluster, config, diagonal):
                    break
            else:
                cluster = _Cluster()
                clusters.append(cluster)
            cluster.members.append(member)
            if mask is not None:
                cluster.masks.append(mask)

        kept: list[tuple[_Cluster, tuple[Point, ...]]] = []
        for cluster in clusters:
            support = len(cluster.keyframes)
            if support < required:
                rejected.append(
                    f"{proposal_type}: supported by {support} of {eligible} keyframes "
                    f"(needs {required})"
                )
                continue
            geometry = (
                _polygon_consensus(cluster, width, height)
                if cluster.members[0].geometry_type == "polygon"
                else _medoid(cluster.members).points
            )
            if geometry is None:
                rejected.append(f"{proposal_type}: consensus region collapsed")
                continue
            kept.append((cluster, geometry))

        # Left-to-right numbering keeps ids stable between runs.
        kept.sort(key=lambda item: float(np.mean([p[0] for p in item[1]])))
        for number, (cluster, geometry) in enumerate(kept, start=1):
            support = sorted(cluster.keyframes)
            rationale = Counter(m.rationale for m in cluster.members if m.rationale)
            results.append(
                SceneProposal(
                    proposal_id=f"{proposal_type}-{number}",
                    proposal_type=proposal_type,  # type: ignore[arg-type]
                    geometry_type=cluster.members[0].geometry_type,  # type: ignore[arg-type]
                    points=geometry,
                    rationale=rationale.most_common(1)[0][0] if rationale else "",
                    source="gemini_consensus",
                    agreement_score=min(1.0, len(support) / eligible),
                    supporting_keyframes=tuple(keyframe_indices[i] for i in support),
                    eligible_keyframes=eligible,
                    **_semantics(cluster.members) if proposal_type == "open_edge" else {},  # type: ignore[arg-type]
                )
            )
    return results, rejected
