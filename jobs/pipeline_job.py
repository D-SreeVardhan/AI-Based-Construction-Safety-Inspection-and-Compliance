from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2

from llm.adjudicator import GeminiPPEAdjudicator
from llm.regulations import CATALOGUE_SHA256
from llm.retrieval import RETRIEVAL_MODE, build_grounded_briefing
from pipeline.evidence import write_incident_evidence
from pipeline.geometry import build_geometry
from pipeline.intake import FrameSampler
from pipeline.render import render_twin_video
from pipeline.report import build_report_html
from pipeline.rules.engine import evaluate_fake_rules, evaluate_real_rules
from pipeline.scene import bootstrap_scene
from pipeline.vision import PersonCrop, Stage1Detector

try:
    from pipeline.vision.ppe_stage import PPEStage
except ImportError:  # torch arrives with the vision extra
    PPEStage = None  # type: ignore[assignment,misc]
from shared.config import AppConfig, load_config
from shared.coordinates import Box2, Point2
from shared.enums import (
    CoordinateSpace,
    HelmetState,
    JobStage,
    ProcessingStatus,
    VestState,
)
from shared.schemas.geometry import GeometryModel
from shared.schemas.jobs import JobRecord
from shared.schemas.run import InputVideoMeta, PassTiming, RunManifest
from shared.schemas.scene import SceneModel
from shared.schemas.tracks import HelmetRecord, Pass1TrackObservation, VestRecord


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def _gemini_status(*, has_key: bool, failed: int, total: int) -> str:
    if not has_key:
        return "no_key"
    if failed == 0:
        return "ok"
    return "failed" if failed >= total else "degraded"


@dataclass
class _PPEOutcome:
    model_id: str
    sent: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verifications: list[dict[str, Any]] = field(default_factory=list)


def load_ppe_stage(config: AppConfig) -> PPEStage | None:
    """The trained PPE classifier, or None to fall back to Gemini-only PPE."""
    if PPEStage is None:
        return None
    try:
        return PPEStage.from_config(config.ppe, config.stage1.device)
    except (OSError, RuntimeError, KeyError) as exc:
        warnings.warn(f"PPE classifier failed to load ({exc}); using Gemini-only PPE", stacklevel=2)
        return None


def _detector_id(model_path: str) -> str:
    path = Path(model_path)
    return f"{model_path}:{_sha256_file(path)[:16]}" if path.is_file() else model_path


def _scene_warnings(scene: SceneModel) -> list[str]:
    if scene.status != "ok":
        return [
            f"Scene bootstrap unavailable ({scene.status_reason}); R3 and R5 cannot be "
            "evaluated for this run."
        ]
    if not scene.proposals:
        return ["Scene bootstrap found no zones or edges with enough keyframe agreement."]
    return []


def _geometry_warnings(geometry: GeometryModel) -> list[str]:
    if geometry.status == "ok":
        return []
    return [
        f"Relative ground plane unavailable ({geometry.status_reason}); R4 and R5 distances "
        "are not reported for this run."
    ]


def _crop_name(crop: PersonCrop) -> str:
    return f"crops/{crop.canonical_track_id.replace('/', '-')}-f{crop.frame_index}.jpg"


