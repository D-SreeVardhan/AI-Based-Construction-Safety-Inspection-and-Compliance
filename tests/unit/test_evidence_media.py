from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np

from app.server import DeskHandler
from cloud.media_view import incident_cards_html, load_media, review_gallery_html
from cloud.publish import _upload_media
from jobs.pipeline_job import FakePipelineJob
from pipeline.evidence import pick_evidence_observation, write_incident_evidence
from pipeline.report import build_report_html
from pipeline.rules.engine import evaluate_real_rules
from shared.config import load_config
from shared.coordinates import Box2, Point2
from shared.enums import CoordinateSpace, HelmetState
from shared.media import is_jpeg
from shared.schemas.incidents import IncidentRecord
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation


def _start(output_root: Path) -> tuple[ThreadingHTTPServer, str]:
    DeskHandler.output_root = output_root
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), DeskHandler)
    Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[:2]
    return httpd, f"{host}:{port}"


def _obs(frame_index: int, height: float) -> Pass1TrackObservation:
    return Pass1TrackObservation(
        shot_id="s0",
        frame_index=frame_index,
        video_time_s=frame_index * 0.1,
        track_id=1,
        canonical_track_id="s0/person-1",
        object_class="person",
        box_reference=Box2(
            x1=100.0, y1=100.0, x2=160.0, y2=100.0 + height, space=CoordinateSpace.REFERENCE
        ),
        anchor_reference=Point2(x=130.0, y=100.0 + height, space=CoordinateSpace.REFERENCE),
        helmet=HelmetRecord(state=HelmetState.NO_HELMET, confidence=0.9, visible=True),
    )


def _incident(observations: list[Pass1TrackObservation]) -> IncidentRecord:
    _, incidents, _ = evaluate_real_rules(
        run_id="run-ev",
        shot_id="s0",
        observations=observations,
        catalogue_sha256="abc",
        config=load_config().rules,
    )
    assert len(incidents) == 1
    return incidents[0]


class _Sampler:
    def frames_at(self, indices: list[int]) -> dict[int, tuple[float, np.ndarray]]:
        return {i: (i * 0.1, np.full((360, 640, 3), 90, dtype=np.uint8)) for i in indices}


def test_evidence_uses_largest_view_and_writes_jpeg(tmp_path: Path) -> None:
    observations = [_obs(i, 120.0 + (40.0 if i == 7 else 0.0)) for i in range(20)]
    incident = _incident(observations)
    picked = pick_evidence_observation(incident, observations)
    assert picked is not None and picked.frame_index == 7

    written = write_incident_evidence(
        sampler=_Sampler(),  # type: ignore[arg-type]
        observations=observations,
        incidents=[incident],
        run_dir=tmp_path,
    )
    assert written == {incident.incident_id}
    path = tmp_path / incident.evidence_path
    assert is_jpeg(path)
    assert cv2.imread(str(path)).shape[0] >= 360


def test_report_inlines_only_real_jpeg_evidence(tmp_path: Path) -> None:
    clip = tmp_path / "clip.bin"
    clip.write_bytes(b"clip")
    job = FakePipelineJob(clip, output_root=tmp_path / "out", run_id="run-ev", skip_video=True)
    manifest = job.run()
    incidents = tuple(
        IncidentRecord.model_validate(item)
        for item in json.loads((job.run_dir / "incidents.json").read_text())["incidents"]
    )
    assert "data:image/jpeg" not in build_report_html(manifest, incidents, (), run_dir=job.run_dir)

    cv2.imwrite(str(job.run_dir / incidents[0].evidence_path), np.zeros((40, 40, 3), np.uint8))
    html = build_report_html(manifest, incidents, (), run_dir=job.run_dir)
    assert "data:image/jpeg;base64," in html


