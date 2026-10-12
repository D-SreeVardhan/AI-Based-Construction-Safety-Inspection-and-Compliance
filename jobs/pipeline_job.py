from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
import warnings
from datetime import UTC, datetime
from pathlib import Path

import cv2

from llm.adjudicator import GeminiPPEAdjudicator
from llm.regulations import CATALOGUE_SHA256
from llm.retrieval import build_grounded_briefing
from pipeline.intake import FrameSampler
from pipeline.report import build_report_html
from pipeline.rules.engine import evaluate_fake_rules, evaluate_real_rules
from pipeline.vision import Stage1Detector
from shared.config import AppConfig, load_config
from shared.coordinates import Box2, Point2
from shared.enums import (
    CoordinateSpace,
    HelmetState,
    JobStage,
    ProcessingStatus,
    VestState,
)
from shared.schemas.jobs import JobRecord
from shared.schemas.run import InputVideoMeta, PassTiming, RunManifest
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation, VestRecord


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


FULL_HASH_BELOW_BYTES = 64 * 1024 * 1024
HASH_SAMPLE_BYTES = 16 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_input(
    path: Path,
    *,
    full_below_bytes: int = FULL_HASH_BELOW_BYTES,
    sample_bytes: int = HASH_SAMPLE_BYTES,
) -> tuple[str, bool]:
    """Full SHA-256 for small files; size + head/tail sample for large clips."""
    size = path.stat().st_size
    if size <= full_below_bytes:
        return _sha256_file(path), True
    digest = hashlib.sha256()
    digest.update(f"{size}\n".encode())
    with path.open("rb") as handle:
        digest.update(handle.read(sample_bytes))
        if size > sample_bytes:
            handle.seek(max(0, size - sample_bytes))
            digest.update(handle.read(sample_bytes))
    return digest.hexdigest(), False


def probe_video(path: Path) -> tuple[InputVideoMeta, bool]:
    """Best-effort ffprobe; falls back to path + hash only."""
    sha, hash_complete = fingerprint_input(path)
    meta = InputVideoMeta(path=str(path.resolve()), sha256=sha)
    if shutil.which("ffprobe") is None:
        return meta, hash_complete
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return meta, hash_complete
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    width = height = fps = duration = None
    if streams:
        stream = streams[0]
        width = int(stream["width"]) if stream.get("width") is not None else None
        height = int(stream["height"]) if stream.get("height") is not None else None
        rate = stream.get("r_frame_rate")
        if isinstance(rate, str) and "/" in rate:
            num_s, den_s = rate.split("/", 1)
            num, den = float(num_s), float(den_s)
            if den:
                fps = num / den
    fmt = payload.get("format") or {}
    if fmt.get("duration") is not None:
        duration = float(fmt["duration"])
    return InputVideoMeta(
        path=str(path.resolve()),
        sha256=sha,
        width=width,
        height=height,
        duration_s=duration,
        fps=fps,
    ), hash_complete


def _fake_tracks(shot_id: str, duration_s: float) -> list[Pass1TrackObservation]:
    observations: list[Pass1TrackObservation] = []
    frame_count = max(1, int(duration_s * 15))
    for frame_index in range(min(frame_count, 45)):
        t = frame_index / 15.0
        observations.append(
            Pass1TrackObservation(
                shot_id=shot_id,
                frame_index=frame_index,
                video_time_s=t,
                track_id=1,
                canonical_track_id=f"{shot_id}/person-1",
                object_class="person",
                box_reference=Box2(
                    x1=100.0 + frame_index,
                    y1=200.0,
                    x2=180.0 + frame_index,
                    y2=360.0,
                    space=CoordinateSpace.REFERENCE,
                ),
                anchor_reference=Point2(
                    x=140.0 + frame_index,
                    y=360.0,
                    space=CoordinateSpace.REFERENCE,
                ),
                helmet=HelmetRecord(
                    state=HelmetState.NO_HELMET,
                    confidence=0.84,
                    visible=True,
                ),
                vest=VestRecord(
                    state=VestState.VEST,
                    confidence=0.91,
                    visible=True,
                ),
            )
        )
    return observations


