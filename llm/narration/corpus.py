"""Corpus building for the narration experiment: seed, teacher pass, gate, MLX export."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

from llm.narration.holdout import holdout_scenarios
from llm.narration.prompts import PROMPT_VERSION, messages
from llm.narration.schema import Scenario, Split
from llm.narration.seed import build_scenarios
from llm.narration.validator import validate

WORK_DIR = Path("data/working/llm")
SCENARIOS = WORK_DIR / "scenarios.jsonl"
SPLITS = WORK_DIR / "splits.json"
TEACHER_RAW = WORK_DIR / "teacher_raw.jsonl"
MLX_DATA = WORK_DIR / "mlx"
SEED = 1729
# The plan's 1,800/300/300/120 needs hours of 7B generation on a 16 GB laptop, so the
# experiment runs at reduced scale; every count is recorded in the evaluation report.
DEFAULT_COUNTS: dict[Split, int] = {"train": 400, "val": 60, "test": 80}


def write_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_corpus(counts: dict[Split, int] | None = None) -> list[Scenario]:
    """Build and freeze scenarios plus the hand-written holdout, split before any generation."""
    scenarios = [*build_scenarios(counts or DEFAULT_COUNTS, SEED), *holdout_scenarios()]
    write_jsonl(SCENARIOS, (s.model_dump(mode="json") for s in scenarios))
    by_split: dict[str, list[str]] = {}
    for scenario in scenarios:
        by_split.setdefault(scenario.split, []).append(scenario.scenario_id)
    digest = hashlib.sha256(json.dumps(by_split, sort_keys=True).encode()).hexdigest()
    SPLITS.write_text(
        json.dumps({"seed": SEED, "sha256": digest, "splits": by_split}, indent=2) + "\n",
        encoding="utf-8",
    )
    return scenarios


def load_scenarios() -> list[Scenario]:
    return [Scenario.model_validate(row) for row in read_jsonl(SCENARIOS)]


def leakage_report(scenarios: list[Scenario]) -> dict[str, int]:
    """Counts of values shared across splits; every entry must be zero."""
    out: dict[str, int] = {}
    for label, getter in (
        ("subject", lambda s: s.request.observed_subject),
        ("condition", lambda s: s.request.observed_condition),
        ("action", lambda s: s.request.deterministic_action),
        ("source_run", lambda s: s.source_run),
    ):
        seen: dict[str, set[str]] = {}
        for scenario in scenarios:
            seen.setdefault(getter(scenario), set()).add(scenario.split)
        out[label] = sum(1 for splits in seen.values() if len(splits) > 1)
    return out


def generate_teacher(
    scenarios: list[Scenario],
    generate: Callable[[list[dict[str, str]]], tuple[str, float]],
    *,
    limit: int | None = None,
) -> int:
    """Append teacher outputs for scenarios not yet generated; resumable after interruption."""
    done = {row["scenario_id"] for row in read_jsonl(TEACHER_RAW)}
    pending = [s for s in scenarios if s.scenario_id not in done]
    if limit is not None:
        pending = pending[:limit]
    TEACHER_RAW.parent.mkdir(parents=True, exist_ok=True)
    with TEACHER_RAW.open("a", encoding="utf-8") as handle:
        for scenario in pending:
            text, seconds = generate(messages(scenario.request, few_shot=True))
            record = {"scenario_id": scenario.scenario_id, "raw": text, "seconds": seconds}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
    return len(pending)


def gate_and_export(scenarios: list[Scenario]) -> dict[str, object]:
    """Apply the teacher gates, then write MLX chat files for the surviving train/val rows."""
    raw = {row["scenario_id"]: row for row in read_jsonl(TEACHER_RAW)}
    kept: dict[Split, list[Scenario]] = {"train": [], "val": []}
    answers: dict[str, str] = {}
    stats: dict[str, Counter[str]] = {s: Counter() for s in ("train", "val", "test", "holdout")}
    for scenario in scenarios:
        row = raw.get(scenario.scenario_id)
        if row is None:
            stats[scenario.split]["missing"] += 1
            continue
        verdict = validate(scenario.request, scenario.action_code, str(row["raw"]))
        stats[scenario.split]["generated"] += 1
        if verdict.valid and verdict.response is not None:
            stats[scenario.split]["accepted"] += 1
            if scenario.split in kept:
                kept[scenario.split].append(scenario)  # type: ignore[index]
                answers[scenario.scenario_id] = json.dumps(
                    verdict.response.model_dump(), ensure_ascii=False
                )
        else:
            for failure in verdict.failures:
                stats[scenario.split][failure] += 1

    MLX_DATA.mkdir(parents=True, exist_ok=True)
    for split, name in (("train", "train"), ("val", "valid")):
        rows = [
            {
                "messages": [
                    *messages(s.request, few_shot=False),
                    {"role": "assistant", "content": answers[s.scenario_id]},
                ]
            }
            for s in kept[split]  # type: ignore[index]
        ]
        write_jsonl(MLX_DATA / f"{name}.jsonl", rows)
    # mlx_lm.lora requires a test file even when only training; reuse validation rows.
    write_jsonl(MLX_DATA / "test.jsonl", read_jsonl(MLX_DATA / "valid.jsonl"))

    audit_pool = [s.scenario_id for s in kept["train"]]
    random.Random(SEED).shuffle(audit_pool)
    audit_ids = [
        *audit_pool[: max(1, len(audit_pool) // 10)],
        *(s.scenario_id for s in scenarios if s.split in ("test", "holdout")),
    ]
    write_jsonl(
        WORK_DIR / "audit.jsonl",
        (
            {
                "scenario_id": sid,
                "request": next(s for s in scenarios if s.scenario_id == sid).request.model_dump(
                    mode="json"
                ),
                "teacher": raw.get(sid, {}).get("raw"),
            }
            for sid in audit_ids
        ),
    )
    return {
        "prompt_version": PROMPT_VERSION,
        "per_split": {split: dict(counter) for split, counter in stats.items()},
        "train_examples": len(kept["train"]),
        "valid_examples": len(kept["val"]),
        "leakage": leakage_report(scenarios),
    }
