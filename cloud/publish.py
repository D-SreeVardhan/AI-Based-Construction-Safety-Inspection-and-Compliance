from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cloud.config import load_cloud_config
from cloud.supabase import SupabaseClient
from llm.regulations import BOOTSTRAP_CLAUSES, CATALOGUE_SHA256


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_path(run_dir: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = run_dir / relative
    return path if path.is_file() else None


def _upload_artifact(
    client: SupabaseClient,
    *,
    run_id: str,
    run_dir: Path,
    relative: str | None,
    content_type: str,
) -> str | None:
    local_path = _artifact_path(run_dir, relative)
    if local_path is None or local_path.stat().st_size == 0:
        return None
    return client.upload_file(
        local_path,
        f"runs/{run_id}/{local_path.name}",
        content_type=content_type,
    )


def publish_run(run_dir: Path) -> dict[str, Any]:
    config = load_cloud_config()
    client = SupabaseClient(config)
    manifest = _read_json(run_dir / "run_manifest.json")
    incidents = _read_json(run_dir / "incidents.json").get("incidents", [])
    briefings = _read_json(run_dir / "briefings.json").get("briefings", [])
    run_id = str(manifest["run_id"])
    artifacts = manifest.get("output_artifacts", {})

    video_path = _upload_artifact(
        client,
        run_id=run_id,
        run_dir=run_dir,
        relative=artifacts.get("safety_twin"),
        content_type="video/mp4",
    )
    report_path = _upload_artifact(
        client,
        run_id=run_id,
        run_dir=run_dir,
        relative=artifacts.get("report"),
        content_type="text/html; charset=utf-8",
    )

    client.upsert(
        "runs",
        {
            "id": run_id,
            "status": manifest["status"],
            "created_at": manifest["created_at"],
            "completed_at": manifest.get("completed_at"),
            "clip_name": Path(manifest["input_video"]["path"]).name,
            "manifest": manifest,
            "video_path": video_path,
            "report_path": report_path,
        },
    )
    if incidents:
        client.upsert(
            "incidents",
            [
                {
                    "id": incident["incident_id"],
                    "run_id": run_id,
                    "rule_id": incident["rule_id"],
                    "status": incident["status"],
                    "payload": incident,
                }
                for incident in incidents
            ],
        )
    if briefings:
        client.upsert(
            "briefings",
            [
                {
                    "incident_id": briefing["incident_id"],
                    "run_id": run_id,
                    "rule_id": briefing["rule_id"],
                    "refused": briefing.get("refused", False),
                    "payload": briefing,
                }
                for briefing in briefings
            ],
        )
    client.upsert(
        "clause_chunks",
        [
            {
                "id": chunk.chunk_id,
                "catalogue_sha256": CATALOGUE_SHA256,
                "rule_ids": [rule_id.value for rule_id in chunk.rule_ids],
                "clause_ref": chunk.clause_ref,
                "title": chunk.title,
                "text": chunk.text,
                "source": chunk.source,
                "source_url": chunk.source_url,
                "retrieved_on": chunk.retrieved_on,
                "sha256": chunk.sha256,
            }
            for chunk in BOOTSTRAP_CLAUSES
        ],
    )
    return {
        "run_id": run_id,
        "incident_count": len(incidents),
        "briefing_count": len(briefings),
        "video_path": video_path,
        "report_path": report_path,
    }
