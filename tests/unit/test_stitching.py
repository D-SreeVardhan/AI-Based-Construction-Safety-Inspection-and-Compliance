"""Tracklet stitching links one worker across an occlusion, and nothing else."""

from __future__ import annotations

import numpy as np

from pipeline.mapping.stitching import StitchedStore, stitch
from shared.coordinates import Box2, Point2
from shared.enums import PERSON_CLASS, CoordinateSpace
from shared.identity import canonical_track_id
from shared.schemas.tracks import Pass1TrackObservation

FPS = 15.0


def _obs(track: int, t: float, x: float, height: float = 120.0) -> Pass1TrackObservation:
    box = Box2(x1=x - 20, y1=500 - height, x2=x + 20, y2=500, space=CoordinateSpace.REFERENCE)
    return Pass1TrackObservation(
        shot_id="s0",
        frame_index=round(t * FPS),
        video_time_s=t,
        track_id=track,
        canonical_track_id=canonical_track_id("s0", track),
        object_class=PERSON_CLASS,
        box_reference=box,
        anchor_reference=Point2(x=x, y=500, space=CoordinateSpace.REFERENCE),
        confidence=0.9,
    )


def _frames(spans):
    """spans: (track, start_s, end_s, x at start, x speed px/s, height)."""
    frames = {}
    for track, start, end, x0, speed, height in spans:
        for i in range(round(start * FPS), round(end * FPS) + 1):
            t = i / FPS
            frames.setdefault(i, []).append(_obs(track, t, x0 + speed * (t - start), height))
    return [(index, frames[index]) for index in sorted(frames)]


def test_a_worker_reappearing_where_expected_is_one_identity() -> None:
    # Track 1 walks right at 30 px/s, vanishes at 5 s; track 2 appears at 7 s close to
    # where track 1 would be. Track 3 appears at the same moment far across the site.
    frames = _frames(
        [
            (1, 0.0, 5.0, 100, 30, 120),
            (2, 7.0, 10.0, 100 + 30 * 7, 30, 122),
            (3, 7.0, 10.0, 1500, 0, 120),
        ]
    )
    result = stitch(iter(frames))
    one, two, three = (canonical_track_id("s0", n) for n in (1, 2, 3))
    assert result.mapping[two] == one
    assert result.mapping[three] == three
    assert result.tracks_before == 3 and result.tracks_after == 2


def test_tracks_seen_at_the_same_time_are_never_merged() -> None:
    frames = _frames([(1, 0.0, 5.0, 100, 0, 120), (2, 4.0, 9.0, 110, 0, 120)])
    result = stitch(iter(frames))
    assert len(set(result.mapping.values())) == 2


def test_a_different_size_or_long_gap_blocks_the_link() -> None:
    small = _frames([(1, 0.0, 5.0, 100, 0, 120), (2, 6.0, 9.0, 105, 0, 60)])
    assert stitch(iter(small)).tracks_after == 2
    late = _frames([(1, 0.0, 5.0, 100, 0, 120), (2, 20.0, 25.0, 105, 0, 120)])
    assert stitch(iter(late)).tracks_after == 2


def test_different_clothing_vetoes_an_otherwise_good_link() -> None:
    frames = _frames([(1, 0.0, 5.0, 100, 0, 120), (2, 6.0, 9.0, 105, 0, 120)])
    one, two = canonical_track_id("s0", 1), canonical_track_id("s0", 2)
    red, blue = np.zeros(128), np.zeros(128)
    red[0], blue[60] = 1.0, 1.0
    same = {one: (red, red), two: (red, red)}
    different = {one: (red, red), two: (blue, blue)}
    assert stitch(iter(frames), appearance=same).tracks_after == 1
    assert stitch(iter(frames), appearance=different).tracks_after == 2


def test_stitched_view_renames_without_touching_the_store() -> None:
    frames = _frames([(1, 0.0, 1.0, 100, 0, 120), (2, 2.0, 3.0, 105, 0, 120)])

    class Store:
        def frames_with_observations(self):
            return iter(frames)

    one, two = canonical_track_id("s0", 1), canonical_track_id("s0", 2)
    view = StitchedStore(Store(), {one: one, two: one})
    ids = {o.canonical_track_id for _, obs in view.frames_with_observations() for o in obs}
    assert ids == {one}
    assert {o.canonical_track_id for _, obs in frames for o in obs} == {one, two}
