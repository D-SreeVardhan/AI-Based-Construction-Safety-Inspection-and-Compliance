from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from jobs.pipeline_job import FakePipelineJob


@pytest.fixture()
def tiny_input(tmp_path: Path) -> Path:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"not-a-real-video-but-hashed-as-input")
    return path


def test_fake_pipeline_skip_video(tiny_input: Path, tmp_path: Path) -> None:
    out = tmp_path / "output"
    job = FakePipelineJob(
        tiny_input,
        output_root=out,
        run_id="run-test-skip",
        skip_video=True,
    )
    manifest = job.run()
    run_dir = out / "run-test-skip"
    assert manifest.status.value == "completed"
    assert (run_dir / "run_manifest.json").is_file()
    assert (run_dir / "incidents.json").is_file()
    assert (run_dir / "tracks.jsonl").is_file()
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "safety_twin.mp4").is_file()
    assert [
        e["rule_id"]
        for e in json.loads((run_dir / "run_manifest.json").read_text())["rule_coverage"]
    ] == [
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
    ]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_fake_pipeline_renders_mp4(tiny_input: Path, tmp_path: Path) -> None:
    out = tmp_path / "output"
    job = FakePipelineJob(
        tiny_input,
        output_root=out,
        run_id="run-test-video",
        skip_video=False,
    )
    manifest = job.run()
    video = out / "run-test-video" / "safety_twin.mp4"
    assert video.is_file()
    assert video.stat().st_size > 1000
    assert "safety_twin_sha256" in manifest.output_artifacts
