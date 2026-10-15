"""SynthSite scoring: the metrics must reproduce the dataset's published baseline numbers."""

from __future__ import annotations

import pytest

from evaluation.synthsite_eval import bootstrap_ci, groups, metrics, split


def pairs(tp: int, fn: int, fp: int, tn: int) -> list[tuple[bool, bool]]:
    return [(True, True)] * tp + [(True, False)] * fn + [(False, True)] * fp + [(False, False)] * tn


def test_metrics_reproduce_published_yolo_world_scores() -> None:
    # SynthSite's confusion_matrix_yolo_world.csv: TP 101, FN 14, FP 61, TN 51
    m = metrics(pairs(101, 14, 61, 51))
    assert m["clips"] == 227
    assert m["precision"] == pytest.approx(0.6235, abs=1e-4)
    assert m["recall"] == pytest.approx(0.8783, abs=1e-4)
    assert m["specificity"] == pytest.approx(0.4554, abs=1e-4)
    assert m["f1"] == pytest.approx(0.7292, abs=1e-4)
    assert m["f2"] == pytest.approx(0.8119, abs=1e-4)


def test_empty_and_degenerate_inputs_do_not_divide_by_zero() -> None:
    assert metrics([])["f2"] == 0.0
    assert metrics(pairs(0, 0, 0, 5))["precision"] == 0.0


def test_bootstrap_interval_brackets_the_point_estimate() -> None:
    data = pairs(101, 14, 61, 51)
    low, high = bootstrap_ci(data, "f2", rounds=500)
    assert low < metrics(data)["f2"] < high
    assert bootstrap_ci(data, "f2", rounds=500) == [low, high]  # seeded: reproducible


def test_rows_split_into_tiers_and_a_fixed_dev_test_split() -> None:
    rows = [
        (f"clip_{n:04d}.mp4", "1" if n % 3 else "2", n % 2 == 0, n % 4 == 0) for n in range(200)
    ]
    out = groups(rows)
    assert len(out["overall"]) == 200 == len(out["tier1"]) + len(out["tier2"])
    assert len(out["dev"]) + len(out["test"]) == 200
    assert 0.2 < len(out["dev"]) / 200 < 0.4  # about 30 % for tuning
    assert split("veo3.1_0001.mp4") == split("veo3.1_0001.mp4")  # fixed, not random
