"""Zone health: has the site changed where a zone or edge was drawn? (v3)

Construction sites change weekly, so hand-drawn zones go stale: an exclusion zone around
an excavation that has been backfilled, an edge that now has a guardrail. Commercial
systems keep alerting on yesterday's geometry. Here every run compares the area inside
each zone against the reference frame the zones were drawn on:

* the current view is the per-pixel median of frames sampled across the clip, which
  removes workers and machines passing through;
* both images become gradient-magnitude maps, so lighting and weather matter far less
  than structure (new formwork, removed barriers, filled pits);
* change = 1 - correlation of the two maps inside the zone (0 = identical structure).

Zones above `REVIEW_THRESHOLD` are flagged for review; their alerts still run.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from shared.schemas.scene import GeometryType, SceneProposal

REVIEW_THRESHOLD = 0.5
EDGE_BAND_PX = 40  # an edge is judged on a band around its polyline
DILATE_PX = 12


def median_background(frames: Sequence[np.ndarray]) -> np.ndarray:
    stack = np.stack([f for f in frames if f.shape == frames[0].shape])
    return np.median(stack, axis=0).astype(np.uint8)


def _gradient(image: np.ndarray) -> np.ndarray:
    grey = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (0, 0), 1.5)
    gx = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def _mask(proposal: SceneProposal, shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    points = np.round(np.asarray(proposal.reference_points)).astype(np.int32)
    if proposal.geometry_type is GeometryType.POLYLINE:
        cv2.polylines(mask, [points], False, 255, EDGE_BAND_PX)
    elif proposal.geometry_type is GeometryType.BOX:
        (x1, y1), (x2, y2) = points[:2]
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
    else:
        cv2.fillPoly(mask, [points], 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DILATE_PX + 1, 2 * DILATE_PX + 1))
    return cv2.dilate(mask, kernel) > 0


def zone_change(
    reference: np.ndarray, current: np.ndarray, proposals: Sequence[SceneProposal]
) -> dict[str, float]:
    """{proposal_id: change in [0, 1]} for every zone with enough area to judge."""
    if current.shape != reference.shape:
        current = cv2.resize(current, (reference.shape[1], reference.shape[0]))
    a, b = _gradient(reference), _gradient(current)
    changes: dict[str, float] = {}
    for proposal in proposals:
        mask = _mask(proposal, reference.shape[:2])
        if mask.sum() < 200:
            continue
        x, y = a[mask], b[mask]
        if x.std() < 1e-3 or y.std() < 1e-3:
            continue  # featureless in either image: nothing to compare
        correlation = float(np.corrcoef(x, y)[0, 1])
        changes[proposal.proposal_id] = round(float(np.clip(1.0 - correlation, 0.0, 1.0)), 3)
    return changes
