from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from shared.config import Stage1Config, TrackerConfig
from shared.coordinates import Box2, Point2
from shared.enums import CoordinateSpace, HelmetState, VestState
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation, VestRecord

if TYPE_CHECKING:
    from pipeline.intake import FrameSampler
    from pipeline.vision.ppe_stage import PPEStage

try:
    from ultralytics import YOLO as _YOLO

    _HAS_ULTRALYTICS = True
except ImportError:
    _YOLO = None  # type: ignore[assignment,misc]
    _HAS_ULTRALYTICS = False

# COCO class indices relevant to construction sites
_PERSON_CLS = 0
_VEHICLE_CLS: frozenset[int] = frozenset({1, 2, 3, 5, 6, 7, 8})
_MIN_CROP_PX = 40  # minimum bounding-box side length to extract a crop
_UNKNOWN_PPE = (
    HelmetRecord(state=HelmetState.UNKNOWN, confidence=0.0, visible=True),
    VestRecord(state=VestState.UNKNOWN, confidence=0.0, visible=True),
)


@dataclass
class PersonCrop:
    """A letterboxed person crop extracted for PPE adjudication."""

    canonical_track_id: str
    frame_index: int
    video_time_s: float
    box: Box2
    crop_bgr: np.ndarray


def _extract_crop(frame: np.ndarray, box: Box2) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1 = max(0, int(box.x1))
    y1 = max(0, int(box.y1))
    x2 = min(w, int(box.x2))
    y2 = min(h, int(box.y2))
    if (x2 - x1) < _MIN_CROP_PX or (y2 - y1) < _MIN_CROP_PX:
        return None
    return frame[y1:y2, x1:x2].copy()


class Stage1Detector:
    """YOLO11n person + vehicle detector with ByteTrack on MPS/CPU.

    With a ``PPEStage``, helmet and vest states come from the two-head classifier and
    temporal filter; without one they stay UNKNOWN for the Gemini adjudicator to fill in.
    One crop per person per *ppe_sample_interval_s* is returned either way, for Gemini
    adjudication or verification, to keep API call counts bounded.
    """

    def __init__(
        self,
        config: Stage1Config,
        tracker_config: TrackerConfig,
        *,
        shot_id: str = "shot-0",
    ) -> None:
        if not _HAS_ULTRALYTICS:
            raise ImportError(
                "ultralytics is required for Stage1Detector. Install with: uv sync --extra vision"
            )
        self.config = config
        self.tracker_config = tracker_config
        self.shot_id = shot_id
        self._model = self._load_model(Path(config.model_path))

    @staticmethod
    def _load_model(model_path: Path) -> _YOLO:  # type: ignore[return]
        if model_path.exists():
            return _YOLO(str(model_path))
        model_path.parent.mkdir(parents=True, exist_ok=True)
        # Ultralytics only auto-downloads paths whose filename is a known asset name,
        # so fetch into the gitignored model dir under that name, then copy.
        pretrained = model_path.parent / "yolo11n.pt"
        model = _YOLO(str(pretrained))
        if pretrained.exists():
            shutil.copy2(pretrained, model_path)
        return model

    def detect_and_track(
        self,
        sampler: FrameSampler,
        *,
        ppe_sample_interval_s: float = 3.0,
        max_frames: int | None = None,
        ppe_stage: PPEStage | None = None,
    ) -> tuple[list[Pass1TrackObservation], list[PersonCrop]]:
        """Run detection and ByteTrack over *sampler*.

        Returns ``(observations, crops_for_adjudication)``.
        Without *ppe_stage*, observations have helmet/vest = UNKNOWN until the adjudicator
        runs. crops_for_adjudication holds at most one crop per person per
        *ppe_sample_interval_s* to bound Gemini API usage.
        """
        observations: list[Pass1TrackObservation] = []
        crops: list[PersonCrop] = []
        last_crop_t: dict[int, float] = {}

        for frame_index, video_time_s, frame_bgr in sampler:
            if max_frames is not None and frame_index >= max_frames:
                break
            results = self._model.track(
                frame_bgr,
                persist=True,
                tracker="bytetrack.yaml",
                conf=self.config.confidence,
                iou=self.config.iou,
                imgsz=self.config.image_size,
                device=self.config.device,
                verbose=False,
                classes=[_PERSON_CLS, *_VEHICLE_CLS],
            )
            if not results:
                continue
            boxes = results[0].boxes
            if boxes is None or boxes.id is None:
                continue

            detections: list[tuple[int, bool, str, Box2]] = []
            for i in range(len(boxes)):
                track_id = int(boxes.id[i])
                is_person = int(boxes.cls[i]) == _PERSON_CLS
                object_class = "person" if is_person else "vehicle"
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
                box = Box2(x1=x1, y1=y1, x2=x2, y2=y2, space=CoordinateSpace.REFERENCE)
                detections.append(
                    (track_id, is_person, f"{self.shot_id}/{object_class}-{track_id}", box)
                )
            ppe = (
                ppe_stage.assess(
                    frame_bgr,
                    [(canonical, box) for _, is_person, canonical, box in detections if is_person],
                )
                if ppe_stage is not None
                else {}
            )

            for track_id, is_person, canonical, box in detections:
                object_class = "person" if is_person else "vehicle"
                anchor = Point2(x=(box.x1 + box.x2) / 2, y=box.y2, space=CoordinateSpace.REFERENCE)
                helmet, vest = ppe.get(canonical, _UNKNOWN_PPE) if is_person else (None, None)

                obs = Pass1TrackObservation(
                    shot_id=self.shot_id,
                    frame_index=frame_index,
                    video_time_s=video_time_s,
                    track_id=track_id,
                    canonical_track_id=canonical,
                    object_class=object_class,
                    box_reference=box,
                    anchor_reference=anchor,
                    helmet=helmet,
                    vest=vest,
                )
                observations.append(obs)

                if is_person:
                    prev_t = last_crop_t.get(track_id, -999.0)
                    if video_time_s - prev_t >= ppe_sample_interval_s:
                        crop = _extract_crop(frame_bgr, box)
                        if crop is not None:
                            crops.append(
                                PersonCrop(
                                    canonical_track_id=canonical,
                                    frame_index=frame_index,
                                    video_time_s=video_time_s,
                                    box=box,
                                    crop_bgr=crop,
                                )
                            )
                            last_crop_t[track_id] = video_time_s

        return observations, crops
