"""Hosted demo API: runs, report with live chat, risk, chat limits, file safety."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from jobs.pipeline_job import FakePipelineJob  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    root = tmp_path_factory.mktemp("cloud")
    clip = root / "clip.bin"
    clip.write_bytes(b"synthetic input")
    FakePipelineJob(clip, output_root=root / "runs", run_id="run-cloud", skip_video=True).run()
    (root / "runs" / "run-cloud" / "safety_twin_720p.mp4").write_bytes(bytes(range(256)) * 8)
    patch = pytest.MonkeyPatch()
    patch.setenv("SAFETY_RUNS_DIR", str(root / "runs"))
    patch.setenv("SAFETY_CHAT_PER_MINUTE", "3")
    for name in ("SAFETY_LLM_PROVIDER", "SAFETY_RUNS_REPO", "SUPABASE_URL"):
        patch.delenv(name, raising=False)
    import app.cloud

    cloud = importlib.reload(app.cloud)
    with TestClient(cloud.app) as test_client:
        yield test_client
    patch.undo()


def test_health_lists_runs_without_secrets(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body == {"status": "ok", "runs": 1, "llm": None, "database": False}


def test_gallery_and_run_list(client: TestClient) -> None:
    [run] = client.get("/api/runs").json()
    assert run["run_id"] == "run-cloud" and run["incidents"] == 1
    assert run["report"] == "/runs/run-cloud/"
    assert "run-cloud" in client.get("/").text


def test_report_is_served_with_the_live_chat_switched_on(client: TestClient) -> None:
    page = client.get("/runs/run-cloud/")
    assert page.status_code == 200
    assert '<meta name="safety-api" content="/api/runs/run-cloud">' in page.text
    redirect = client.get("/runs/run-cloud", follow_redirects=False)
    assert redirect.status_code == 308 and redirect.headers["location"] == "/runs/run-cloud/"


def test_files_support_range_and_never_leave_the_run(client: TestClient) -> None:
    part = client.get("/runs/run-cloud/safety_twin_720p.mp4", headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10
    assert client.get("/runs/run-cloud/../../pyproject.toml").status_code == 404
    assert client.get("/runs/run-cloud/%2e%2e/%2e%2e/pyproject.toml").status_code == 404
    assert client.get("/runs/run-cloud/report.html").status_code == 404  # only via /runs/id/
    assert client.get("/runs/nope/").status_code == 404
    assert client.get("/api/runs/..%2Fetc/risk").status_code == 404


def test_risk_register_api(client: TestClient) -> None:
    body = client.get("/api/runs/run-cloud/risk").json()
    rated = {r["rule"] for r in body["rows"]}
    others = {r["rule"] for r in body["not_assessed"]} | {r["rule"] for r in body["not_observed"]}
    assert len(rated | others) == 8
    assert all(r["rating"] == r["likelihood"] * r["severity"] for r in body["rows"])


def test_chat_answers_from_the_register_and_is_rate_limited(client: TestClient) -> None:
    replies = [
        client.post("/api/runs/run-cloud/chat", json={"question": "What are the risks?"})
        for _ in range(4)
    ]
    assert [r.status_code for r in replies] == [200, 200, 200, 429]
    first = replies[0].json()
    assert first["source"] == "register" and first["citations"]
    stats = client.get("/api/stats").json()
    assert stats["by_source"] == {"register": 3}


def test_chat_rejects_bad_input_and_reviews_need_a_database(client: TestClient) -> None:
    assert client.post("/api/runs/run-cloud/chat", json={"question": ""}).status_code == 422
    review = {"incident_id": "x", "verdict": "real", "reviewer": "Asha"}
    assert client.post("/api/runs/run-cloud/reviews", json=review).status_code == 503
    for bad in (
        {"incident_id": "x", "verdict": "maybe", "reviewer": "Asha"},
        {"incident_id": "x", "verdict": "real"},  # a verdict needs a reviewer
        {"incident_id": "x", "verdict": "real", "reviewer": "<script>"},
    ):
        assert client.post("/api/runs/run-cloud/reviews", json=bad).status_code == 422


def test_team_review_summary(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.cloud as cloud

    stored: list[dict] = []
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setattr(cloud, "supabase_insert", lambda table, r: stored.append(r))
    monkeypatch.setattr(cloud, "fetch_supabase", lambda run_id: stored)
    [incident] = client.get("/api/runs/run-cloud/risk").json()["rows"][0]["incidents"]
    for n, (name, verdict) in enumerate((("Asha", "real"), ("Ben", "real"))):
        body = {"incident_id": incident, "verdict": verdict, "reviewer": f" {name} "}
        assert client.post("/api/runs/run-cloud/reviews", json=body).status_code == 200
        stored[-1] |= {"id": n, "created_at": f"2026-10-15T00:00:0{n}Z"}
    assert stored[0]["reviewer"] == "Asha" and stored[0]["run_id"] == "run-cloud"
    summary = client.get("/api/runs/run-cloud/reviews").json()
    assert summary["reviewers"] == 2 and summary["decided"] == 1 and summary["precision"] == 1.0


def test_runs_dir_is_configurable(tmp_path: Path) -> None:
    from app.cloud import RunStore

    assert RunStore(tmp_path / "missing").ids() == []


def test_publishing_refuses_runs_without_face_pixelation(tmp_path: Path) -> None:
    from tools.publish_run import check

    clip = tmp_path / "clip.bin"
    clip.write_bytes(b"synthetic input")
    job = FakePipelineJob(clip, output_root=tmp_path, run_id="run-raw", skip_video=True)
    job.run()
    assert any("privacy" in problem for problem in check(job.run_dir))


def test_published_manifests_carry_no_local_paths() -> None:
    import json

    from tools.publish_run import redact

    manifest = {
        "input_video": {"path": r"C:\Users\someone\OneDrive\clips\9.mp4"},
        "diagnostics": {"work_dir": r"C:\Users\someone\AppData\Local\runs\x", "privacy": "faces"},
    }
    clean = json.dumps(redact(manifest))
    assert "someone" not in clean and '"9.mp4"' in clean and "<local>" in clean
