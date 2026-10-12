from __future__ import annotations

import json
from pathlib import Path

from jobs.pipeline_job import FakePipelineJob
from pipeline.report import build_report_html
from shared.schemas.run import RunManifest


def _fake_run(tmp_path: Path) -> tuple[RunManifest, Path]:
    clip = tmp_path / '<img src=x onerror="alert(1)">.bin'
    clip.write_bytes(b"clip")
    job = FakePipelineJob(clip, output_root=tmp_path / "out", run_id="run-report", skip_video=True)
    return job.run(), job.run_dir


def test_report_escapes_untrusted_manifest_values(tmp_path: Path) -> None:
    manifest, _ = _fake_run(tmp_path)
    html = build_report_html(manifest, (), ())
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


def test_report_lists_incidents_citations_and_warnings(tmp_path: Path) -> None:
    manifest, run_dir = _fake_run(tmp_path)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    incidents = json.loads((run_dir / "incidents.json").read_text())["incidents"]
    briefings = json.loads((run_dir / "briefings.json").read_text())["briefings"]

    assert incidents and briefings
    assert f"Incidents ({len(incidents)})" in html
    first_ref = briefings[0]["retrieved_chunks"][0]["chunk"]["clause_ref"]
    assert first_ref in html
    for warning in manifest.warnings:
        assert warning in html
    assert "Not a certified safety system" in html
