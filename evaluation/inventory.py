from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from shared.coordinates import StrictModel
from shared.enums import RuleId, RuleStatus


class ClipEntry(StrictModel):
    path: str
    camera_id: str
    license: str
    split: str


class RuleDemoEntry(StrictModel):
    clip_id: str
    expected_interval_s: tuple[float, float]
    expected_status: RuleStatus
    evidence: str
    licensed_real_positive: bool
    use_for_precision_recall: bool

    @model_validator(mode="after")
    def _interval_ordered(self) -> RuleDemoEntry:
        start, end = self.expected_interval_s
        if end <= start:
            raise ValueError("expected_interval_s must be start < end")
        if self.use_for_precision_recall and not self.licensed_real_positive:
            raise ValueError("precision/recall claims require a licensed real positive")
        return self


class DemoSplits(StrictModel):
    development: tuple[str, ...]
    heldout: tuple[str, ...]


class DemoInventory(StrictModel):
    schema_version: int = Field(ge=1)
    frozen_at: str
    notes: str
    splits: DemoSplits
    clips: dict[str, ClipEntry]
    rules: dict[RuleId, RuleDemoEntry]

    @model_validator(mode="after")
    def _complete(self) -> DemoInventory:
        missing = [rule for rule in RuleId if rule not in self.rules]
        if missing:
            raise ValueError(f"inventory missing rules: {missing}")
        assigned = set(self.splits.development) | set(self.splits.heldout)
        overlap = set(self.splits.development) & set(self.splits.heldout)
        if overlap:
            raise ValueError(f"clip ids in both splits: {sorted(overlap)}")
        unknown = assigned - set(self.clips)
        if unknown:
            raise ValueError(f"split references unknown clips: {sorted(unknown)}")
        for rule, entry in self.rules.items():
            if entry.clip_id not in self.clips:
                raise ValueError(f"{rule.value} references unknown clip {entry.clip_id}")
        return self


def default_inventory_path() -> Path:
    return Path(__file__).resolve().parents[1] / "evaluation" / "demo_inventory.yaml"


def load_demo_inventory(path: Path | None = None) -> DemoInventory:
    inventory_path = path or default_inventory_path()
    with inventory_path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = yaml.safe_load(handle)
    return DemoInventory.model_validate(payload)
