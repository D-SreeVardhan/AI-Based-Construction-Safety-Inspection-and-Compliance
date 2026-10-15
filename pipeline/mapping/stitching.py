"""Tracklet stitching: one worker, one identity, across occlusions (v3, P4).

ByteTrack keeps a lost track for a few seconds; a worker hidden longer behind formwork
or another worker comes back under a new ID. Every rule keys on the track, so one real
event became several incidents and per-worker exposure was split. This pass links a
track that ends to one that starts shortly after, where that worker would plausibly be:

* gap: the second track starts 0–`MAX_GAP_S` after the first ends (never overlapping);
* place: its first ground-contact point lies within reach of the first track's last
  point, extrapolated with its recent velocity (capped at 1 s) — reach grows with the
  gap at walking speed, measured in person heights so it is scale-free;
* size: box heights agree within `MAX_HEIGHT_RATIO` (the same person, similar depth);
* optional appearance: when pass one stored torso colour histograms, they must agree.

Candidate links are scored and assigned globally (Hungarian, each end and each start used
at most once), so two simultaneous candidates never both claim one track. Gates are
conservative: a missed link only leaves a duplicate; a false link would merge two
people. The pass-one store is never modified; `StitchedStore` presents the mapping.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from shared.enums import PERSON_CLASS
from shared.schemas.tracks import Pass1TrackObservation

MAX_GAP_S = 6.0
VELOCITY_WINDOW_S = 1.0
MAX_EXTRAPOLATION_S = 1.0
REACH_BASE_H = 0.6  # person heights, at zero gap
REACH_PER_S_H = 0.7  # person heights per second of gap (a brisk walk)
MAX_HEIGHT_RATIO = 1.35
MIN_TRACK_OBSERVATIONS = 3
MAX_APPEARANCE_DISTANCE = 0.5  # Bhattacharyya; calibrated on SARD 9 links judged by eye
ACCEPT_COST = 1.0


@dataclass
class _Track:
    track_id: str
    shot_id: str
    times: list[float] = field(default_factory=list)
    anchors: list[tuple[float, float]] = field(default_factory=list)
    heights: list[float] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.times[0]

    @property
    def end(self) -> float:
        return self.times[-1]

    def edge(self, at_end: bool) -> tuple[np.ndarray, float, np.ndarray]:
        """(anchor, height, velocity per second) over the first or last second."""
        times = np.asarray(self.times)
        anchors = np.asarray(self.anchors)
        heights = np.asarray(self.heights)
        if at_end:
            window = times >= self.end - VELOCITY_WINDOW_S
        else:
            window = times <= self.start + VELOCITY_WINDOW_S
        t, a = times[window], anchors[window]
        velocity = np.zeros(2)
        if len(t) >= 2 and t[-1] > t[0]:
            velocity = (a[-1] - a[0]) / (t[-1] - t[0])
        point = anchors[-1] if at_end else anchors[0]
        return point, float(np.median(heights[window])), velocity


@dataclass(frozen=True)
class StitchResult:
    mapping: dict[str, str]  # track id -> identity (the chain's first track)
    links: list[tuple[str, str, float]]  # (earlier, later, cost)
    tracks_before: int
    tracks_after: int


def _bhattacharyya(a: np.ndarray, b: np.ndarray) -> float:
    a = a / max(a.sum(), 1e-9)
    b = b / max(b.sum(), 1e-9)
    return float(np.sqrt(max(0.0, 1.0 - np.sum(np.sqrt(a * b)))))


def stitch(
    frames: Iterator[tuple[object, list[Pass1TrackObservation]]],
    *,
    appearance: Mapping[str, tuple[np.ndarray, np.ndarray]] | None = None,
) -> StitchResult:
    """Link fragmented person tracks. `appearance`: track -> (start hist, end hist)."""
    tracks: dict[str, _Track] = {}
    for _, observations in frames:
        for o in observations:
            if o.object_class != PERSON_CLASS or o.interpolated:
                continue
            track = tracks.setdefault(o.canonical_track_id, _Track(o.canonical_track_id, o.shot_id))
            box = o.box_oriented or o.box_reference
            track.times.append(o.video_time_s)
            track.anchors.append((o.anchor_reference.x, o.anchor_reference.y))
            track.heights.append(box.y2 - box.y1)
    usable = [t for t in tracks.values() if len(t.times) >= MIN_TRACK_OBSERVATIONS]
    ends = sorted(usable, key=lambda t: t.end)
    starts = sorted(usable, key=lambda t: t.start)
    cost = np.full((len(ends), len(starts)), np.inf)
    for i, a in enumerate(ends):
        a_point, a_height, a_velocity = a.edge(at_end=True)
        for j, b in enumerate(starts):
            gap = b.start - a.end
            if b is a or a.shot_id != b.shot_id or not 0.0 < gap <= MAX_GAP_S:
                continue
            b_point, b_height, _ = b.edge(at_end=False)
            ratio = max(a_height, b_height) / max(min(a_height, b_height), 1e-6)
            if ratio > MAX_HEIGHT_RATIO:
                continue
            scale = (a_height + b_height) / 2
            predicted = a_point + a_velocity * min(gap, MAX_EXTRAPOLATION_S)
            distance = float(np.linalg.norm(b_point - predicted)) / scale
            reach = REACH_BASE_H + REACH_PER_S_H * gap
            if distance > reach:
                continue
            score = distance / reach + 0.05 * gap + 0.5 * (ratio - 1.0)
            if appearance and a.track_id in appearance and b.track_id in appearance:
                d = _bhattacharyya(appearance[a.track_id][1], appearance[b.track_id][0])
                if d > MAX_APPEARANCE_DISTANCE:
                    continue
                score += d
            cost[i, j] = score
    links: list[tuple[str, str, float]] = []
    if np.isfinite(cost).any():
        filled = np.where(np.isfinite(cost), cost, 1e6)
        rows, cols = linear_sum_assignment(filled)
        for i, j in zip(rows, cols, strict=True):
            if cost[i, j] <= ACCEPT_COST:
                links.append((ends[i].track_id, starts[j].track_id, round(float(cost[i, j]), 3)))
    successor = {a: b for a, b, _ in links}
    predecessor = {b: a for a, b, _ in links}
    mapping: dict[str, str] = {}
    for track_id in tracks:
        if track_id in predecessor:
            continue
        current = track_id
        while current is not None and current not in mapping:
            mapping[current] = track_id
            current = successor.get(current)
    for track_id in tracks:
        mapping.setdefault(track_id, track_id)
    return StitchResult(
        mapping=mapping,
        links=links,
        tracks_before=len(tracks),
        tracks_after=len(set(mapping.values())),
    )


APPEARANCE_FRAMES = 3  # observations averaged at each end of a track


def _descriptor(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
    """Clothing colour: hue-saturation histograms of torso and legs (helmets look alike)."""
    import cv2

    x1, y1, x2, y2 = box
    height, width = y2 - y1, x2 - x1
    if height < 24 or width < 8:
        return None
    cx1, cx2 = x1 + int(0.15 * width), x2 - int(0.15 * width)
    parts = []
    for top, bottom in ((0.22, 0.58), (0.58, 0.95)):
        region = image[
            max(0, y1 + int(top * height)) : y1 + int(bottom * height), max(0, cx1) : cx2
        ]
        if region.size == 0:
            return None
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 4], [0, 180, 0, 256]).flatten()
        parts.append(hist / max(hist.sum(), 1e-9))
    return np.concatenate(parts)


def appearance_from_video(
    video, frames, canvas: tuple[int, int] = (1920, 1080)
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """track -> (descriptor at its start, descriptor at its end), from the source video.

    Only the few frames at each end of every person track are decoded (one sequential
    pass), so this works on any stored run without touching pass one.
    """
    import cv2

    track_obs: dict[str, list] = {}
    for record, observations in frames:
        for o in observations:
            if o.object_class == PERSON_CLASS and not o.interpolated:
                track_obs.setdefault(o.canonical_track_id, []).append((record.source_index, o))
    wanted: dict[int, list] = {}
    for track_id, rows in track_obs.items():
        for side, chosen in ((0, rows[:APPEARANCE_FRAMES]), (1, rows[-APPEARANCE_FRAMES:])):
            for source_index, o in chosen:
                wanted.setdefault(source_index, []).append((track_id, side, o))
    sums: dict[tuple[str, int], list[np.ndarray]] = {}
    capture = cv2.VideoCapture(str(video))
    index, last = -1, max(wanted, default=-1)
    while index < last:
        if not capture.grab():
            break
        index += 1
        if index not in wanted:
            continue
        ok, raw = capture.retrieve()
        if not ok:
            continue
        scale = min(canvas[0] / raw.shape[1], canvas[1] / raw.shape[0])
        ox, oy = (canvas[0] - raw.shape[1] * scale) / 2, (canvas[1] - raw.shape[0] * scale) / 2
        for track_id, side, o in wanted[index]:
            b = o.box_oriented or o.box_reference
            box = (
                int((b.x1 - ox) / scale),
                int((b.y1 - oy) / scale),
                int((b.x2 - ox) / scale),
                int((b.y2 - oy) / scale),
            )
            descriptor = _descriptor(raw, box)
            if descriptor is not None:
                sums.setdefault((track_id, side), []).append(descriptor)
    capture.release()
    result = {}
    for track_id in track_obs:
        start, end = sums.get((track_id, 0)), sums.get((track_id, 1))
        if start and end:
            result[track_id] = (np.mean(start, axis=0), np.mean(end, axis=0))
    return result


class StitchedStore:
    """A read view of a pass-one store with person tracks renamed to their identity."""

    def __init__(self, store, mapping: Mapping[str, str]) -> None:
        self._store = store
        self._mapping = dict(mapping)

    def _rename(self, observation: Pass1TrackObservation) -> Pass1TrackObservation:
        identity = self._mapping.get(observation.canonical_track_id)
        if identity is None or identity == observation.canonical_track_id:
            return observation
        return observation.model_copy(update={"canonical_track_id": identity})

    def frames_with_observations(self):
        for record, observations in self._store.frames_with_observations():
            yield record, [self._rename(o) for o in observations]

    def observations_for(self, canonical_track_id: str) -> list[Pass1TrackObservation]:
        members = [t for t, identity in self._mapping.items() if identity == canonical_track_id]
        rows = [o for t in members or [canonical_track_id] for o in self._store.observations_for(t)]
        return [self._rename(o) for o in sorted(rows, key=lambda o: o.frame_index)]

    def __getattr__(self, name: str):
        return getattr(self._store, name)
