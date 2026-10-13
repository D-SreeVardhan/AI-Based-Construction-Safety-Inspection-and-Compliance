"""Typed contract for incident narration (v7 §45.5).

The model sees only a ``WordingRequest`` and may only return a ``WordingResponse``. Everything
the rule engine decided (rule, severity, status, action code) stays outside the prompt.
"""

from __future__ import annotations

import json
from typing import Literal

from shared.coordinates import StrictModel
from shared.enums import DistanceBand

Split = Literal["train", "val", "test", "holdout"]


class WordingRequest(StrictModel):
    schema_version: int = 1
    observed_subject: str
    observed_condition: str
    duration_s: float | None = None
    relative_band: DistanceBand | None = None
    deterministic_action: str
    allowed_entities: tuple[str, ...]

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class WordingResponse(StrictModel):
    reasoning: str
    recommended_wording: str


class Scenario(StrictModel):
    """A request plus the bookkeeping that never reaches the model."""

    scenario_id: str
    split: Split
    rule_id: str
    action_code: str
    source_run: str
    condition_family: int
    action_family: int
    request: WordingRequest
