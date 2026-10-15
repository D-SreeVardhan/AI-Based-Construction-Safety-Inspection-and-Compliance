"""Privacy by default: pixelate workers' faces in everything the pipeline exports.

Worker monitoring is regulated (GDPR / India's DPDP Act; the EU AI Act lists workplace
monitoring as high-risk), and a safety tool has no use for identity. Blurring whole
heads would also hide the hard hat that R1 is about, so only the *face band* is
pixelated: below the helmet line, the central part of an upright worker's box.

The band comes from body proportions, not a face detector: a standing adult's head is
about 1/7.5 of their height; the hard hat covers roughly its upper 40 %. Workers too
small to be identifiable (under `MIN_HEIGHT_PX` on the 1080p canvas) are left alone, and
so are crouching or bent-over workers (aspect below `MIN_UPRIGHT_ASPECT`), whose face
is rarely visible and whose head position the box does not tell.
"""

from __future__ import annotations

from collections.abc import Iterable

import cv2
import numpy as np

from shared.enums import PERSON_CLASS
from shared.schemas.tracks import Pass1TrackObservation

MIN_HEIGHT_PX = 70.0
MIN_UPRIGHT_ASPECT = 1.8
HEAD_FRACTION = 1 / 7.5
FACE_TOP = 0.38  # of the head height, below the box top (under the helmet brim)
FACE_BOTTOM = 1.15  # chin, slightly below the head-height estimate
FACE_WIDTH = 0.62  # of the box width, centred
BLOCKS = 4  # pixelation blocks across the face


def face_band(
    box: tuple[float, float, float, float], *, scale: float = 1.0
) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    if height * scale < MIN_HEIGHT_PX or height < MIN_UPRIGHT_ASPECT * width:
        return None
    head = height * HEAD_FRACTION
    cx = (x1 + x2) / 2
    half = width * FACE_WIDTH / 2
    return (
        round((cx - half) * scale),
        round((y1 + FACE_TOP * head) * scale),
        round((cx + half) * scale),
        round((y1 + FACE_BOTTOM * head) * scale),
    )


def pixelate(image: np.ndarray, rect: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = rect
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    region = image[y1:y2, x1:x2]
    small = cv2.resize(
        region,
        (BLOCKS, max(1, round(BLOCKS * (y2 - y1) / (x2 - x1)))),
        interpolation=cv2.INTER_AREA,
    )
    image[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)


def anonymise(
    image: np.ndarray,
    observations: Iterable[Pass1TrackObservation],
    *,
    scale: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """A copy of `image` with every eligible worker's face band pixelated.

    Boxes are on the reference canvas; `scale` and `offset` map them into `image`
    (for original-resolution frames and crops).
    """
    out = image.copy()
    for observation in observations:
        if observation.object_class != PERSON_CLASS:
            continue
        b = observation.box_oriented or observation.box_reference
        band = face_band((b.x1, b.y1, b.x2, b.y2), scale=scale)
        if band is None:
            continue
        x1, y1, x2, y2 = band
        pixelate(
            out,
            (
                x1 - round(offset[0]),
                y1 - round(offset[1]),
                x2 - round(offset[0]),
                y2 - round(offset[1]),
            ),
        )
    return out
