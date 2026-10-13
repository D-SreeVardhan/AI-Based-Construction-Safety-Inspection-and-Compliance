"""Static scene geometry proposed by the scene bootstrap (v7 §9, §39).

Everything here is a heuristic proposal in reference-canvas pixels, never a surveyed fact.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from shared.coordinates import StrictModel

ProposalType = Literal[
    "restricted_zone",
    "open_edge",
    "visible_guardrail",
    "barrier",
    "warning_sign",
    "traffic_zone",
    "machinery_operating_region",
]
GeometryType = Literal["polygon", "polyline"]
ProposalSource = Literal["gemini_consensus", "local_heuristic", "bundled_cache"]
ProtectionState = Literal["guarded", "unguarded_or_inadequate", "unknown"]
ProtectionVisibility = Literal["sufficient", "insufficient", "unknown"]

# Types whose geometry is a closed region rather than a line.
POLYGON_TYPES: frozenset[str] = frozenset(
    {"restricted_zone", "barrier", "warning_sign", "traffic_zone", "machinery_operating_region"}
)
POLYLINE_TYPES: frozenset[str] = frozenset({"open_edge", "visible_guardrail"})


class SceneKeyframe(StrictModel):
    frame_index: int = Field(ge=0)
    video_time_s: float = Field(ge=0.0)
    sha256: str = Field(min_length=64, max_length=64)


class SceneProposal(StrictModel):
    proposal_id: str
    proposal_type: ProposalType
    geometry_type: GeometryType
    # (x, y) in reference-canvas pixels.
    points: tuple[tuple[float, float], ...]
    visible_drop_or_open_side: bool | None = None
    protection_visibility: ProtectionVisibility | None = None
    protection_state: ProtectionState | None = None
    rationale: str = ""
    source: ProposalSource
    # supporting keyframes / eligible keyframes; computed locally, never taken from Gemini.
    agreement_score: float = Field(ge=0.0, le=1.0)
    supporting_keyframes: tuple[int, ...]
    eligible_keyframes: int = Field(ge=1)
    heuristic: bool = True

    @model_validator(mode="after")
    def _geometry_matches_type(self) -> SceneProposal:
        minimum = 3 if self.geometry_type == "polygon" else 2
        if len(self.points) < minimum:
            raise ValueError(f"{self.geometry_type} needs at least {minimum} points")
        expected = "polygon" if self.proposal_type in POLYGON_TYPES else "polyline"
        if self.geometry_type != expected:
            raise ValueError(f"{self.proposal_type} must be a {expected}")
        return self


class SceneModel(StrictModel):
    schema_version: int = 1
    cache_key: str
    # "ok" has usable proposals (possibly none); "unavailable" means the bootstrap did not run.
    status: Literal["ok", "unavailable"]
    status_reason: str | None = None
    source: ProposalSource | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    keyframes: tuple[SceneKeyframe, ...] = ()
    proposals: tuple[SceneProposal, ...] = ()
    # Human-readable reasons clusters were dropped (support too low, invalid geometry, ...).
    rejected: tuple[str, ...] = ()

    def of_type(self, proposal_type: ProposalType) -> tuple[SceneProposal, ...]:
        return tuple(p for p in self.proposals if p.proposal_type == proposal_type)
