"""Seed scenarios for the narration experiment (v7 §45.5.1).

Splits are made by source run, subject numbering, and wording family at once, so a test
scenario shares no run, track id, condition phrasing, or action phrasing with training. The
blind holdout is written separately in ``holdout.py`` and never passes through this generator.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from llm.narration.schema import Scenario, Split, WordingRequest
from shared.enums import DistanceBand

MACHINES = ("truck", "excavator", "crane", "loader", "roller")


@dataclass(frozen=True)
class RuleSeed:
    rule_id: str
    action_code: str
    conditions: tuple[str, ...]
    actions: tuple[str, ...]
    target: str | None = None  # extra allowed entity, e.g. a zone id
    machinery: bool = False
    banded: bool = False


RULE_SEEDS: tuple[RuleSeed, ...] = (
    RuleSeed(
        "R1",
        "helmet",
        (
            "no helmet visible on the head",
            "head appears uncovered, no hard hat seen",
            "repeatedly seen without head protection",
            "hard hat missing across several frames",
            "bare head observed while working",
            "no safety helmet detected",
        ),
        (
            "Verify this worker is wearing a hardhat.",
            "Check that the worker has suitable head protection on.",
            "Confirm a hard hat is worn before work continues.",
            "Ask the worker to put on a helmet and confirm.",
            "Pause the task and verify head protection.",
            "Make sure the worker wears a safety helmet.",
        ),
    ),
    RuleSeed(
        "R2",
        "vest",
        (
            "no high-visibility vest while a vehicle is in the same frame",
            "worker without hi-vis vest close to a vehicle",
            "vest missing near site vehicles",
            "no reflective jacket seen next to machinery",
            "hi-vis vest not worn near plant",
            "no visible high-visibility clothing near a vehicle",
        ),
        (
            "Verify this worker is wearing a high-visibility vest near moving machinery.",
            "Check the worker wears a hi-vis vest while vehicles are around.",
            "Confirm reflective clothing is worn near the machinery.",
            "Make sure a high-visibility vest is put on before working near vehicles.",
            "Pause and verify hi-vis clothing near the plant.",
            "Ask the worker to wear a vest around the vehicles and confirm.",
        ),
    ),
    RuleSeed(
        "R3",
        "zone_access",
        (
            "inside an inferred restricted zone",
            "standing within the marked exclusion area",
            "present in a zone that appears restricted",
            "entered the barrier-separated region",
            "located inside the apparent no-go area",
            "within a region inferred as restricted",
        ),
        (
            "Check on site whether this region is restricted and whether the worker is authorised.",
            "Confirm if the worker is permitted in this area.",
            "Verify access rights for this zone and move the worker out if not authorised.",
            "Check whether the area is restricted and the worker has permission.",
            "Review who is allowed in this zone and confirm the worker's authorisation.",
            "Find out whether this zone is off limits and whether the worker should be there.",
        ),
        target="restricted_zone-1",
    ),
    RuleSeed(
        "R4",
        "machinery_separation",
        (
            "close to active {machine}",
            "within the near band of a moving {machine}",
            "working next to an operating {machine}",
            "walking beside a moving {machine}",
            "inside the working distance of an active {machine}",
            "very near a {machine} that is moving",
        ),
        (
            "Check on site that pedestrians are kept clear of the machine's working area.",
            "Confirm the worker is kept away from the moving machine.",
            "Verify a safe separation between the worker and the machine.",
            "Ask the worker to move clear of the machine and confirm.",
            "Review how pedestrians are separated from plant on site.",
            "Make sure people stay out of the machine's reach.",
        ),
        machinery=True,
        banded=True,
    ),
    RuleSeed(
        "R5",
        "edge_protection",
        (
            "close to an open edge reported as unguarded",
            "near a visible drop with no protection reported",
            "working beside an exposed edge without guarding",
            "next to an edge that appears unprotected",
            "at the margin of an open side lacking a guardrail report",
            "within reach of an unprotected edge",
        ),
        (
            "Check on site whether this edge is exposed and what protection is in place.",
            "Verify edge protection is installed where the worker is.",
            "Confirm guardrails or barriers are in place at this edge.",
            "Inspect the edge and add protection if it is open.",
            "Look at this edge and confirm whether fall protection is present.",
            "Make sure the worker is kept away from the edge until it is protected.",
        ),
        target="open_edge-1",
        banded=True,
    ),
)

# (run ids, track-id range, wording families) per split.
_SPLITS: dict[Split, tuple[tuple[str, ...], range, tuple[int, ...]]] = {
    "train": (tuple(f"run-train-{i}" for i in range(1, 9)), range(1, 41), (0, 1, 2, 3)),
    "val": (("run-val-1", "run-val-2"), range(41, 61), (4,)),
    "test": (("run-test-1", "run-test-2"), range(61, 91), (5,)),
}


def _scenario(seed: RuleSeed, split: Split, index: int, rng: random.Random) -> Scenario:
    runs, tracks, families = _SPLITS[split]
    condition_family = rng.choice(families)
    action_family = rng.choice(families)
    track = f"person-{rng.choice(tracks)}"
    machine = rng.choice(MACHINES)
    condition = seed.conditions[condition_family].format(machine=machine)
    entities = [track]
    if seed.machinery:
        entities.append(machine)
    if seed.target:
        entities.append(seed.target)
    duration = round(rng.uniform(1.0, 30.0), 1) if rng.random() < 0.8 else None
    request = WordingRequest(
        observed_subject=f"Worker {track}",
        observed_condition=condition,
        duration_s=duration,
        relative_band=DistanceBand.NEAR if seed.banded else None,
        deterministic_action=seed.actions[action_family],
        allowed_entities=tuple(entities),
    )
    return Scenario(
        scenario_id=f"{split}-{seed.rule_id}-{index:04d}",
        split=split,
        rule_id=seed.rule_id,
        action_code=seed.action_code,
        source_run=rng.choice(runs),
        condition_family=condition_family,
        action_family=action_family,
        request=request,
    )


def build_scenarios(counts: dict[Split, int], seed: int) -> list[Scenario]:
    """Deterministic scenarios per split, balanced across rules and de-duplicated globally."""
    rng = random.Random(seed)
    seen: set[str] = set()
    out: list[Scenario] = []
    for split in ("train", "val", "test"):
        target = counts.get(split, 0)
        built = 0
        attempts = 0
        while built < target:
            attempts += 1
            if attempts > target * 50:
                raise RuntimeError(f"could not build {target} unique {split} scenarios")
            rule_seed = RULE_SEEDS[built % len(RULE_SEEDS)]
            scenario = _scenario(rule_seed, split, built, rng)
            key = scenario.request.canonical_json()
            if key in seen:
                continue
            seen.add(key)
            out.append(scenario)
            built += 1
    return out
