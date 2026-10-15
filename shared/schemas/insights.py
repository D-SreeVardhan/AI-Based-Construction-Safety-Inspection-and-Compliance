"""Leading indicators for one run (`insights.json`), alongside the confirmed incidents.

Incidents count what persisted past a rule's debounce. Safety practice also wants the
precursors (OSHA's leading indicators, near-miss precursor analysis):

* exposure: worker-seconds during which a rule's hazard condition held, confirmed or not;
* brief exposures: the condition held, but for less than the debounce (a near miss for
  proximity and edge rules, a lapse for PPE and zones);
* closest approaches: the smallest worker-to-machine or worker-to-edge distance per pair,
  with its interval, even when no alert fired;
* zone exposure: where in the scene the exposure happened.

Every time is video seconds and every distance is in worker heights (WH), never metres.
"""

from __future__ import annotations

from pydantic import Field

from shared.coordinates import DistanceInterval, StrictModel
from shared.enums import DistanceBand, RuleId

INSIGHTS_SCHEMA_VERSION = 1


class RuleExposure(StrictModel):
    rule_id: RuleId
    exposure_s: float = Field(ge=0.0)
    workers_exposed: int = Field(ge=0)
    brief_exposures: int = Field(ge=0)
    confirmed_incidents: int = Field(ge=0)


class BriefExposure(StrictModel):
    rule_id: RuleId
    canonical_track_id: str
    start_s: float = Field(ge=0.0)
    end_s: float = Field(ge=0.0)
    proposal_ids: tuple[str, ...] = ()
    object_id: str | None = None
    closest: DistanceInterval | None = None


class ClosestApproach(StrictModel):
    rule_id: RuleId
    canonical_track_id: str
    target_id: str  # machine track id (R4) or edge proposal id (R5)
    time_s: float = Field(ge=0.0)
    distance: DistanceInterval
    band: DistanceBand | None = None


class AreaExposure(StrictModel):
    rule_id: RuleId
    proposal_id: str
    label: str = ""
    exposure_s: float = Field(ge=0.0)
    workers: int = Field(ge=0)


class WorkerExposure(StrictModel):
    canonical_track_id: str
    exposure_s: float = Field(ge=0.0)
    by_rule: dict[str, float] = Field(default_factory=dict)


class InsightsFile(StrictModel):
    schema_version: int = INSIGHTS_SCHEMA_VERSION
    run_id: str
    observed_s: float = Field(ge=0.0)
    workers_exposed: int = Field(default=0, ge=0)  # distinct track IDs with any exposure
    exposure: tuple[RuleExposure, ...]
    brief_exposures: tuple[BriefExposure, ...] = ()
    closest_approaches: tuple[ClosestApproach, ...] = ()
    area_exposure: tuple[AreaExposure, ...] = ()
    top_workers: tuple[WorkerExposure, ...] = ()
    heatmap_path: str | None = None
    zone_health: dict[str, float] = Field(default_factory=dict)
