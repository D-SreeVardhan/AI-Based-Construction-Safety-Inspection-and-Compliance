from __future__ import annotations

from pathlib import Path

import numpy as np

from jobs.pipeline_job import RealPipelineJob, _sha256_file, fingerprint_input
from pipeline.vision import PersonCrop
from shared.config import load_config
from shared.coordinates import Box2, Point2
from shared.enums import CoordinateSpace, HelmetState, ProcessingStatus, VestState
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation, VestRecord


def test_fingerprint_full_for_small_files(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"tiny-input")
    digest, complete = fingerprint_input(path, full_below_bytes=64)
    assert complete is True
    assert digest == _sha256_file(path)


def test_fingerprint_samples_large_files(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"HEAD" + b"x" * 24 + b"TAIL")
    digest, complete = fingerprint_input(path, full_below_bytes=8, sample_bytes=4)
    assert complete is False
    assert digest != _sha256_file(path)
    again, _ = fingerprint_input(path, full_below_bytes=8, sample_bytes=4)
    assert again == digest


def test_real_pipeline_no_gemini_key_completes_with_unknown_ppe(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"not-a-real-video")

    class FakeStage1Detector:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def detect_and_track(self, *_args, **_kwargs):
            box = Box2(x1=0.0, y1=0.0, x2=80.0, y2=160.0, space=CoordinateSpace.REFERENCE)
            obs = Pass1TrackObservation(
                shot_id="shot-0",
                frame_index=0,
                video_time_s=0.0,
                track_id=1,
                canonical_track_id="shot-0/person-1",
                object_class="person",
                box_reference=box,
                anchor_reference=Point2(x=40.0, y=160.0, space=CoordinateSpace.REFERENCE),
                helmet=HelmetRecord(state=HelmetState.UNKNOWN, confidence=0.0, visible=True),
                vest=VestRecord(state=VestState.UNKNOWN, confidence=0.0, visible=True),
            )
            crop = PersonCrop(
                canonical_track_id="shot-0/person-1",
                frame_index=0,
                video_time_s=0.0,
                box=box,
                crop_bgr=np.zeros((80, 40, 3), dtype=np.uint8),
            )
            return [obs], [crop]

    class ExplodingAdjudicator:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("adjudicator should not be constructed without key")

    monkeypatch.setattr("jobs.pipeline_job.Stage1Detector", FakeStage1Detector)
    monkeypatch.setattr("jobs.pipeline_job.GeminiPPEAdjudicator", ExplodingAdjudicator)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    config = load_config()
    manifest = RealPipelineJob(
        input_path,
        output_root=tmp_path / "output",
        config=config,
        run_id="run-no-key",
        skip_video=True,
        gemini_api_key="",
    ).run()

    assert manifest.status == ProcessingStatus.COMPLETED
    assert manifest.gemini_status == "no_key"
    tracks = (tmp_path / "output" / "run-no-key" / "tracks.jsonl").read_text(encoding="utf-8")
    assert '"state":"unknown"' in tracks
