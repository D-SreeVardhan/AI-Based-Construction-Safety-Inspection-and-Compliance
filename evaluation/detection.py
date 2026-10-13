"""Box-detection metrics for comparing stage-1 detectors (v7 §34.4).

Matching is greedy by descending confidence at IoU >= 0.5 against unmatched ground truth,
the PASCAL-VOC rule; AP is the all-point interpolated area under the precision-recall curve.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

Box = tuple[float, float, float, float]  # x1, y1, x2, y2
IOU_MATCH = 0.5


@dataclass(frozen=True)
class Detection:
    image_id: str
    confidence: float
    box: Box


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(detections: Sequence[Detection], truth: Mapping[str, Sequence[Box]]) -> list[bool]:
    """True-positive flag per detection, in descending-confidence order."""
    taken: dict[str, set[int]] = {}
    flags = []
    for det in sorted(detections, key=lambda d: -d.confidence):
        best, best_iou = -1, IOU_MATCH
        for index, box in enumerate(truth.get(det.image_id, ())):
            if index in taken.get(det.image_id, set()):
                continue
            overlap = iou(det.box, box)
            if overlap >= best_iou:
                best, best_iou = index, overlap
        if best >= 0:
            taken.setdefault(det.image_id, set()).add(best)
        flags.append(best >= 0)
    return flags


def average_precision(detections: Sequence[Detection], truth: Mapping[str, Sequence[Box]]) -> float:
    total = sum(len(boxes) for boxes in truth.values())
    if total == 0:
        return float("nan")
    flags = match(detections, truth)
    tp = fp = 0
    points: list[tuple[float, float]] = []  # (recall, precision)
    for flag in flags:
        tp, fp = tp + flag, fp + (not flag)
        points.append((tp / total, tp / (tp + fp)))
    area, previous_recall = 0.0, 0.0
    for index, (recall, _) in enumerate(points):
        envelope = max(p for _, p in points[index:])
        area += (recall - previous_recall) * envelope
        previous_recall = recall
    return area


def precision_recall(
    detections: Sequence[Detection], truth: Mapping[str, Sequence[Box]], threshold: float
) -> tuple[float, float]:
    """Precision and recall using only detections at or above ``threshold``."""
    total = sum(len(boxes) for boxes in truth.values())
    kept = [d for d in detections if d.confidence >= threshold]
    hits = sum(match(kept, truth))
    precision = hits / len(kept) if kept else float("nan")
    return precision, (hits / total if total else float("nan"))
