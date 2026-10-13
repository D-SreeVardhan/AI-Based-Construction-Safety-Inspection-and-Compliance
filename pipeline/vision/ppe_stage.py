"""Per-frame PPE assessment: two-head classifier + per-track temporal filter.

A person is assessable on a frame only if the box is tall enough and upright (the head and
torso bands assume a standing worker). Assessable people are classified every
`classify_every_frames` frames; in between, the smoothed state is carried forward. Frames
where a person is not assessable report UNKNOWN with ``visible=False`` so a stale verdict
never feeds the rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from pipeline.data.ppe_crops import Box
from pipeline.vision.ppe_model import PPEClassifier, PPEPrediction
from pipeline.vision.ppe_temporal import TemporalPPEFilter
from shared.config import PPEConfig
from shared.coordinates import Box2
from shared.enums import HelmetState, VestState
from shared.schemas.tracks import HelmetRecord, VestRecord

PPERecords = tuple[HelmetRecord, VestRecord]


class _Predictor(Protocol):
    def predict(self, crops: Sequence[np.ndarray]) -> list[PPEPrediction]: ...


class PPEStage:
    def __init__(
        self,
        classifier: _Predictor,
        *,
        alpha: float,
        minimum_observations: int,
        confidence_floor: float,
        minimum_height_px: int,
        minimum_upright_aspect: float,
        classify_every_frames: int,
        model_id: str = "ppe-two-head",
    ) -> None:
        self.classifier = classifier
        self.filter = TemporalPPEFilter(
            alpha=alpha,
            minimum_observations=minimum_observations,
            confidence_floor=confidence_floor,
        )
        self.minimum_height_px = minimum_height_px
        self.minimum_upright_aspect = minimum_upright_aspect
        self.classify_every_frames = classify_every_frames
        self.model_id = model_id
        self.classified_crops = 0
        self._frames_seen = 0

    @classmethod
    def from_config(cls, config: PPEConfig, device: str) -> PPEStage | None:
        """None when no trained weights exist, so callers fall back to Gemini-only PPE."""
        checkpoint = Path(config.model_path)
        if not checkpoint.is_file():
            return None
        return cls(
            PPEClassifier(checkpoint, device, batch_size=config.batch_size),
            alpha=config.temporal_alpha,
            minimum_observations=config.minimum_observations,
            confidence_floor=config.confidence_floor,
            minimum_height_px=config.minimum_person_height_px,
            minimum_upright_aspect=config.minimum_upright_aspect,
            classify_every_frames=config.classify_every_frames,
            model_id=f"effnet-b0-two-head:{checkpoint.parent.name}/{checkpoint.name}",
        )

    def assessable(self, box: Box2) -> bool:
        height = box.y2 - box.y1
        width = max(box.x2 - box.x1, 1e-6)
        return height >= self.minimum_height_px and height / width >= self.minimum_upright_aspect

    def assess(
        self, frame_bgr: np.ndarray, people: Sequence[tuple[str, Box2]]
    ) -> dict[str, PPERecords]:
        """Records for each ``(track_id, box)``; call once per sampled frame, in order."""
        records: dict[str, PPERecords] = {}
        to_classify: list[tuple[str, np.ndarray]] = []
        classify_now = self._frames_seen % self.classify_every_frames == 0
        self._frames_seen += 1
        for track_id, box in people:
            if not self.assessable(box):
                records[track_id] = self.filter.unobserved()
            elif classify_now:
                crop = _padded_crop(frame_bgr, box)
                if crop is None:
                    records[track_id] = self.filter.unobserved()
                else:
                    to_classify.append((track_id, crop))
            else:
                records[track_id] = _hide_stale(*self.filter.current(track_id))

        if to_classify:
            predictions = self.classifier.predict([crop for _, crop in to_classify])
            self.classified_crops += len(predictions)
            for (track_id, _), prediction in zip(to_classify, predictions, strict=True):
                records[track_id] = _hide_stale(*self.filter.update(track_id, prediction))
        return records


def _padded_crop(frame_bgr: np.ndarray, box: Box2) -> np.ndarray | None:
    """Crop with the same context padding the training crops were built with."""
    height, width = frame_bgr.shape[:2]
    padded = Box(box.x1, box.y1, box.x2, box.y2).padded(width, height)
    x1, y1 = int(padded.x1), int(padded.y1)
    x2, y2 = int(round(padded.x2)), int(round(padded.y2))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return frame_bgr[y1:y2, x1:x2]


def _hide_stale(helmet: HelmetRecord, vest: VestRecord) -> PPERecords:
    if not helmet.visible:
        helmet = helmet.model_copy(update={"state": HelmetState.UNKNOWN})
    if not vest.visible:
        vest = vest.model_copy(update={"state": VestState.UNKNOWN})
    return helmet, vest
