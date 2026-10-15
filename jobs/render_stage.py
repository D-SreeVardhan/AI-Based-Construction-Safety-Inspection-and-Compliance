"""Pass three: render the side-by-side video and cut evidence images (v7 §6, §15.4).

Frames are decoded again (identically, see `FrameSource`) and joined with the pass-one
store and pass-two outputs by processed frame index.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from jobs.pass2 import Pass2Result
from pipeline.cache.pass1_store import Pass1Store
from pipeline.intake.frames import FrameSource, Letterbox, read_frame_at
from pipeline.intake.prefetch import Prefetch
from pipeline.mapping.camera_model import GroundMapper
from pipeline.render.clips import cut_clips
from pipeline.render.compositor import Compositor
from pipeline.render.encoder import VideoEncoder
from pipeline.render.heatmap import ExposureHeatmap
from pipeline.render.plan_view import PlanView
from pipeline.render.privacy import anonymise, face_band, pixelate
from pipeline.render.source_overlay import ALERT, draw_scene, render_source_frame
from pipeline.render.twin3d import TwinRenderer
from pipeline.render.twin_worker import TwinWorker
from shared.config import AppConfig
from shared.enums import PERSON_CLASS
from shared.errors import PipelineError
from shared.schemas.bundle import HEATMAP_FILE, SITE_VIEW_FILE, VIDEO_FILE, VIDEO_PROXY_FILE
from shared.schemas.incidents import IncidentRecord
from shared.schemas.scene import SceneCache
from shared.schemas.tracks import Pass1TrackObservation

CROP_PADDING = 0.15
EVIDENCE_JPEG_QUALITY = 92


@dataclass
class RenderResult:
    video: Path
    proxy: Path
    frames: int
    evidence: list[Path] = field(default_factory=list)
    heatmap: str | None = None
    site_view: str | None = None
    clips: dict[str, str] = field(default_factory=dict)


def _crop(image: np.ndarray, observation: Pass1TrackObservation, scale: float = 1.0) -> np.ndarray:
    box = observation.box_oriented or observation.box_reference
    pad_x, pad_y = box.width() * CROP_PADDING, box.height() * CROP_PADDING
    x1 = int(max(0, (box.x1 - pad_x) * scale))
    y1 = int(max(0, (box.y1 - pad_y) * scale))
    x2 = int(min(image.shape[1], (box.x2 + pad_x) * scale))
    y2 = int(min(image.shape[0], (box.y2 + pad_y) * scale))
    return image[y1:y2, x1:x2].copy()


def render_run(
    *,
    source: FrameSource,
    store: Pass1Store,
    pass2: Pass2Result,
    scene: SceneCache,
    config: AppConfig,
    run_dir: Path,
    title: str,
    mappers: Mapping[str, GroundMapper] | None = None,
    progress: Callable[[int], None] | None = None,
) -> RenderResult:
    render = config.render
    incidents = pass2.rules.incidents
    compositor = Compositor(
        render,
        title=title,
        duration_s=pass2.end_time_s,
        incidents=incidents,
        coverage=pass2.rules.coverage,
    )
    panes = _PaneRenderer(config, scene, pass2, mappers or {})
    heat = ExposureHeatmap((config.intake.target_width, config.intake.target_height))
    private = render.privacy == "faces"
    evidence_by_frame: dict[int, list[IncidentRecord]] = {}
    for incident in incidents:
        evidence_by_frame.setdefault(incident.source_frame_index, []).append(incident)

    video_path = run_dir / VIDEO_FILE
    evidence: list[Path] = []
    frames = 0
    stored = store.frames_with_observations()
    last_crops: dict[str, np.ndarray] = {}
    previous_time: float | None = None
    try:
        with VideoEncoder(
            video_path,
            width=render.output_width,
            height=render.output_height,
            fps=render.output_fps,
            crf=render.crf,
            preset=render.preset,
            codec=render.video_codec,
            proxy=run_dir / VIDEO_PROXY_FILE,
            proxy_height=render.proxy_height,
        ) as encoder:
            for decoded in Prefetch(source):
                record, observations = next(stored, (None, []))
                if record is None or record.frame_index != decoded.frame_index:
                    raise PipelineError(
                        "RENDER_FRAME_MISMATCH",
                        f"decoded frame {decoded.frame_index} has no matching pass-one record",
                    )
                output = pass2.frame_outputs.get(record.frame_index)
                panes.begin(record, observations, output)  # the twin starts in parallel
                # Faces are pixelated before anything is drawn or saved from this frame.
                image = anonymise(decoded.image, observations) if private else decoded.image
                dt = 0.0 if previous_time is None else record.video_time_s - previous_time
                previous_time = record.video_time_s
                heat.add(image, observations, output, min(max(dt, 0.0), 0.25))
                source_pane = render_source_frame(
                    image,
                    observations=observations,
                    output=output,
                    proposals=scene.proposals_for(record.shot_id),
                    time_s=record.video_time_s,
                    size=(render.pane_width, render.pane_height),
                    hud=False,
                )
                plan_pane = panes.finish()
                by_track = {o.canonical_track_id: o for o in observations}
                for incident in compositor.visible_incidents(record.video_time_s):
                    subject = by_track.get(incident.canonical_track_id or "")
                    if subject is not None:  # keep the last sighting once the worker leaves
                        last_crops[incident.incident_id] = _crop(image, subject)
                workers = sum(1 for o in observations if o.object_class == PERSON_CLASS)
                encoder.write(
                    compositor.compose(
                        source_pane,
                        plan_pane,
                        time_s=record.video_time_s,
                        crops=last_crops,
                        workers=workers,
                        machines=len(observations) - workers,
                    )
                )
                for incident in evidence_by_frame.get(record.frame_index, []):
                    evidence += _write_evidence(
                        run_dir,
                        incident,
                        image,
                        source,
                        record.source_index,
                        by_track,
                        observations if private else None,
                    )
                frames += 1
                if progress is not None:
                    progress(frames)
    finally:
        panes.close()

    heatmap = heat.save(run_dir / HEATMAP_FILE)
    site_view = _save_site_view(heat.background, scene, run_dir / SITE_VIEW_FILE)
    clips: dict[str, str] = {}
    if render.evidence_clips and incidents:
        x, y = compositor.left
        width, height = compositor.pane
        clips = cut_clips(
            video_path,
            incidents,
            run_dir,
            pane=(x, y, width, height),
            duration_s=pass2.end_time_s + 1.0 / config.intake.target_fps,
        )
    return RenderResult(
        video=video_path,
        proxy=run_dir / VIDEO_PROXY_FILE,
        frames=frames,
        evidence=evidence,
        heatmap=HEATMAP_FILE if heatmap else None,
        site_view=SITE_VIEW_FILE if site_view else None,
        clips=clips,
    )


def _save_site_view(background: np.ndarray | None, scene: SceneCache, path: Path) -> Path | None:
    """The first frame (faces pixelated) with every configured zone and edge drawn on it."""
    proposals = [p for shot in scene.shot_proposals.values() for p in shot]
    if background is None or not proposals:
        return None
    view = background.copy()
    draw_scene(view, proposals)
    cv2.imwrite(
        str(path),
        cv2.resize(view, (1280, 720), interpolation=cv2.INTER_AREA),
        [cv2.IMWRITE_JPEG_QUALITY, 88],
    )
    return path


class _PaneRenderer:
    """The right-hand pane: the 3D twin when the shot is calibrated, else the plan view.

    With `render.parallel_twin` the twin is drawn by a worker process: `begin` hands it
    the frame, the caller draws the source pane meanwhile, `finish` collects the result.
    """

    def __init__(
        self,
        config: AppConfig,
        scene: SceneCache,
        pass2: Pass2Result,
        mappers: Mapping[str, GroundMapper],
    ) -> None:
        render = config.render
        self.config = config
        self.scene = scene
        self.pass2 = pass2
        self.mappers = mappers
        self.size = (render.pane_width, render.pane_height)
        self.plan = PlanView(
            self.size,
            (config.intake.target_width, config.intake.target_height),
            config.intake.target_fps,
        )
        self.worker = (
            TwinWorker(self.size, config.intake.target_fps)
            if render.parallel_twin and mappers
            else None
        )
        self.twin: TwinRenderer | None = None
        self.shot: str | None = None
        self.calibrated = False
        self._pending: dict | None = None

    def begin(self, record, observations, output) -> None:
        if record.shot_id != self.shot:
            self.shot = record.shot_id
            self.plan.reset()
            mapper = self.mappers.get(record.shot_id)
            self.calibrated = mapper is not None
            proposals = self.scene.proposals_for(record.shot_id)
            if self.calibrated and self.worker is not None:
                self.worker.reset(mapper, proposals)
                self.twin = None
            elif self.calibrated:
                self.twin = TwinRenderer(
                    self.size, mapper, proposals, fps=self.config.intake.target_fps
                )
        inputs = {
            "time_s": record.video_time_s,
            "observations": observations,
            "output": output,
            "machine_states": self.pass2.machine_states.get(record.frame_index, {}),
            "machinery_classes": frozenset(self.config.stage1.machinery_classes),
            "positions": dict(self.pass2.twin.positions_at(record.frame_index))
            if self.pass2.twin is not None
            else None,
        }
        if self.calibrated and self.worker is not None:
            self.worker.submit(**inputs)
            self._pending = None
        else:
            self._pending = {**inputs, "proposals": self.scene.proposals_for(record.shot_id)}

    def finish(self) -> np.ndarray:
        if self.calibrated and self.worker is not None:
            return self.worker.result()
        inputs = self._pending or {}
        if self.calibrated and self.twin is not None:
            return self.twin.render(**{k: v for k, v in inputs.items() if k != "proposals"})
        return self.plan.render(
            observations=inputs["observations"],
            output=inputs["output"],
            proposals=inputs["proposals"],
        )

    def close(self) -> None:
        if self.worker is not None:
            self.worker.close()


def _write_evidence(
    run_dir: Path,
    incident: IncidentRecord,
    canvas: np.ndarray,
    source: FrameSource,
    source_index: int,
    by_track: dict[str, Pass1TrackObservation],
    private_observations: list[Pass1TrackObservation] | None = None,
) -> list[Path]:
    """Full frame with the subject highlighted, plus an original-resolution crop."""
    subject = by_track.get(incident.canonical_track_id or "")
    frame = canvas.copy()
    if subject is not None:
        box = subject.box_oriented or subject.box_reference
        cv2.rectangle(
            frame, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), ALERT, 3, cv2.LINE_AA
        )
    paths = [run_dir / incident.evidence_path]
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(paths[0]), frame, [cv2.IMWRITE_JPEG_QUALITY, EVIDENCE_JPEG_QUALITY])
    if subject is not None and incident.evidence_crop_path is not None:
        crop = _original_resolution_crop(source, source_index, subject, private_observations)
        if crop is None:
            crop = _crop(canvas, subject)
        crop_path = run_dir / incident.evidence_crop_path
        cv2.imwrite(str(crop_path), crop, [cv2.IMWRITE_JPEG_QUALITY, EVIDENCE_JPEG_QUALITY])
        paths.append(crop_path)
    return paths


def _original_resolution_crop(
    source: FrameSource,
    source_index: int,
    subject: Pass1TrackObservation,
    private_observations: list[Pass1TrackObservation] | None = None,
) -> np.ndarray | None:
    """Crop from the raw source frame so L1 sees full detail, not the 1080p canvas."""
    letterbox: Letterbox | None = source.letterbox
    if letterbox is None:
        return None
    try:
        raw = read_frame_at(source.path, source_index)
    except PipelineError:
        return None
    box = subject.box_oriented or subject.box_reference
    corners = np.array([[box.x1, box.y1, 1.0], [box.x2, box.y2, 1.0]]).T
    (x1, x2), (y1, y2) = (letterbox.inverse() @ corners)[:2]
    pad_x, pad_y = (x2 - x1) * CROP_PADDING, (y2 - y1) * CROP_PADDING
    top, left = int(max(0, y1 - pad_y)), int(max(0, x1 - pad_x))
    crop = raw[top : int(min(raw.shape[0], y2 + pad_y)), left : int(min(raw.shape[1], x2 + pad_x))]
    if not crop.size:
        return None
    crop = crop.copy()
    for other in private_observations or ():  # faces of everyone in the crop, not just one
        b = other.box_oriented or other.box_reference
        band = face_band((b.x1, b.y1, b.x2, b.y2))
        if other.object_class != PERSON_CLASS or band is None:
            continue
        points = np.array([[band[0], band[1], 1.0], [band[2], band[3], 1.0]]).T
        (bx1, bx2), (by1, by2) = (letterbox.inverse() @ points)[:2]
        pixelate(crop, (int(bx1) - left, int(by1) - top, int(bx2) - left, int(by2) - top))
    return crop
