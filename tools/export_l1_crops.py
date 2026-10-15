"""Export the PPE crops the classifier is least sure about, for L1 adjudication (P12).

    uv run python tools/export_l1_crops.py output/<run_id> --count 200

L1 (Sree Vardhan's vision-model check) is meant for exactly the cases the small PPE
classifier cannot settle. This picks person observations whose smoothed helmet or hi-vis
state is `unknown` (but the worker is large enough to judge), or whose confidence lies
within `--margin` of the rules' floor. At most two are taken per track, spread over the
clip. Crops are cut at original resolution with faces pixelated, and written to
`output/<run_id>/l1_export/` with a `manifest.jsonl` that L1 can join back to the bundle
by frame and track.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import cv2

from pipeline.cache.pass1_store import Pass1Store
from pipeline.render.privacy import anonymise
from shared.config import load_config
from shared.enums import PERSON_CLASS
from shared.schemas.run import RunManifest
from tools.label_ppe import Sample, raw_box

MIN_HEIGHT_PX = 60.0
# The temporal PPE filter needs a few observations: early `unknown`s are warm-up, not doubt.
WARM_UP_S = 1.0
PER_TRACK = 2
PAD = 0.25


def ambiguity(observation, floor: float, margin: float) -> float | None:
    """Higher = more ambiguous; None when the observation is not a candidate."""
    box = observation.box_oriented or observation.box_reference
    if box.height() < MIN_HEIGHT_PX or observation.interpolated:
        return None
    scores = []
    for record in (observation.helmet, observation.vest):
        if record is None:
            continue
        if record.state.value == "unknown" and record.visible:
            scores.append(1.0)
        elif abs(record.confidence - floor) <= margin:
            scores.append(1.0 - abs(record.confidence - floor) / margin)
    return max(scores) if scores else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--margin", type=float, default=0.15)
    args = parser.parse_args()

    config = load_config()
    floor = config.rules.ppe_confidence_floor
    manifest = RunManifest.model_validate_json(
        (args.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    store = Pass1Store(Path(manifest.diagnostics["work_dir"]) / "pass1.sqlite")
    candidates = defaultdict(list)
    frame_observations = {}
    first_seen: dict[str, float] = {}
    for record, observations in store.frames_with_observations():
        frame_observations[record.frame_index] = observations
        for o in observations:
            if o.object_class != PERSON_CLASS:
                continue
            first_seen.setdefault(o.canonical_track_id, o.video_time_s)
            if o.video_time_s - first_seen[o.canonical_track_id] < WARM_UP_S:
                continue
            score = ambiguity(o, floor, args.margin)
            if score is not None:
                candidates[o.canonical_track_id].append((score, record, o))
    rng = random.Random(42017)
    picked = []
    for rows in candidates.values():
        rows.sort(key=lambda row: -row[0])
        spaced = rows[:: max(1, len(rows) // PER_TRACK)][:PER_TRACK]
        picked += spaced
    rng.shuffle(picked)
    picked = sorted(picked, key=lambda row: -row[0])[: args.count]
    out = args.run_dir / "l1_export"
    out.mkdir(exist_ok=True)
    wanted = defaultdict(list)
    for score, record, o in picked:
        wanted[record.source_index].append((score, record, o))
    capture = cv2.VideoCapture(manifest.input_video.path)
    canvas = (config.intake.target_width, config.intake.target_height)
    rows = []
    index, last = -1, max(wanted, default=-1)
    while index < last:
        if not capture.grab():
            break
        index += 1
        if index not in wanted:
            continue
        ok, raw = capture.retrieve()
        if not ok:
            continue
        height, width = raw.shape[:2]
        scale = min(canvas[0] / width, canvas[1] / height)
        offset = ((canvas[0] - width * scale) / 2, (canvas[1] - height * scale) / 2)
        for score, record, o in wanted[index]:
            frame = frame_observations[record.frame_index]
            private = anonymise(
                raw, frame, scale=1 / scale, offset=(offset[0] / scale, offset[1] / scale)
            )
            b = o.box_oriented or o.box_reference
            x1, y1, x2, y2 = raw_box((b.x1, b.y1, b.x2, b.y2), (width, height), canvas)
            pad_x, pad_y = int((x2 - x1) * PAD), int((y2 - y1) * PAD / 2)
            crop = private[max(0, y1 - pad_y) : y2 + pad_y, max(0, x1 - pad_x) : x2 + pad_x]
            name = f"f{record.frame_index:06d}_{o.canonical_track_id.split(':')[-1]}.jpg"
            cv2.imwrite(str(out / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            sample = Sample(
                sample_id=name[:-4],
                frame_index=record.frame_index,
                source_index=record.source_index,
                time_s=round(record.video_time_s, 3),
                track_id=o.canonical_track_id,
                box=(round(b.x1, 1), round(b.y1, 1), round(b.x2, 1), round(b.y2, 1)),
            )
            rows.append(
                {
                    **asdict(sample),
                    "crop": name,
                    "ambiguity": round(score, 3),
                    "helmet": o.helmet.model_dump(mode="json") if o.helmet else None,
                    "vest": o.vest.model_dump(mode="json") if o.vest else None,
                }
            )
    capture.release()
    (out / "manifest.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"exported {len(rows)} ambiguous crops from {len(candidates)} tracks to {out}")


if __name__ == "__main__":
    main()