def _flags(obs: Pass1TrackObservation) -> tuple[bool, bool]:
    return (
        obs.helmet is not None and obs.helmet.state == HelmetState.NO_HELMET,
        obs.vest is not None and obs.vest.state == VestState.NO_VEST,
    )


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
        report_path.write_text(
            build_report_html(manifest, incidents, briefings, run_dir=self.run_dir),
            encoding="utf-8",
        )
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
        ppe_stage = load_ppe_stage(self.config)
        observations, crops = detector.detect_and_track(
            sampler,
            ppe_sample_interval_s=self.ppe_sample_interval_s,
            max_frames=self.max_frames,
            ppe_stage=ppe_stage,
        )

        # --- Stage 2: Gemini PPE adjudication (Gemini-only) or verification (hybrid) ---
        job = job.model_copy(
            update={
                "stage": JobStage.DETECTION,
                "progress": 0.45,
                "message": "Reviewing large person crops via Gemini"
                if ppe_stage is not None
                else f"Adjudicating {len(crops)} crops via Gemini",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        for crop in crops:
            cv2.imwrite(str(self.run_dir / _crop_name(crop)), crop.crop_bgr)

        adjudicator = (
            GeminiPPEAdjudicator(
                self.gemini_api_key,
                model=self.config.scene.gemini_model,
                cache_dir=cache_dir,
            )
            if self.gemini_api_key
            else None
        )
        if ppe_stage is None:
            ppe = self._adjudicate_all_crops(observations, crops, adjudicator)
        else:
            ppe = self._review_with_gemini(observations, crops, adjudicator, ppe_stage.model_id)
            self._write_json(
                self.run_dir / "ppe_verification.json",
                {"schema_version": 1, "verifications": ppe.verifications},
            )

        # Write tracks
        tracks_path = self.run_dir / "tracks.jsonl"
        with tracks_path.open("w", encoding="utf-8") as handle:
            for obs in observations:
                handle.write(obs.model_dump_json())
                handle.write("\n")

        # Compute detection summary for Q&A context
        person_tracks = {o.canonical_track_id for o in observations if o.object_class == "person"}
        vehicle_tracks = {o.canonical_track_id for o in observations if o.object_class != "person"}
        no_helmet_tracks = {
            o.canonical_track_id
            for o in observations
            if o.helmet and o.helmet.state.value == "no_helmet"
        }
        no_vest_tracks = {
            o.canonical_track_id for o in observations if o.vest and o.vest.state.value == "no_vest"
        }
        detection_summary: dict[str, int] = {
            "unique_person_tracks": len(person_tracks),
            "unique_vehicle_tracks": len(vehicle_tracks),
            "total_person_observations": sum(1 for o in observations if o.object_class == "person"),
            "tracks_with_no_helmet": len(no_helmet_tracks),
            "tracks_with_no_vest": len(no_vest_tracks),
        }

        # --- Stage 3: Scene bootstrap, then rules ---
        job = job.model_copy(
            update={
                "stage": JobStage.MAPPING_RULES,
                "progress": 0.60,
                "message": "Inferring restricted zones and open edges",
            }
        )
        self._write_json(self.run_dir / "job.json", job)

        scene, scene_cache_status = bootstrap_scene(
            sampler=sampler,
            observations=observations,
            video_sha256=input_meta.sha256,
            detector_id=_detector_id(self.config.stage1.model_path),
            config=self.config,
            api_key=self.gemini_api_key,
        )
        self._write_json(self.run_dir / "scene.json", scene)

        job = job.model_copy(
            update={"progress": 0.63, "message": "Fitting the relative ground plane"}
        )
        self._write_json(self.run_dir / "job.json", job)
        geometry, geometry_context = build_geometry(
            sampler=sampler,
            observations=observations,
            video_width=input_meta.width,
            video_height=input_meta.height,
            config=self.config,
        )
        self._write_json(self.run_dir / "geometry.json", geometry)

        job = job.model_copy(
            update={"progress": 0.65, "message": "Evaluating R1–R5 against real tracks"}
        )
        self._write_json(self.run_dir / "job.json", job)

        coverage, incidents, _results = evaluate_real_rules(
            run_id=self.run_id,
            shot_id=self.shot_id,
            observations=observations,
            catalogue_sha256=CATALOGUE_SHA256,
            config=self.config.rules,
            scene=scene,
            geometry=geometry_context,
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
        try:
            evidence_written = write_incident_evidence(
                sampler=sampler,
                observations=observations,
                incidents=incidents,
                run_dir=self.run_dir,
            )
        except RuntimeError:
            evidence_written = set()
        missing_evidence = len(incidents) - len(evidence_written)

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
            "scene": "scene.json",
            "geometry": "geometry.json",
        }
        if ppe_stage is not None:
            artifacts["ppe_verification"] = "ppe_verification.json"
        out_w = self.config.render.output_width
        out_h = self.config.render.output_height
        if self.skip_video:
            video_path.write_bytes(b"")
            artifacts["safety_twin"] = "safety_twin.mp4"
        else:
            render_twin_video(
                input_video=self.input_path,
                run_dir=self.run_dir,
                output_path=video_path,
                target_width=out_w,
                target_height=out_h,
                output_fps=self.config.render.output_fps,
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
        run_warnings.extend(ppe.warnings)
        run_warnings.extend(_scene_warnings(scene))
        run_warnings.extend(_geometry_warnings(geometry))
        if missing_evidence:
            run_warnings.append(f"{missing_evidence} incident(s) have no evidence crop.")

        manifest = RunManifest(
            run_id=self.run_id,
            status=ProcessingStatus.COMPLETED,
            mode="real_pipeline",
            created_at=_iso(started),
            completed_at=_iso(finished),
            input_video=input_meta,
            model_ids={
                "stage1": str(self.config.stage1.model_path),
                "ppe": ppe.model_id,
                **({"scene": f"gemini-consensus/{scene.model_id}"} if scene.status == "ok" else {}),
                **({"pose": geometry.pose_model_id} if geometry.pose_model_id else {}),
                "rag": RETRIEVAL_MODE,
                "briefing": "deterministic-grounded-briefing-v1",
            },
            dependency_versions={"pipeline": "real-0.3.0"},
            prompt_versions={
                "briefing_template": "deterministic-v1",
                "ppe": "ppe-v1",
                "scene": self.config.scene.prompt_version,
            },
            gemini_status=_gemini_status(
                has_key=bool(self.gemini_api_key),
                failed=len(ppe.errors),
                total=ppe.sent,
            ),
            scene_cache_status=scene_cache_status,
            rule_coverage=coverage,
            warnings=tuple(run_warnings),
            pass_timings=(timing,),
            output_artifacts=artifacts,
            detection_summary=detection_summary,
        )
        self._write_json(self.run_dir / "run_manifest.json", manifest)

        report_path = self.run_dir / "report.html"
        report_path.write_text(
            build_report_html(manifest, incidents, briefings, run_dir=self.run_dir),
            encoding="utf-8",
        )
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

    def _adjudicate_all_crops(
        self,
        observations: list[Pass1TrackObservation],
        crops: list[PersonCrop],
        adjudicator: GeminiPPEAdjudicator | None,
    ) -> _PPEOutcome:
        """Gemini-only PPE: every sampled crop is assessed and patched onto nearby frames."""
        outcome = _PPEOutcome(model_id=f"gemini/{self.config.scene.gemini_model}")
        if adjudicator is None:
            outcome.warnings.append(
                "GEMINI_API_KEY not set — all PPE assessments returned UNKNOWN. "
                "R1/R2 alerts will be empty."
            )
            return outcome
        # Observations are frozen; index by track so adjudicated copies replace originals.
        obs_by_track = _index_by_track(observations)
        min_height = self.config.ppe.gemini_minimum_crop_height_px
        too_small = 0
        for crop in crops:
            if crop.crop_bgr.shape[0] < min_height:
                too_small += 1
                continue
            result = adjudicator.assess(crop.crop_bgr)
            outcome.sent += 1
            if result.error is not None:
                outcome.errors.append(result.error)
            for index in obs_by_track.get(crop.canonical_track_id, []):
                obs = observations[index]
                if abs(obs.video_time_s - crop.video_time_s) > self.ppe_sample_interval_s / 2:
                    continue
                update: dict[str, object] = {}
                if obs.helmet is not None:
                    update["helmet"] = result.helmet
                if obs.vest is not None:
                    update["vest"] = result.vest
                if update:
                    observations[index] = obs.model_copy(update=update)
        if too_small:
            outcome.warnings.append(
                f"{too_small} of {len(crops)} person crops were shorter than {min_height} px "
                "and were not sent to Gemini (PPE left UNKNOWN for those frames)."
            )
        if outcome.errors:
            outcome.warnings.append(
                f"Gemini PPE assessment failed for {len(outcome.errors)} of {outcome.sent} "
                f"crops (left UNKNOWN; R1/R2 may under-report). First error: "
                f"{outcome.errors[0][:160]}"
            )
        return outcome

    def _review_with_gemini(
        self,
        observations: list[Pass1TrackObservation],
        crops: list[PersonCrop],
        adjudicator: GeminiPPEAdjudicator | None,
        classifier_id: str,
    ) -> _PPEOutcome:
        """Hybrid PPE, routed by resolution.

        Crops at least ``gemini_minimum_crop_height_px`` tall go to Gemini (flagged workers
        first, then the largest, up to the call budget); a definite Gemini answer replaces
        the classifier verdict on that track's frames within half a sampling interval, in
        either direction. Everything else keeps the classifier verdict: on small crops
        Gemini guesses, and on large ones the classifier can be fooled by out-of-domain
        clothing (striped sweaters read as reflective bands).
        """
        model = self.config.scene.gemini_model
        outcome = _PPEOutcome(
            model_id=f"{classifier_id}+gemini-review/{model}" if adjudicator else classifier_id
        )
        obs_by_track = _index_by_track(observations)
        flagged = {
            track_id
            for track_id, indices in obs_by_track.items()
            if any(any(_flags(observations[i])) for i in indices)
        }
        if adjudicator is None:
            if flagged:
                outcome.warnings.append(
                    f"GEMINI_API_KEY not set — {len(flagged)} worker(s) flagged by the PPE "
                    "classifier were not double-checked."
                )
            return outcome

        min_height = self.config.ppe.gemini_minimum_crop_height_px
        cap = self.config.ppe.maximum_gemini_verifications
        large = [c for c in crops if c.crop_bgr.shape[0] >= min_height]
        large.sort(
            key=lambda c: (c.canonical_track_id not in flagged, -c.crop_bgr.shape[0], c.frame_index)
        )
        reviewed, over_budget = large[:cap], large[cap:]
        reviewed_tracks = {c.canonical_track_id for c in reviewed}
        half_window = self.ppe_sample_interval_s / 2
        overrides = 0

        for crop in sorted(reviewed, key=lambda c: c.frame_index):
            window = [
                index
                for index in obs_by_track.get(crop.canonical_track_id, [])
                if abs(observations[index].video_time_s - crop.video_time_s) <= half_window
            ]
            at_crop = next(
                (o for o in (observations[i] for i in window) if o.frame_index == crop.frame_index),
                None,
            )
            entry: dict[str, Any] = {
                "track_id": crop.canonical_track_id,
                "crop": _crop_name(crop),
                "classifier": {
                    "helmet": at_crop.helmet.state.value if at_crop and at_crop.helmet else None,
                    "vest": at_crop.vest.state.value if at_crop and at_crop.vest else None,
                },
            }
            outcome.verifications.append(entry)
            result = adjudicator.assess(crop.crop_bgr)
            outcome.sent += 1
            if result.error is not None:
                outcome.errors.append(result.error)
                entry["action"] = "gemini_error_kept"
                continue
            entry["gemini"] = {"helmet": result.helmet.state.value, "vest": result.vest.state.value}
            changed: set[str] = set()
            for index in window:
                obs = observations[index]
                update: dict[str, object] = {}
                if (
                    obs.helmet is not None
                    and result.helmet.state != HelmetState.UNKNOWN
                    and obs.helmet.state != result.helmet.state
                ):
                    update["helmet"] = result.helmet
                if (
                    obs.vest is not None
                    and result.vest.state != VestState.UNKNOWN
                    and obs.vest.state != result.vest.state
                ):
                    update["vest"] = result.vest
                if update:
                    observations[index] = obs.model_copy(update=update)
                    changed.update(update)
            entry["action"] = "override:" + ",".join(sorted(changed)) if changed else "agree"
            overrides += bool(changed)

        unreviewed_flagged = flagged - reviewed_tracks
        outcome.warnings.append(
            f"Gemini reviewed {outcome.sent} person crop(s) of at least {min_height} px and "
            f"changed the classifier verdict on {overrides}; smaller workers use the "
            "classifier alone."
        )
        if unreviewed_flagged:
            outcome.warnings.append(
                f"{len(unreviewed_flagged)} worker(s) flagged by the classifier had no crop "
                "Gemini could review; their verdict is unverified."
            )
        if over_budget:
            outcome.warnings.append(
                f"{len(over_budget)} large crop(s) exceeded the {cap}-call Gemini budget "
                "(ppe.maximum_gemini_verifications); classifier verdict kept."
            )
        if outcome.errors:
            outcome.warnings.append(
                f"Gemini PPE review failed for {len(outcome.errors)} of {outcome.sent} "
                f"crops (classifier verdict kept). First error: {outcome.errors[0][:160]}"
            )
        return outcome

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _index_by_track(observations: list[Pass1TrackObservation]) -> dict[str, list[int]]:
    by_track: dict[str, list[int]] = {}
    for index, obs in enumerate(observations):
        by_track.setdefault(obs.canonical_track_id, []).append(index)
    return by_track


def create_pipeline_job(
    input_video: Path,
    *,
    output_root: Path | None = None,
    run_id: str | None = None,
    skip_video: bool = False,
    force_fake: bool = False,
) -> FakePipelineJob | RealPipelineJob:
    """Select the real pipeline when a Gemini key is configured, else the fixture pipeline."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key and not force_fake:
        return RealPipelineJob(
            input_video,
            output_root=output_root,
            run_id=run_id,
            skip_video=skip_video,
            gemini_api_key=gemini_key,
        )
    return FakePipelineJob(
        input_video,
        output_root=output_root,
        run_id=run_id,
        skip_video=skip_video,
    )
