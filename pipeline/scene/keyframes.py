"""Keyframe selection for the scene bootstrap (v7 §39.1).

Keyframes cover the clip uniformly, preferring frames that show both people and machinery,
and drop frames too blurred to propose geometry from.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.intake import FrameSampler
from shared.schemas.tracks import Pass1TrackObservation

SELECTOR_VERSION = "uniform-bins-v1"


@dataclass(frozen=True)
class Keyframe:
    frame_index: int
    video_time_s: float
    image_bgr: np.ndarray
    sha256: str
    sharpness: float


def sharpness(image_bgr: np.ndarray) -> float:
    """Variance of the Laplacian: low means blurred."""
    return float(cv2.Laplacian(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def frame_hash(image_bgr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(image_bgr).tobytes()).hexdigest()


def candidate_indices(
    observations: Sequence[Pass1TrackObservation], total_samples: int, count: int
) -> list[int]:
    """One sample index per equal time bin, favouring frames with people and machinery."""
    if total_samples <= 0 or count <= 0:
        return []
    people: dict[int, int] = defaultdict(int)
    machines: dict[int, int] = defaultdict(int)
    for obs in observations:
        target = people if obs.object_class == "person" else machines
        target[obs.frame_index] += 1
    detected = sorted(set(people) | set(machines))

    chosen: list[int] = []
    for bin_index in range(count):
        start = bin_index * total_samples // count
        stop = max(start + 1, (bin_index + 1) * total_samples // count)
        centre = (start + stop - 1) / 2
        in_bin = [i for i in detected if start <= i < stop]
        if in_bin:
            pick = max(
                in_bin,
                key=lambda i: (min(people[i], 3) + 2 * (machines[i] > 0), -abs(i - centre)),
            )
        else:
            pick = round(centre)
        chosen.append(min(pick, total_samples - 1))
    return sorted(set(chosen))


def select_keyframes(
    sampler: FrameSampler,
    observations: Sequence[Pass1TrackObservation],
    *,
    count: int,
    minimum_sharpness: float,
) -> tuple[list[Keyframe], list[str]]:
    """Read and filter keyframes; the second item lists why candidates were dropped."""
    wanted = candidate_indices(observations, sampler.sample_count(), count)
    frames = sampler.frames_at(wanted)
    keyframes: list[Keyframe] = []
    dropped: list[str] = []
    for index in wanted:
        if index not in frames:
            dropped.append(f"frame {index}: could not be read")
            continue
        time_s, image = frames[index]
        score = sharpness(image)
        if score < minimum_sharpness:
            dropped.append(f"frame {index}: blurred (sharpness {score:.1f})")
            continue
        keyframes.append(Keyframe(index, time_s, image, frame_hash(image), score))
    return keyframes, dropped
