from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from jobs.pipeline_job import (
    FakePipelineJob,
    RealPipelineJob,
    _sha256_file,
    create_pipeline_job,
    fingerprint_input,
)
from llm.adjudicator import AdjudicationResult
from pipeline.vision import PersonCrop
from shared.config import load_config
from shared.coordinates import Box2, Point2
from shared.enums import CoordinateSpace, HelmetState, ProcessingStatus, VestState
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation, VestRecord


def test_fingerprint_full_for_small_files(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc" * 100)
    digest, complete = fingerprint_input(path, full_below_bytes=10_000)
    assert complete is True
    assert digest == _sha256_file(path)


def test_fingerprint_samples_large_files(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 5000)
    digest, complete = fingerprint_input(path, full_below_bytes=1000, sample_bytes=100)
    assert complete is False
    again, _ = fingerprint_input(path, full_below_bytes=1000, sample_bytes=100)
    assert again == digest


class _OneWorkerDetector:
    """Stage-1 stub: one person track observed for 2 s with a single PPE crop at t=0."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def detect_and_track(self, *_args, **_kwargs):
        box = Box2(x1=0.0, y1=0.0, x2=80.0, y2=160.0, space=CoordinateSpace.REFERENCE)
        observations = [
            Pass1TrackObservation(
                shot_id="shot-0",
                frame_index=frame,
                video_time_s=frame / 15.0,
                track_id=1,
                canonical_track_id="shot-0/person-1",
                object_class="person",
                box_reference=box,
                anchor_reference=Point2(x=40.0, y=160.0, space=CoordinateSpace.REFERENCE),
                helmet=HelmetRecord(state=HelmetState.UNKNOWN, confidence=0.0, visible=True),
                vest=VestRecord(state=VestState.UNKNOWN, confidence=0.0, visible=True),
            )
            for frame in range(0, 30, 3)
        ]
        crop = PersonCrop(
            canonical_track_id="shot-0/person-1",
            frame_index=0,
            video_time_s=0.0,
            box=box,
            crop_bgr=np.zeros((80, 40, 3), dtype=np.uint8),
        )
        return observations, [crop]


def _run_real(tmp_path: Path, run_id: str, *, gemini_api_key: str) -> RealPipelineJob:
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"not-a-real-video")
    return RealPipelineJob(
        input_path,
        output_root=tmp_path / "output",
        config=load_config(),
        run_id=run_id,
        skip_video=True,
        gemini_api_key=gemini_api_key,
    )


def _tracks(job: RealPipelineJob) -> list[dict]:
    lines = (job.run_dir / "tracks.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_real_pipeline_no_gemini_key_completes_with_unknown_ppe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExplodingAdjudicator:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("adjudicator should not be constructed without key")

    monkeypatch.setattr("jobs.pipeline_job.Stage1Detector", _OneWorkerDetector)
    monkeypatch.setattr("jobs.pipeline_job.GeminiPPEAdjudicator", ExplodingAdjudicator)

    job = _run_real(tmp_path, "run-no-key", gemini_api_key="")
    manifest = job.run()

    assert manifest.status == ProcessingStatus.COMPLETED
    assert manifest.gemini_status == "no_key"
    assert all(t["helmet"]["state"] == "unknown" for t in _tracks(job))


def test_real_pipeline_applies_adjudication_to_frozen_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoHelmetAdjudicator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def assess(self, _crop) -> AdjudicationResult:
            return AdjudicationResult(
                helmet=HelmetRecord(state=HelmetState.NO_HELMET, confidence=0.95, visible=True),
                vest=VestRecord(state=VestState.NO_VEST, confidence=0.9, visible=True),
                raw_json="{}",
                latency_ms=1,
                cached=False,
            )

    monkeypatch.setattr("jobs.pipeline_job.Stage1Detector", _OneWorkerDetector)
    monkeypatch.setattr("jobs.pipeline_job.GeminiPPEAdjudicator", NoHelmetAdjudicator)

    job = _run_real(tmp_path, "run-adjudicated", gemini_api_key="test-key")
    manifest = job.run()

    assert manifest.status == ProcessingStatus.COMPLETED
    states = [t["helmet"]["state"] for t in _tracks(job)]
    assert "no_helmet" in states
    assert not any("PPE assessment failed" in w for w in manifest.warnings)


def test_real_pipeline_warns_when_adjudication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class QuotaAdjudicator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def assess(self, _crop) -> AdjudicationResult:
            return AdjudicationResult(
                helmet=HelmetRecord(state=HelmetState.UNKNOWN, confidence=0.0, visible=False),
                vest=VestRecord(state=VestState.UNKNOWN, confidence=0.0, visible=False),
                raw_json='{"error": "429"}',
                latency_ms=1,
                cached=False,
                error="Gemini gemini-2.5-flash failed 429: quota",
            )

    monkeypatch.setattr("jobs.pipeline_job.Stage1Detector", _OneWorkerDetector)
    monkeypatch.setattr("jobs.pipeline_job.GeminiPPEAdjudicator", QuotaAdjudicator)

    job = _run_real(tmp_path, "run-quota", gemini_api_key="test-key")
    manifest = job.run()

    assert manifest.gemini_status == "failed"
    warning = next(w for w in manifest.warnings if "PPE assessment failed" in w)
    assert "1 of 1 crops" in warning
    assert "429" in warning
    report = (job.run_dir / "report.html").read_text(encoding="utf-8")
    assert "PPE assessment failed" in report


def test_create_pipeline_job_selects_by_gemini_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    assert isinstance(create_pipeline_job(clip, output_root=tmp_path), FakePipelineJob)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert isinstance(create_pipeline_job(clip, output_root=tmp_path), RealPipelineJob)
    forced = create_pipeline_job(clip, output_root=tmp_path, force_fake=True)
    assert isinstance(forced, FakePipelineJob)