def render_placeholder_mp4(
    *,
    output_path: Path,
    duration_s: float,
    width: int,
    height: int,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to render the placeholder side-by-side video")
    pane_w = width // 2
    pane_h = height
    duration_s = max(1.0, min(duration_s, 10.0))
    filter_complex = (
        f"color=c=0x1a1a1a:s={pane_w}x{pane_h}:d={duration_s:.3f}[left];"
        f"color=c=0x2f3e2f:s={pane_w}x{pane_h}:d={duration_s:.3f}[right];"
        "[left][right]hstack=inputs=2[v]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-r",
        "15",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{duration_s:.3f}",
        str(output_path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {completed.stderr.strip() or completed.stdout}")


class FakePipelineJob:
    """Week-1 placeholder job: schemas + fake tracks + side-by-side stub video."""

    def __init__(
        self,
        input_path: Path,
        *,
        output_root: Path | None = None,
        config: AppConfig | None = None,
        run_id: str | None = None,
        skip_video: bool = False,
    ) -> None:
        self.input_path = input_path.resolve()
        self.config = config or load_config()
        self.output_root = (output_root or Path("output")).resolve()
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.skip_video = skip_video
        self.shot_id = "shot-0"
        self.run_dir = self.output_root / self.run_id

    def run(self) -> RunManifest:
        if not self.input_path.is_file():
            raise FileNotFoundError(f"input video not found: {self.input_path}")

        started = _utc_now()
        self.run_dir.mkdir(parents=True, exist_ok=False)
        evidence_dir = self.run_dir / "evidence"
        evidence_dir.mkdir()

        job = JobRecord(
            job_id=f"job-{self.run_id}",
            run_id=self.run_id,
            status=ProcessingStatus.RUNNING,
            stage=JobStage.INTAKE,
            progress=0.05,
            message="Probing input",
        )
        self._write_json(self.run_dir / "job.json", job)

        input_meta, hash_complete = probe_video(self.input_path)
        duration_s = input_meta.duration_s or 2.0
        out_w = self.config.render.output_width
        out_h = self.config.render.output_height

        job = job.model_copy(
            update={
                "stage": JobStage.DETECTION,
                "progress": 0.35,
                "message": "Writing fake tracks",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        tracks = _fake_tracks(self.shot_id, duration_s)
        tracks_path = self.run_dir / "tracks.jsonl"
        with tracks_path.open("w", encoding="utf-8") as handle:
            for obs in tracks:
                handle.write(obs.model_dump_json())
                handle.write("\n")

        job = job.model_copy(
            update={
                "stage": JobStage.MAPPING_RULES,
                "progress": 0.55,
                "message": "Evaluating placeholder R1–R5",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        coverage, incidents, _results = evaluate_fake_rules(
            run_id=self.run_id,
            shot_id=self.shot_id,
            catalogue_sha256=CATALOGUE_SHA256,
        )
        briefings = tuple(build_grounded_briefing(incident) for incident in incidents)
        incidents_path = self.run_dir / "incidents.json"
        self._write_json(
            incidents_path,
            {"schema_version": 1, "incidents": [i.model_dump(mode="json") for i in incidents]},
        )
        self._write_json(
            self.run_dir / "briefings.json",
            {"schema_version": 1, "briefings": [b.model_dump(mode="json") for b in briefings]},
        )
        for incident in incidents:
            evidence_file = self.run_dir / incident.evidence_path
            evidence_file.parent.mkdir(parents=True, exist_ok=True)
            evidence_file.write_text(
                "placeholder evidence frame for synthetic R1 alert\n",
                encoding="utf-8",
            )

        job = job.model_copy(
            update={
                "stage": JobStage.RENDER,
                "progress": 0.8,
                "message": "Rendering placeholder side-by-side video",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        video_path = self.run_dir / "safety_twin.mp4"
        artifacts: dict[str, str] = {
            "briefings": "briefings.json",
            "incidents": "incidents.json",
            "tracks": "tracks.jsonl",
            "run_manifest": "run_manifest.json",
        }
        if self.skip_video:
            video_path.write_bytes(b"")
            artifacts["safety_twin"] = "safety_twin.mp4"
        else:
            render_placeholder_mp4(
                output_path=video_path,
                duration_s=duration_s,
                width=out_w,
                height=out_h,
            )
            artifacts["safety_twin"] = "safety_twin.mp4"
            artifacts["safety_twin_sha256"] = _sha256_file(video_path)

        finished = _utc_now()
        timing = PassTiming(
            stage=JobStage.PUBLISH,
            started_at=_iso(started),
            finished_at=_iso(finished),
            duration_s=(finished - started).total_seconds(),
        )
        manifest = RunManifest(
            run_id=self.run_id,
            status=ProcessingStatus.COMPLETED,
            created_at=_iso(started),
            completed_at=_iso(finished),
            input_video=input_meta,
            model_ids={
                "stage1": "fake",
                "ppe": "fake",
                "rag": "local-bm25-alias-bootstrap",
                "briefing": "deterministic-grounded-briefing-v1",
            },
            dependency_versions={"pipeline": "fake-0.1.0"},
            prompt_versions={"briefing_template": "deterministic-v1"},
            gemini_status="unused",
            scene_cache_status="none",
            rule_coverage=coverage,
            warnings=self._run_warnings(hash_complete),
            pass_timings=(timing,),
            output_artifacts=artifacts,
        )
        self._write_json(self.run_dir / "run_manifest.json", manifest)

        report_path = self.run_dir / "report.html"
        report_path.write_text(build_report_html(manifest, incidents, briefings), encoding="utf-8")
        artifacts = {**artifacts, "report": "report.html"}
        manifest = manifest.model_copy(update={"output_artifacts": artifacts})
        self._write_json(self.run_dir / "run_manifest.json", manifest)

        job = JobRecord(
            job_id=f"job-{self.run_id}",
            run_id=self.run_id,
            status=ProcessingStatus.COMPLETED,
            stage=JobStage.PUBLISH,
            progress=1.0,
            message="Completed",
            cancellable=False,
        )
        self._write_json(self.run_dir / "job.json", job)
        return manifest

    @staticmethod
    def _run_warnings(hash_complete: bool) -> tuple[str, ...]:
        warnings = [
            "Week-1 fake pipeline: detections and twin geometry are synthetic placeholders.",
        ]
        if not hash_complete:
            warnings.append("Input fingerprint is a head/tail sample, not a full-file SHA-256.")
        return tuple(warnings)

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")  # type: ignore[union-attr]
        else:
            data = payload
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Real pipeline job — YOLO11n + ByteTrack + Gemini Vision PPE adjudicator
# ---------------------------------------------------------------------------


class RealPipelineJob:
    """Production pipeline job using real detectors and Gemini PPE adjudicator.

    Falls back to FakePipelineJob automatically if ultralytics is not installed
    so the system remains runnable on machines without GPU dependencies.
    """

    def __init__(
        self,
        input_path: Path,
        *,
        output_root: Path | None = None,
        config: AppConfig | None = None,
        run_id: str | None = None,
        skip_video: bool = False,
        gemini_api_key: str | None = None,
        ppe_sample_interval_s: float = 3.0,
        max_frames: int | None = None,
    ) -> None:
        self.input_path = input_path.resolve()
        self.config = config or load_config()
        self.output_root = (output_root or Path("output")).resolve()
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.skip_video = skip_video
        self.shot_id = "shot-0"
        self.run_dir = self.output_root / self.run_id
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        self.ppe_sample_interval_s = ppe_sample_interval_s
        self.max_frames = max_frames

    def run(self) -> RunManifest:
        """Run the full real pipeline. Falls back to fake if ultralytics missing."""
        if not self.input_path.is_file():
            raise FileNotFoundError(f"input video not found: {self.input_path}")

        started = _utc_now()
        self.run_dir.mkdir(parents=True, exist_ok=False)
        evidence_dir = self.run_dir / "evidence"
        evidence_dir.mkdir()
        crops_dir = self.run_dir / "crops"
        crops_dir.mkdir()
        cache_dir = self.run_dir / ".adjudicator_cache"

        job = JobRecord(
            job_id=f"job-{self.run_id}",
            run_id=self.run_id,
            status=ProcessingStatus.RUNNING,
            stage=JobStage.INTAKE,
            progress=0.05,
            message="Probing input",
        )
        self._write_json(self.run_dir / "job.json", job)

        input_meta, hash_complete = probe_video(self.input_path)

        # --- Stage 1: YOLO11n + ByteTrack ---
        job = job.model_copy(
            update={"stage": JobStage.DETECTION, "progress": 0.15, "message": "Running detection"}
        )
        self._write_json(self.run_dir / "job.json", job)

        sampler = FrameSampler(
            self.input_path,
            target_fps=self.config.intake.target_fps,
            target_width=self.config.intake.target_width,
            target_height=self.config.intake.target_height,
        )
        try:
            detector = Stage1Detector(
                self.config.stage1,
                self.config.tracker,
                shot_id=self.shot_id,
            )
        except ImportError:
            warnings.warn(
                "ultralytics not installed — falling back to FakePipelineJob. "
                "Install vision deps: uv sync --extra vision",
                stacklevel=2,
            )
            return FakePipelineJob(
                self.input_path,
                output_root=self.output_root,
                config=self.config,
                run_id=self.run_id,
                skip_video=self.skip_video,
            ).run()
        observations, crops = detector.detect_and_track(
            sampler,
            ppe_sample_interval_s=self.ppe_sample_interval_s,
            max_frames=self.max_frames,
        )

        # --- Stage 2: Gemini PPE adjudication ---
        job = job.model_copy(
            update={
                "stage": JobStage.DETECTION,
                "progress": 0.45,
                "message": f"Adjudicating {len(crops)} crops via Gemini",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        # Build track-level adjudication: update observations in place
        obs_by_track: dict[str, list] = {}
        for obs in observations:
            obs_by_track.setdefault(obs.canonical_track_id, []).append(obs)

        adjudicator = (
            GeminiPPEAdjudicator(
                self.gemini_api_key,
                model=self.config.scene.gemini_model,
                cache_dir=cache_dir,
            )
            if self.gemini_api_key
            else None
        )

        for crop in crops:
            # Write crop to disk
            rel_crop_path = (
                f"crops/{crop.canonical_track_id.replace('/', '-')}-f{crop.frame_index}.jpg"
            )
            abs_crop = self.run_dir / rel_crop_path
            abs_crop.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(abs_crop), crop.crop_bgr)
            if adjudicator is None:
                continue
            result = adjudicator.assess(crop.crop_bgr)
            # Patch matching observations in the same track near this frame
            track_obs = obs_by_track.get(crop.canonical_track_id, [])
            for obs in track_obs:
                if abs(obs.video_time_s - crop.video_time_s) <= self.ppe_sample_interval_s / 2:
                    if obs.helmet is not None:
                        obs.helmet = result.helmet
                    if obs.vest is not None:
                        obs.vest = result.vest

        # Write tracks
        tracks_path = self.run_dir / "tracks.jsonl"
        with tracks_path.open("w", encoding="utf-8") as handle:
            for obs in observations:
                handle.write(obs.model_dump_json())
                handle.write("\n")

        # --- Stage 3: Rules evaluation ---
        job = job.model_copy(
            update={
                "stage": JobStage.MAPPING_RULES,
                "progress": 0.65,
                "message": "Evaluating R1–R5 against real tracks",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        coverage, incidents, _results = evaluate_real_rules(
            run_id=self.run_id,
            shot_id=self.shot_id,
            observations=observations,
            catalogue_sha256=CATALOGUE_SHA256,
            config=self.config.rules,
        )
        briefings = tuple(build_grounded_briefing(incident) for incident in incidents)

        incidents_path = self.run_dir / "incidents.json"
        self._write_json(
            incidents_path,
            {"schema_version": 1, "incidents": [i.model_dump(mode="json") for i in incidents]},
        )
        self._write_json(
            self.run_dir / "briefings.json",
            {"schema_version": 1, "briefings": [b.model_dump(mode="json") for b in briefings]},
        )
        for incident in incidents:
            evidence_file = self.run_dir / incident.evidence_path
            evidence_file.parent.mkdir(parents=True, exist_ok=True)
            if not evidence_file.exists():
                evidence_file.write_text(
                    f"evidence placeholder for {incident.incident_id}\n", encoding="utf-8"
                )

        # --- Stage 4: Render ---
        job = job.model_copy(
            update={
                "stage": JobStage.RENDER,
                "progress": 0.80,
                "message": "Rendering placeholder twin video",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        video_path = self.run_dir / "safety_twin.mp4"
        artifacts: dict[str, str] = {
            "briefings": "briefings.json",
            "incidents": "incidents.json",
            "tracks": "tracks.jsonl",
            "run_manifest": "run_manifest.json",
        }
        duration_s = input_meta.duration_s or 2.0
        out_w = self.config.render.output_width
        out_h = self.config.render.output_height
        if self.skip_video:
            video_path.write_bytes(b"")
            artifacts["safety_twin"] = "safety_twin.mp4"
        else:
            render_placeholder_mp4(
                output_path=video_path,
                duration_s=duration_s,
                width=out_w,
                height=out_h,
            )
            artifacts["safety_twin"] = "safety_twin.mp4"
            artifacts["safety_twin_sha256"] = _sha256_file(video_path)

        finished = _utc_now()
        timing = PassTiming(
            stage=JobStage.PUBLISH,
            started_at=_iso(started),
            finished_at=_iso(finished),
            duration_s=(finished - started).total_seconds(),
        )
        run_warnings: list[str] = []
        if not hash_complete:
            run_warnings.append("Input fingerprint is a head/tail sample, not a full-file SHA-256.")
        if not self.gemini_api_key:
            run_warnings.append(
                "GEMINI_API_KEY not set — all PPE assessments returned UNKNOWN. "
                "R1/R2 alerts will be empty."
            )

        manifest = RunManifest(
            run_id=self.run_id,
            status=ProcessingStatus.COMPLETED,
            mode="real_pipeline",
            created_at=_iso(started),
            completed_at=_iso(finished),
            input_video=input_meta,
            model_ids={
                "stage1": str(self.config.stage1.model_path),
                "ppe": f"gemini/{self.config.scene.gemini_model}",
                "rag": "local-bm25-alias-bootstrap",
                "briefing": "deterministic-grounded-briefing-v1",
            },
            dependency_versions={"pipeline": "real-0.2.0"},
            prompt_versions={"briefing_template": "deterministic-v1", "ppe": "ppe-v1"},
            gemini_status="ok" if self.gemini_api_key else "no_key",
            scene_cache_status="none",
            rule_coverage=coverage,
            warnings=tuple(run_warnings),
            pass_timings=(timing,),
            output_artifacts=artifacts,
        )
        self._write_json(self.run_dir / "run_manifest.json", manifest)

        report_path = self.run_dir / "report.html"
        report_path.write_text(build_report_html(manifest, incidents, briefings), encoding="utf-8")
        artifacts = {**artifacts, "report": "report.html"}
        manifest = manifest.model_copy(update={"output_artifacts": artifacts})
        self._write_json(self.run_dir / "run_manifest.json", manifest)

        job = JobRecord(
            job_id=f"job-{self.run_id}",
            run_id=self.run_id,
            status=ProcessingStatus.COMPLETED,
            stage=JobStage.PUBLISH,
            progress=1.0,
            message="Completed",
            cancellable=False,
        )
        self._write_json(self.run_dir / "job.json", job)
        return manifest

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
