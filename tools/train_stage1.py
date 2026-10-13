"""Fine-tune the stage-1 detector on MJCSD and compare it with the pretrained baseline.

    uv run python tools/train_stage1.py train --epochs 12
    uv run python tools/train_stage1.py evaluate --weights <run>/weights/best.pt

Both models are scored on the frozen test split after mapping to the two classes the
pipeline consumes: ``person`` and ``vehicle`` (every machinery class merged). The
pretrained COCO baseline contributes its person and vehicle-type classes. Test days are
unseen, but test cameras are not (see pipeline/data/mjcsd.py).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from evaluation.detection import Box, Detection, average_precision, precision_recall
from pipeline.data.mjcsd import STAGE1_CLASSES
from pipeline.vision import class_ids

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover
    YOLO = None  # type: ignore[assignment,misc]

DATA = Path("data/working/stage1")
RUN_DIR = Path("artifacts/checkpoints/stage1")
RUN_NAME = "yolo11n_mjcsd_v1"
BASELINE = Path("artifacts/models/stage1/yolo11n.pt")
REPORT = Path("evaluation/results/stage1.json")
SEED = 42017
OPERATING_CONFIDENCE = 0.20  # config/defaults.yaml stage1.confidence


def train(epochs: int, batch: int, imgsz: int, device: str) -> None:
    model = YOLO(str(BASELINE))
    model.train(
        data=str(DATA / "dataset.yaml"),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        workers=2,
        cache=False,
        optimizer="AdamW",
        lr0=0.0005,
        patience=8,
        close_mosaic=3,
        seed=SEED,
        deterministic=True,
        project=str(RUN_DIR.resolve()),
        name=RUN_NAME,
        exist_ok=True,
        plots=True,
        save_period=2,
    )


def ground_truth() -> tuple[dict[str, dict[str, list[Box]]], list[Path]]:
    """Merged-class boxes (pixels) per test image."""
    from_label: dict[str, dict[str, list[Box]]] = {"person": {}, "vehicle": {}}
    images = sorted((DATA / "images" / "test").glob("*.jpg"))
    for image in images:
        for kind in from_label:
            from_label[kind][image.stem] = []
        size = Image.open(image).size  # header read only
        for line in (DATA / "labels" / "test" / f"{image.stem}.txt").read_text().splitlines():
            cls, xc, yc, w, h = line.split()
            kind = "person" if STAGE1_CLASSES[int(cls)] == "person" else "vehicle"
            xc, yc, w, h = (
                float(xc) * size[0],
                float(yc) * size[1],
                float(w) * size[0],
                float(h) * size[1],
            )
            from_label[kind][image.stem].append((xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2))
    return from_label, images


def predict(
    weights: Path, images: list[Path], imgsz: int, device: str
) -> dict[str, list[Detection]]:
    model = YOLO(str(weights))
    person_ids, vehicle_ids = class_ids(model.names)
    out: dict[str, list[Detection]] = {"person": [], "vehicle": []}
    for image in images:
        result = model.predict(
            str(image), imgsz=imgsz, conf=0.05, iou=0.6, device=device, verbose=False
        )[0]
        for box, conf, cls in zip(
            result.boxes.xyxy.tolist(),
            result.boxes.conf.tolist(),
            result.boxes.cls.tolist(),
            strict=True,
        ):
            index = int(cls)
            kind = "person" if index in person_ids else "vehicle" if index in vehicle_ids else None
            if kind:
                out[kind].append(Detection(image.stem, float(conf), tuple(box)))  # type: ignore[arg-type]
    return out


def evaluate(weights: Path, imgsz: int, device: str) -> None:
    truth, images = ground_truth()
    report: dict[str, object] = {
        "test_images": len(images),
        "operating_confidence": OPERATING_CONFIDENCE,
        "split_unit": "camera/day (cameras are not held out)",
        "models": {},
    }
    for label, path in (("pretrained_yolo11n", BASELINE), ("mjcsd_finetuned", weights)):
        detections = predict(path, images, imgsz, device)
        scores = {}
        for kind in ("person", "vehicle"):
            precision, recall = precision_recall(
                detections[kind], truth[kind], OPERATING_CONFIDENCE
            )
            scores[kind] = {
                "ap50": round(average_precision(detections[kind], truth[kind]), 4),
                "precision_at_operating_point": round(precision, 4),
                "recall_at_operating_point": round(recall, 4),
                "ground_truth": sum(len(v) for v in truth[kind].values()),
            }
        report["models"][label] = {"weights": str(path), **scores}  # type: ignore[index]
        print(label, json.dumps(scores))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--epochs", type=int, default=12)
    fit.add_argument("--batch", type=int, default=8)
    check = sub.add_parser("evaluate")
    check.add_argument("--weights", type=Path, default=RUN_DIR / RUN_NAME / "weights" / "best.pt")
    for p in (fit, check):
        p.add_argument("--imgsz", type=int, default=960)
        p.add_argument("--device", default="mps")
    args = parser.parse_args()
    if args.command == "train":
        train(args.epochs, args.batch, args.imgsz, args.device)
    else:
        evaluate(args.weights, args.imgsz, args.device)


if __name__ == "__main__":
    main()
