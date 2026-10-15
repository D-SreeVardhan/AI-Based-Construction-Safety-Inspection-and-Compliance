"""A finished run, loaded once for the risk register, the chatbot and the server."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from pipeline.output.bundle import read_model
from pipeline.output.risk import RiskAssessment, assess
from pipeline.rules.catalogue import CompiledCatalogue, load_catalogue
from shared.schemas.bundle import (
    INCIDENTS_FILE,
    INSIGHTS_FILE,
    RUN_MANIFEST_FILE,
    SCENE_FILE,
    TRACKS_SUMMARY_FILE,
    IncidentsFile,
    TracksSummaryFile,
)
from shared.schemas.incidents import IncidentRecord
from shared.schemas.insights import InsightsFile
from shared.schemas.run import RunManifest
from shared.schemas.scene import SceneCache

# A person identity counts as a worker seen once it was in view this long; shorter ones
# are mostly track fragments and would understate the share of workers exposed.
MIN_SEEN_S = 3.0


@dataclass
class RunBundle:
    run_dir: Path
    manifest: RunManifest
    incidents: list[IncidentRecord]
    insights: InsightsFile | None
    tracks: TracksSummaryFile | None
    zone_labels: dict[str, str]
    catalogue: CompiledCatalogue

    @classmethod
    def load(cls, run_dir: Path) -> RunBundle:
        run_dir = Path(run_dir)
        manifest = read_model(run_dir / RUN_MANIFEST_FILE, RunManifest)
        incidents = list(read_model(run_dir / INCIDENTS_FILE, IncidentsFile).incidents)
        insights_path, tracks_path = run_dir / INSIGHTS_FILE, run_dir / TRACKS_SUMMARY_FILE
        scene_path = run_dir / SCENE_FILE
        labels: dict[str, str] = {}
        if scene_path.is_file():
            scene = read_model(scene_path, SceneCache)
            labels = {
                p.proposal_id: p.label or p.proposal_id
                for proposals in scene.shot_proposals.values()
                for p in proposals
            }
        return cls(
            run_dir=run_dir,
            manifest=manifest,
            incidents=incidents,
            insights=read_model(insights_path, InsightsFile) if insights_path.is_file() else None,
            tracks=read_model(tracks_path, TracksSummaryFile) if tracks_path.is_file() else None,
            zone_labels=labels,
            catalogue=load_catalogue(),
        )

    @property
    def run_id(self) -> str:
        return self.manifest.run_id

    @property
    def duration_s(self) -> float:
        return self.manifest.input_video.duration_s or 0.0

    @cached_property
    def workers_seen(self) -> int:
        if self.tracks is None:
            return len({i.canonical_track_id for i in self.incidents if i.canonical_track_id})
        return sum(
            track.object_class == "person"
            and sum(span.end_s - span.start_s for span in track.presence) >= MIN_SEEN_S
            for track in self.tracks.tracks
        )

    @cached_property
    def risk(self) -> RiskAssessment:
        rules = {rule.rule_id: rule for rule in self.catalogue.catalogue.rules}
        return assess(
            self.manifest,
            self.incidents,
            self.insights,
            titles={rule_id: rule.title for rule_id, rule in rules.items()},
            severities={rule_id: str(rule.severity) for rule_id, rule in rules.items()},
            workers_seen=self.workers_seen,
        )
