"""Materialise the MJCSD stage-1 detector dataset (v7 §34.3).

    uv run python tools/build_stage1.py \
        --source data/external/mjcsd/extracted/DATASET --out data/working/stage1

Splits are frozen by seed and written to ``splits.json``; rerunning with the same inputs
reproduces them byte for byte. ``--max-train`` caps only the training split (evenly strided)
so a laptop-scale run still covers every camera and day; val and test are never subsampled.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import yaml

from pipeline.data.mjcsd import (
    SPLITS,
    STAGE1_CLASSES,
    assign_splits,
    load_class_map,
    read_records,
    stride_subsample,
)

SEED = 42017
RATIOS = (0.70, 0.15, 0.15)


def link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/working/stage1"))
    parser.add_argument("--class-map", type=Path, default=Path("config/class_map.yaml"))
    parser.add_argument("--max-train", type=int, default=None)
    args = parser.parse_args()

    mapping = load_class_map(args.class_map)
    records, skipped = read_records(args.source, mapping)
    assignment = assign_splits(records, RATIOS, SEED)
    by_split = {s: [r for r in records if assignment[r.group] == s] for s in SPLITS}
    by_split["train"] = stride_subsample(by_split["train"], args.max_train)

    if args.out.exists():
        shutil.rmtree(args.out)
    counts: dict[str, dict[str, int]] = {}
    for split, rows in by_split.items():
        class_counts: Counter[str] = Counter()
        for record in rows:
            link(record.image, args.out / "images" / split / f"{record.stem}.jpg")
            label_path = args.out / "labels" / split / f"{record.stem}.txt"
            label_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.write_text(
                "".join(f"{c} {x} {y} {w} {h}\n" for c, x, y, w, h in record.labels),
                encoding="utf-8",
            )
            class_counts.update(STAGE1_CLASSES[c] for c, *_ in record.labels)
        counts[split] = {"images": len(rows), **class_counts}

    (args.out / "dataset.yaml").write_text(
        yaml.safe_dump(
            {
                "path": str(args.out.resolve()),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": dict(enumerate(STAGE1_CLASSES)),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest = {
        "dataset_id": "mjcsd",
        "seed": SEED,
        "ratios": RATIOS,
        "split_unit": "camera/day",
        "camera_held_out": False,
        "class_map": mapping,
        "skipped": dict(skipped),
        "counts": counts,
        "groups": {split: sorted({r.group for r in rows}) for split, rows in by_split.items()},
    }
    (args.out / "splits.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "skipped": dict(skipped)}, indent=2))


if __name__ == "__main__":
    main()
