"""MJCSD to stage-1 YOLO dataset conversion (v7 §34.1-34.3).

MJCSD frames come from five fixed cameras over about three weeks. The split unit is one
camera on one day, so consecutive frames of a recording never straddle train and test.
Camera identity is NOT held out (every camera appears in every split), so test scores
measure new days on known cameras and not new sites; reports must say so.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

STAGE1_CLASSES = ("person", "excavator", "crane", "truck", "other_machinery")
SPLITS = ("train", "val", "test")
_STEM = re.compile(r"^(I0\d{3})(\d{8})\d{6}_\d+$")
MIN_BOX_PX = 4


@dataclass(frozen=True)
class Record:
    stem: str
    group: str  # camera/day: the indivisible split unit
    image: Path
    labels: tuple[tuple[int, float, float, float, float], ...]  # class, xc, yc, w, h (0-1)
    sha256: str


def load_class_map(path: Path) -> dict[str, str | None]:
    mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
    unknown = {v for v in mapping.values() if v is not None and v not in STAGE1_CLASSES}
    if unknown:
        raise ValueError(f"class map targets are not stage-1 classes: {sorted(unknown)}")
    return mapping


def group_of(stem: str) -> str:
    match = _STEM.match(stem)
    if match is None:
        raise ValueError(f"unrecognised MJCSD file name: {stem}")
    return f"mjcsd/{match[1]}/{match[2]}"


def convert_labels(
    annotation: dict[str, object], mapping: dict[str, str | None], skipped: Counter[str]
) -> tuple[tuple[int, float, float, float, float], ...]:
    """YOLO rows for one annotation file. Unknown labels raise; unmapped ones are counted."""
    rows = []
    for item in annotation["labels"]:  # type: ignore[attr-defined]
        name = item["name"]
        if name not in mapping:
            raise KeyError(f"MJCSD label {name!r} is missing from the class map")
        target = mapping[name]
        if target is None:
            skipped[name] += 1
            continue
        width, height = item["size"]["width"], item["size"]["height"]
        x1, x2 = sorted((max(0, item["x1"]), min(width, item["x2"])))
        y1, y2 = sorted((max(0, item["y1"]), min(height, item["y2"])))
        if x2 - x1 < MIN_BOX_PX or y2 - y1 < MIN_BOX_PX:
            skipped["degenerate_box"] += 1
            continue
        rows.append(
            (
                STAGE1_CLASSES.index(target),
                round((x1 + x2) / 2 / width, 6),
                round((y1 + y2) / 2 / height, 6),
                round((x2 - x1) / width, 6),
                round((y2 - y1) / height, 6),
            )
        )
    return tuple(rows)


def read_records(source: Path, mapping: dict[str, str | None]) -> tuple[list[Record], Counter[str]]:
    """Every annotated image once; exact byte-duplicates are rejected, first one kept."""
    skipped: Counter[str] = Counter()
    records: list[Record] = []
    seen: set[str] = set()
    for annotation_path in sorted((source / "train_JSON").glob("*.json")):
        stem = annotation_path.stem
        image = source / "train_pic" / f"{stem}.jpg"
        if not image.exists():
            skipped["missing_image"] += 1
            continue
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest in seen:
            skipped["duplicate_image"] += 1
            continue
        seen.add(digest)
        labels = convert_labels(json.loads(annotation_path.read_text()), mapping, skipped)
        records.append(Record(stem, group_of(stem), image, labels, digest))
    return records, skipped


def assign_splits(
    records: list[Record], ratios: tuple[float, float, float], seed: int
) -> dict[str, str]:
    """Group -> split. Seeded shuffle, then each group goes to the split furthest below its
    image-count target, so ratios hold by images rather than by number of groups."""
    sizes = Counter(r.group for r in records)
    order = sorted(sizes, key=lambda g: hashlib.sha256(f"{seed}:{g}".encode()).hexdigest())
    total = sum(sizes.values())
    filled = dict.fromkeys(SPLITS, 0)
    assignment: dict[str, str] = {}
    for group in order:
        split = max(SPLITS, key=lambda s: ratios[SPLITS.index(s)] * total - filled[s])
        assignment[group] = split
        filled[split] += sizes[group]
    return assignment


def stride_subsample(records: list[Record], limit: int | None) -> list[Record]:
    """Even stride over name-sorted records so a cap keeps every day and camera represented."""
    if limit is None or len(records) <= limit:
        return records
    ordered = sorted(records, key=lambda r: r.stem)
    step = len(ordered) / limit
    return [ordered[int(i * step)] for i in range(limit)]
