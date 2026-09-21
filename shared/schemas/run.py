from __future__ import annotations

from pydantic import Field

from shared.coordinates import StrictModel
from shared.enums import JobStage, ProcessingStatus, RuleId, RuleStatus


class RuleCoverageEntry(StrictModel):
    rule_id: RuleId
    status: RuleStatus
    reason_code: str


class PassTiming(StrictModel):
    stage: JobStage
    started_at: str
    finished_at: str
    duration_s: float = Field(ge=0.0)


class InputVideoMeta(StrictModel):
    path: str
    sha256: str
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    fps: float | None = None


class RunManifest(StrictModel):
    schema_version: int = 1
    run_id: str
    status: ProcessingStatus
    created_at: str
    completed_at: str | None = None
    mode: str = "fake_pipeline"
    package_version: str = "0.1.0"
    input_video: InputVideoMeta
    model_ids: dict[str, str] = Field(default_factory=dict)
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    gemini_status: str = "unused"
    scene_cache_status: str = "none"
    rule_coverage: tuple[RuleCoverageEntry, ...] = ()
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    pass_timings: tuple[PassTiming, ...] = ()
    output_artifacts: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = (
        "Approximate 2.5D visualization — positions and zones are inferred from video. "
        "Heuristic triage only; not legal advice or certified safety measurement."
    )
