"""Machinery contact footprint and operating state (v7 §38).

Only the bottom edge of a machine's box is ever mapped to the ground: upper corners sit
above the plane and would land far from the machine. The footprint is the bottom contact
segment inflated by a project-defined margin in Worker-Heights.

Operating state here is motion-based. Without an articulation measure a machine that is not
translating cannot be called stationary (a boom may still swing), so it stays UNKNOWN.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from pipeline.geometry.plane import PlaneEnsemble
from shared.config import RulesConfig
from shared.enums import OperatingState
from shared.schemas.tracks import Pass1TrackObservation

_EDGE_MARGIN_PX = 3.0
_MIN_WINDOW_POINTS = 4
_MIN_VALID_FRACTION = 0.70


def contact_pixels(obs: Pass1TrackObservation) -> np.ndarray:
    """Bottom-left and bottom-right box corners as ``(2, 2)`` pixels."""
    box = obs.box_reference
    return np.array([[box.x1, box.y2], [box.x2, box.y2]])


def contact_visible(obs: Pass1TrackObservation, content_bottom: float) -> bool:
    """False when the box runs off the bottom of the image, so the contact is cut off."""
    return obs.box_reference.y2 <= content_bottom - _EDGE_MARGIN_PX


def operating_states(
    observations: Sequence[Pass1TrackObservation],
    ensemble: PlaneEnsemble,
    config: RulesConfig,
) -> dict[int, OperatingState]:
    """Operating state of one machine at each of its observations, keyed by frame index."""
    ordered = sorted(observations, key=lambda o: o.video_time_s)
    centres = np.array(
        [[(o.box_reference.x1 + o.box_reference.x2) / 2, o.box_reference.y2] for o in ordered]
    )
    ground = ensemble.ground(centres) if len(ordered) else np.empty((0, 2))
    times = np.array([o.video_time_s for o in ordered])
    window = config.r4_state_window_seconds

    states: dict[int, OperatingState] = {}
    for i, obs in enumerate(ordered):
        members = np.flatnonzero((times >= times[i] - window) & (times <= times[i]))
        valid = members[np.isfinite(ground[members]).all(axis=1)]
        if len(valid) < _MIN_WINDOW_POINTS or len(valid) / len(members) < _MIN_VALID_FRACTION:
            states[obs.frame_index] = OperatingState.UNKNOWN
            continue
        third = max(1, len(valid) // 3)
        start, end = (
            np.median(ground[valid[:third]], axis=0),
            np.median(ground[valid[-third:]], axis=0),
        )
        elapsed = float(np.mean(times[valid[-third:]]) - np.mean(times[valid[:third]]))
        displacement = float(np.linalg.norm(end - start))
        speed = displacement / elapsed if elapsed > 0 else 0.0
        moving = (
            speed >= config.r4_active_speed_wh_s or displacement >= config.r4_active_displacement_wh
        )
        states[obs.frame_index] = OperatingState.ACTIVE if moving else OperatingState.UNKNOWN
    return states
