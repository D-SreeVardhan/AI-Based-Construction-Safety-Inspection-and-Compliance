from __future__ import annotations

from shared.coordinates import StrictModel
from shared.schemas.tracks import HelmetRecord, VestRecord


class AdjudicationRecord(StrictModel):
    """Gemini Vision PPE assessment for a single person crop.

    Stored alongside incident records; never mutates an existing IncidentRecord.
    """

    schema_version: int = 1
    record_id: str
    run_id: str
    canonical_track_id: str
    frame_index: int
    video_time_s: float
    crop_path: str  # relative to run_dir
    gemini_model: str
    prompt_version: str
    helmet: HelmetRecord
    vest: VestRecord
    latency_ms: int
    cached: bool
    raw_json: str
