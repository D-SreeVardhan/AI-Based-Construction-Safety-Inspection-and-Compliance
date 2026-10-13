"""Debounce windows shared by the per-track rules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from shared.schemas.tracks import Pass1TrackObservation

T = TypeVar("T", bound=Pass1TrackObservation)


def longest_window(observations: Sequence[T], max_gap_s: float) -> tuple[T, T, float] | None:
    """Longest run of time-ordered observations with no gap above ``max_gap_s``.

    Returns ``(first, last, span_s)``, or None for an empty input. Gaps shorter than the
    tolerance are bridged so a detector missing a frame does not reset the debounce.
    """
    ordered = sorted(observations, key=lambda o: o.video_time_s)
    if not ordered:
        return None
    start = end = ordered[0]
    best = (start, end, 0.0)
    for item in ordered[1:]:
        if item.video_time_s - end.video_time_s <= max_gap_s:
            end = item
        else:
            start = end = item
        span = end.video_time_s - start.video_time_s
        if span > best[2]:
            best = (start, end, span)
    return best
