from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from evaluation.detection import Detection, average_precision, iou, precision_recall
from pipeline.data.mjcsd import (
    STAGE1_CLASSES,
    Record,
    assign_splits,
    convert_labels,
    group_of,
    load_class_map,
    stride_subsample,
)
from pipeline.vision import class_ids

MAPPING = load_class_map(Path("config/class_map.yaml"))


def annotation(*labels: tuple[str, int, int, int, int]) -> dict[str, object]:
    return {
        "labels": [
            {
                "name": n,
                "x1": a,
                "y1": b,
                "x2": c,
                "y2": d,
                "size": {"width": 1920, "height": 1080},
            }
            for n, a, b, c, d in labels
        ]
    }


def test_labels_map_and_normalise() -> None:
    skipped: Counter[str] = Counter()
    rows = convert_labels(
        annotation(
            ("worker", 960, 540, 1056, 756),
            ("tanker", 0, 0, 192, 108),
            ("helmet", 10, 10, 40, 40),
            ("worker", 10, 10, 12, 12),
        ),
        MAPPING,
        skipped,
    )
    assert rows[0] == (STAGE1_CLASSES.index("person"), 0.525, 0.6, 0.05, 0.2)
    assert rows[1][0] == STAGE1_CLASSES.index("truck")
    assert len(rows) == 2
    assert skipped == Counter({"helmet": 1, "degenerate_box": 1})


def test_unknown_label_is_rejected_not_mapped() -> None:
    with pytest.raises(KeyError):
        convert_labels(annotation(("bulldozer", 0, 0, 100, 100)), MAPPING, Counter())


def test_group_is_camera_and_day() -> None:
    assert group_of("I020320201028170213_62") == "mjcsd/I0203/20201028"
    with pytest.raises(ValueError):
        group_of("not-a-frame")


def records(groups: dict[str, int]) -> list[Record]:
    return [
        Record(f"{g}_{i}", g, Path("x.jpg"), (), f"{g}{i}")
        for g, n in groups.items()
        for i in range(n)
    ]


def test_splits_keep_groups_whole_and_are_deterministic() -> None:
    rows = records({f"g{i}": 10 for i in range(40)})
    first = assign_splits(rows, (0.7, 0.15, 0.15), 42017)
    assert first == assign_splits(rows, (0.7, 0.15, 0.15), 42017)
    sizes = Counter(first.values())
    assert set(first) == {f"g{i}" for i in range(40)}
    assert sizes["train"] > sizes["val"] and sizes["train"] > sizes["test"]
    assert sizes["val"] >= 4 and sizes["test"] >= 4


def test_stride_subsample_spreads_evenly() -> None:
    rows = records({"a": 50, "b": 50})
    picked = stride_subsample(rows, 10)
    assert len(picked) == 10
    assert {r.group for r in picked} == {"a", "b"}
    assert stride_subsample(rows, None) is rows


def test_class_ids_resolve_by_name() -> None:
    coco = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane", 5: "bus"}
    people, vehicles = class_ids(coco)
    assert people == {0}
    assert vehicles == {1, 2, 3, 5}
    custom = dict(enumerate(STAGE1_CLASSES))
    people, vehicles = class_ids(custom)
    assert people == {0}
    assert vehicles == {1, 2, 3, 4}


def test_iou_and_average_precision() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    truth = {"a": [(0, 0, 10, 10)], "b": [(0, 0, 10, 10)]}
    perfect = [Detection("a", 0.9, (0, 0, 10, 10)), Detection("b", 0.8, (0, 0, 10, 10))]
    assert average_precision(perfect, truth) == 1.0
    # a confident false positive ahead of both hits halves precision at every recall point
    noisy = [Detection("a", 0.95, (50, 50, 60, 60)), *perfect]
    assert average_precision(noisy, truth) == pytest.approx(2 / 3)
    precision, recall = precision_recall(noisy, truth, 0.85)
    assert (precision, recall) == (pytest.approx(0.5), pytest.approx(0.5))


def test_duplicate_detections_do_not_double_count() -> None:
    truth = {"a": [(0, 0, 10, 10)]}
    twice = [Detection("a", 0.9, (0, 0, 10, 10)), Detection("a", 0.8, (0, 0, 10, 10))]
    precision, recall = precision_recall(twice, truth, 0.0)
    assert precision == 0.5 and recall == 1.0
