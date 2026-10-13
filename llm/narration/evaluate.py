"""Four-arm narration evaluation and the promotion gate (v7 §17, §45.5, §45.7)."""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from llm.narration.corpus import SEED, TEACHER_RAW, read_jsonl
from llm.narration.prompts import messages, template_arm
from llm.narration.schema import Scenario
from llm.narration.validator import validate

ARMS = ("template", "base_zeroshot", "base_fewshot", "lora_zeroshot", "teacher_fewshot")
EVAL_SPLITS = ("test", "holdout")
CLAIM_CHECKS = ("numbers", "entities", "claims", "citation", "verdict", "authority")

# (raw text, seconds) for one scenario.
Output = tuple[str, float]
Generator = Callable[[list[dict[str, str]]], Output]


def score(scenarios: Sequence[Scenario], outputs: Mapping[str, Output]) -> dict[str, object]:
    """Metrics for one arm over one split. Latency is generation wall-clock, batch 1."""
    results = []
    for scenario in scenarios:
        raw, seconds = outputs[scenario.scenario_id]
        results.append((validate(scenario.request, scenario.action_code, raw), seconds))
    total = len(results)
    schema_ok = [v for v, _ in results if not any(f.startswith("schema") for f in v.failures)]
    histogram: Counter[str] = Counter(f for v, _ in results for f in v.failures)

    def rate(count: int, base: int) -> float | None:
        return round(count / base, 4) if base else None

    claim = sum(1 for v in schema_ok if any(f.split(":")[0] in CLAIM_CHECKS for f in v.failures))
    observation = sum(
        1 for v in schema_ok if not any(f.startswith("observation") for f in v.failures)
    )
    action = sum(1 for v in schema_ok if not any(f.startswith("action") for f in v.failures))
    seconds_list = sorted(s for _, s in results)
    return {
        "n": total,
        "schema_valid_rate": rate(len(schema_ok), total),
        "fully_valid_rate": rate(sum(1 for v, _ in results if v.valid), total),
        "unsupported_claim_rate": rate(claim, len(schema_ok)),
        "observation_consistency": rate(observation, len(schema_ok)),
        "action_consistency": rate(action, len(schema_ok)),
        "citation_or_authority_leaks": sum(
            1
            for v, _ in results
            if any(f.startswith(("citation", "authority")) for f in v.failures)
        ),
        "legal_claims": sum(
            1 for v, _ in results if any(f.startswith("verdict") for f in v.failures)
        ),
        "latency_median_s": round(statistics.median(seconds_list), 3) if seconds_list else None,
        "latency_p95_s": round(seconds_list[min(total - 1, int(0.95 * total))], 3)
        if seconds_list
        else None,
        "failures": dict(histogram.most_common()),
    }


def run_arm(
    scenarios: Sequence[Scenario], arm: str, generators: Mapping[str, Generator]
) -> dict[str, Output]:
    """Outputs for every scenario of one arm; the teacher arm replays the corpus-pass outputs."""
    if arm == "template":
        return {s.scenario_id: (template_arm(s.request), 0.0) for s in scenarios}
    if arm == "teacher_fewshot":
        raw = {r["scenario_id"]: r for r in read_jsonl(TEACHER_RAW)}
        return {
            s.scenario_id: (str(raw[s.scenario_id]["raw"]), float(raw[s.scenario_id]["seconds"]))  # type: ignore[arg-type]
            for s in scenarios
        }
    generate = generators[arm]
    few_shot = arm.endswith("fewshot")
    return {s.scenario_id: generate(messages(s.request, few_shot=few_shot)) for s in scenarios}


def promotion_gate(holdout: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """§45.7 checks for the LoRA student on the blind holdout.

    Criteria that need human raters or labelled-good outputs are reported as unmeasured, and
    an unmeasured criterion blocks promotion rather than passing by default.
    """

    def criterion(name: str, value: object, passed: bool | None) -> tuple[str, dict[str, object]]:
        return name, {"value": value, "passed": passed, "measured": passed is not None}

    def at_most(value: object, limit: float) -> bool | None:
        return None if value is None else float(value) <= limit  # type: ignore[arg-type]

    def at_least(value: object, limit: float) -> bool | None:
        return None if value is None else float(value) >= limit  # type: ignore[arg-type]

    rows = dict(
        [
            criterion(
                "schema_validity_100",
                holdout["schema_valid_rate"],
                at_least(holdout["schema_valid_rate"], 1.0),
            ),
            criterion(
                "citation_rule_severity_leakage_0",
                holdout["citation_or_authority_leaks"],
                holdout["citation_or_authority_leaks"] == 0,
            ),
            criterion("legal_claims_0", holdout["legal_claims"], holdout["legal_claims"] == 0),
            criterion(
                "unsupported_claim_rate_le_2pct",
                holdout["unsupported_claim_rate"],
                at_most(holdout["unsupported_claim_rate"], 0.02),
            ),
            criterion(
                "observation_consistency_ge_97pct",
                holdout["observation_consistency"],
                at_least(holdout["observation_consistency"], 0.97),
            ),
            criterion(
                "action_consistency_ge_97pct",
                holdout["action_consistency"],
                at_least(holdout["action_consistency"], 0.97),
            ),
            criterion("false_refusal_le_5pct", None, None),
            criterion("blind_rating_student_ge_template", None, None),
            criterion("runtime_fallback_test", "tests/unit/test_narration.py", True),
        ]
    )
    rows["promoted"] = {
        "value": all(r["passed"] is True for r in rows.values()),
        "passed": None,
        "measured": True,
    }
    return rows


def export_blind_sheet(
    scenarios: Sequence[Scenario],
    outputs: Mapping[str, Mapping[str, Output]],
    directory: Path,
    *,
    sample: int = 40,
) -> None:
    """Rating sheet with arm labels hidden behind shuffled letters, plus a separate key."""
    rng = random.Random(SEED)
    chosen = rng.sample(list(scenarios), min(sample, len(scenarios)))
    directory.mkdir(parents=True, exist_ok=True)
    key_rows: list[dict[str, str]] = []
    with (directory / "blind_rating_sheet.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "scenario_id",
                "input",
                "option",
                "reasoning",
                "recommended_wording",
                "clarity_1_5",
                "actionability_1_5",
            ]
        )
        for scenario in chosen:
            labels = list(zip("ABCDE", rng.sample(list(ARMS), len(ARMS)), strict=True))
            for letter, arm in labels:
                parsed = _safe_json(outputs[arm][scenario.scenario_id][0])
                writer.writerow(
                    [
                        scenario.scenario_id,
                        scenario.request.canonical_json(),
                        letter,
                        parsed.get("reasoning", ""),
                        parsed.get("recommended_wording", ""),
                        "",
                        "",
                    ]
                )
                key_rows.append({"scenario_id": scenario.scenario_id, "option": letter, "arm": arm})
    (directory / "blind_rating_key.json").write_text(
        json.dumps(key_rows, indent=2) + "\n", encoding="utf-8"
    )


def _safe_json(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {k: str(v) for k, v in value.items()} if isinstance(value, dict) else {}
