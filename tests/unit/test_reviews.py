"""Team review: consensus, precision per rule and reviewer agreement (Cohen's kappa)."""

from __future__ import annotations

import pytest

from evaluation.reviews import allowed_reviewers, cohen_kappa, consensus, summarize

RULES = {"a": "R1", "b": "R1", "c": "R3", "d": "R3", "e": "R3"}


def row(incident: str, reviewer: str, verdict: str, n: int, reason: str | None = None) -> dict:
    return {
        "id": n,
        "created_at": f"2026-10-15T10:00:{n:02d}Z",
        "incident_id": incident,
        "reviewer": reviewer,
        "verdict": verdict,
        "reason": reason,
    }


def test_kappa_matches_a_hand_worked_example() -> None:
    a = ["real", "real", "false_alarm", "false_alarm"]
    b = ["real", "false_alarm", "false_alarm", "false_alarm"]
    # observed 0.75; chance 0.5*0.25 + 0.5*0.75 = 0.5; kappa = 0.25 / 0.5
    assert cohen_kappa(a, b) == pytest.approx(0.5)
    assert cohen_kappa(a, a) == pytest.approx(1.0)
    assert cohen_kappa(["real"] * 3, ["real"] * 3) == 1.0  # all agree, no variety
    assert cohen_kappa([], []) is None


def test_consensus_needs_a_majority_of_decided_verdicts() -> None:
    assert consensus(["real", "real", "false_alarm"]) == "real"
    assert consensus(["real", "false_alarm"]) is None  # tie
    assert consensus(["unsure", "unsure"]) is None
    assert consensus(["unsure", "false_alarm"]) == "false_alarm"


def test_summary_uses_each_reviewers_latest_verdict() -> None:
    rows = [
        row("a", "Asha", "false_alarm", 1),
        row("a", "Asha", "real", 2),  # changed her mind: real counts
        row("a", "Ben", "real", 3),
        row("b", "Asha", "false_alarm", 4, "ppe"),
        row("b", "ben", "false_alarm", 5, "ppe"),  # names are case-insensitive
        row("c", "Asha", "real", 6),
        row("c", "Ben", "false_alarm", 7),  # tie: undecided
        row("d", "Asha", "unsure", 8),
        row("zzz", "Asha", "real", 9),  # not an incident of this run: ignored
    ]
    summary = summarize(rows, RULES)
    assert summary["reviewers"] == 2 and summary["reviewed"] == 4 and summary["decided"] == 2
    r1 = summary["by_rule"]["R1"]
    assert r1["real"] == 1 and r1["false_alarm"] == 1 and r1["precision"] == 0.5
    assert r1["reason:ppe"] == 1
    r3 = summary["by_rule"]["R3"]
    assert r3["undecided"] == 2 and r3["unreviewed"] == 1 and r3["precision"] is None
    [pair] = summary["agreement"]["pairs"]
    assert pair["reviewers"] == ["asha", "ben"] and pair["incidents"] == 3
    assert pair["agreement"] == pytest.approx(0.667, abs=1e-3)


def test_only_listed_reviewers_count_when_a_list_is_set() -> None:
    rows = [row("a", "Asha", "real", 1), row("a", "Troll", "false_alarm", 2)]
    allowed = allowed_reviewers({"SAFETY_REVIEWERS": "asha, Ben"})
    assert allowed == {"asha", "ben"}
    summary = summarize(rows, RULES, allowed=allowed)
    assert summary["reviewers"] == 1 and summary["by_rule"]["R1"]["real"] == 1
    assert allowed_reviewers({}) is None