class _RecordingClient:
    def __init__(self) -> None:
        self.config = SimpleNamespace(supabase_bucket="run-media")
        self.uploads: dict[str, bytes] = {}

    def upload_file(self, local_path: Path, object_path: str, *, content_type: str) -> str:
        return self.upload_bytes(local_path.read_bytes(), object_path, content_type=content_type)

    def upload_bytes(self, data: bytes, object_path: str, *, content_type: str) -> str:
        self.uploads[object_path] = data
        return f"run-media/{object_path}"

    def download(self, object_path: str) -> bytes | None:
        return self.uploads.get(object_path)

    def signed_urls(self, object_paths: list[str], *, expires_in: int = 3600) -> dict[str, str]:
        return {p: f"https://signed/{p}?token=t" for p in object_paths if p in self.uploads}


def _jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.zeros((20, 20, 3), np.uint8))


def test_publish_media_round_trips_into_space_html(tmp_path: Path) -> None:
    _jpeg(tmp_path / "evidence/inc-a.jpg")
    (tmp_path / "evidence/inc-b.jpg").write_text("placeholder", encoding="utf-8")
    _jpeg(tmp_path / "crops/p1-f0.jpg")
    (tmp_path / "ppe_verification.json").write_text(
        json.dumps(
            {
                "verifications": [
                    {
                        "track_id": "s0/person-1",
                        "crop": "crops/p1-f0.jpg",
                        "classifier": {"helmet": "unknown", "vest": "vest"},
                        "gemini": {"helmet": "no_helmet", "vest": "vest"},
                        "action": "override:helmet",
                    },
                    {"track_id": "s0/person-2", "crop": "crops/missing.jpg"},
                ]
            }
        ),
        encoding="utf-8",
    )
    incidents: list[dict[str, Any]] = [
        {"incident_id": "inc-a", "evidence_path": "evidence/inc-a.jpg"},
        {"incident_id": "inc-b", "evidence_path": "evidence/inc-b.jpg"},
    ]
    client = _RecordingClient()
    media = _upload_media(client, run_id="run-x", run_dir=tmp_path, incidents=incidents)  # type: ignore[arg-type]

    assert set(media["evidence"]) == {"inc-a"}
    assert [e["crop"] for e in media["ppe_review"]] == ["crops/p1-f0.jpg"]
    assert "runs/run-x/media.json" in client.uploads

    evidence_urls, review = load_media(client, "run-x")  # type: ignore[arg-type]
    assert evidence_urls == {"inc-a": "https://signed/runs/run-x/evidence/inc-a.jpg?token=t"}
    rows = [
        {
            "rule_id": "R1",
            "status": "evaluated_alert",
            "payload": {
                "incident_id": iid,
                "first_seen_s": 1.0,
                "resolved_at_s": 2.0,
                "observation_text": "<b>worker</b> without helmet",
                "action_text": "Check",
            },
        }
        for iid in ("inc-a", "inc-b")
    ]
    cards = incident_cards_html(rows, evidence_urls)
    assert cards.count("<img") == 1 and "No evidence crop" in cards
    assert "&lt;b&gt;worker" in cards
    gallery = review_gallery_html(review)
    assert "runs/run-x/crops/p1-f0.jpg" in gallery and "no_helmet / vest" in gallery


def test_space_media_absent_for_legacy_runs() -> None:
    assert load_media(_RecordingClient(), "run-old") == ({}, [])  # type: ignore[arg-type]


def test_desk_serves_only_real_evidence_jpegs(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "run-abc123"
    _jpeg(run_dir / "evidence/inc-a.jpg")
    (run_dir / "evidence/inc-b.jpg").write_text("placeholder", encoding="utf-8")
    httpd, addr = _start(tmp_path / "output")
    try:
        conn = HTTPConnection(addr, timeout=10)
        for path, status in (
            ("/runs/run-abc123/evidence/inc-a.jpg", 200),
            ("/runs/run-abc123/evidence/inc-b.jpg", 404),
            ("/runs/run-abc123/crops/inc-a.jpg", 404),
        ):
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            assert response.status == status, path
            if status == 200:
                assert response.getheader("Content-Type") == "image/jpeg"
    finally:
        httpd.shutdown()
