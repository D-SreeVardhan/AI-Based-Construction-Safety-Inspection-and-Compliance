from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm.narration.evaluate import ARMS, promotion_gate, run_arm, score
from llm.narration.holdout import holdout_scenarios
from llm.narration.narrate import narrate
from llm.narration.params import expected_trainable
from llm.narration.prompts import messages, template_arm
from llm.narration.seed import build_scenarios
from llm.narration.validator import validate

COUNTS = {"train": 60, "val": 12, "test": 18}


@pytest.fixture(scope="module")
def scenarios():
    return build_scenarios(COUNTS, 1729)


def test_splits_do_not_leak(scenarios) -> None:
    by_split: dict[str, list] = {}
    for s in scenarios:
        by_split.setdefault(s.split, []).append(s)
    assert {k: len(v) for k, v in by_split.items()} == COUNTS
    for attribute in ("condition_family", "source_run"):
        seen = {split: {getattr(s, attribute) for s in rows} for split, rows in by_split.items()}
        assert seen["train"].isdisjoint(seen["test"]) or attribute == "source_run"
    assert {s.request.observed_subject for s in by_split["train"]}.isdisjoint(
        {s.request.observed_subject for s in by_split["test"]}
    )


def test_holdout_is_forty_author_written_rows() -> None:
    rows = holdout_scenarios()
    assert len(rows) == 40
    assert {r.split for r in rows} == {"holdout"}


def test_template_arm_passes_every_gate(scenarios) -> None:
    for scenario in [*scenarios, *holdout_scenarios()]:
        verdict = validate(scenario.request, scenario.action_code, template_arm(scenario.request))
        assert verdict.valid, (scenario.scenario_id, verdict.failures)


@pytest.mark.parametrize(
    ("raw", "failure"),
    [
        ("not json", "schema:not_json"),
        (json.dumps({"reasoning": "only one field"}), "schema:keys"),
    ],
)
def test_validator_rejects_malformed(scenarios, raw: str, failure: str) -> None:
    verdict = validate(scenarios[0].request, scenarios[0].action_code, raw)
    assert not verdict.valid
    assert failure in verdict.failures


def test_validator_rejects_law_verdict_and_rule_ids(scenarios) -> None:
    scenario = scenarios[0]
    good = json.loads(template_arm(scenario.request))
    bad = {
        "reasoning": good["reasoning"] + " This is a violation of Rule 7 under R3 severity.",
        "recommended_wording": good["recommended_wording"],
    }
    verdict = validate(scenario.request, scenario.action_code, json.dumps(bad))
    assert not verdict.valid
    assert {"citation:law_reference", "verdict:compliance_language"} <= set(verdict.failures)


def test_validator_rejects_invented_numbers_and_tracks(scenarios) -> None:
    scenario = scenarios[0]
    good = json.loads(template_arm(scenario.request))
    bad = {
        "reasoning": good["reasoning"] + " It happened 99 seconds near person-4242.",
        "recommended_wording": good["recommended_wording"],
    }
    verdict = validate(scenario.request, scenario.action_code, json.dumps(bad))
    assert "numbers:not_in_request" in verdict.failures
    assert "entities:unknown_track" in verdict.failures


def test_narrate_falls_back_for_every_failure_mode(scenarios) -> None:
    scenario = scenarios[0]
    template = json.loads(template_arm(scenario.request))

    def boom(_: list[dict[str, str]]) -> str:
        raise RuntimeError("model unavailable")

    for generate in (None, boom, lambda _: "garbage"):
        response, source = narrate(scenario.request, scenario.action_code, generate)
        assert source == "template"
        assert response.model_dump() == template

    response, source = narrate(
        scenario.request, scenario.action_code, lambda _: json.dumps(template)
    )
    assert source == "student"
    assert response.model_dump() == template


def test_prompt_never_contains_rule_or_severity(scenarios) -> None:
    for scenario in scenarios[:20]:
        text = json.dumps(messages(scenario.request, few_shot=True))
        assert scenario.rule_id not in scenario.request.canonical_json()
        assert "severity" not in scenario.request.canonical_json()
        assert text


def test_score_and_arms_on_template_outputs(scenarios) -> None:
    test_rows = [s for s in scenarios if s.split == "test"]
    outputs = run_arm(test_rows, "template", {})
    metrics = score(test_rows, outputs)
    assert metrics["n"] == len(test_rows)
    assert metrics["fully_valid_rate"] == 1.0
    assert metrics["unsupported_claim_rate"] == 0.0
    assert "template" in ARMS


def test_promotion_requires_unmeasured_criteria(scenarios) -> None:
    test_rows = [s for s in scenarios if s.split == "test"]
    metrics = score(test_rows, run_arm(test_rows, "template", {}))
    gate = promotion_gate(metrics)
    assert gate["false_refusal_le_5pct"]["measured"] is False
    assert gate["promoted"]["value"] is False


def test_lora_parameter_arithmetic_matches_plan(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"hidden_size": 1536, "num_attention_heads": 12, "num_key_value_heads": 2}),
        encoding="utf-8",
    )
    assert expected_trainable(config, rank=8, layers=8)["total"] == 311_296
