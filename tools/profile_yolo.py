#!/usr/bin/env python3
"""Profile a YOLO-format detection dataset for CCTV-domain suitability.

Reports the two things that decide whether a dataset is useful here: whether it
carries negative PPE classes (workers *without* helmets and vests, which most
datasets omit), and what pixel scale its people occupy. The reference domain is
fixed CCTV, where a worker is 40-200 px tall and a helmet is 15-25 px. A dataset
of 600 px close-up workers trains a model that fails on deployment footage, so
the scale profile drives how much degradation augmentation it needs.

    python3 tools/profile_yolo.py data/external/ultralytics-ppe
    python3 tools/profile_yolo.py data/external/jhboyo-ppe --names helmet head vest
"""

import argparse
import collections
import os
import random
import sys

import cv2

# Class names that represent an absent item. Matched case-insensitively against
# a normalised form, so "NO-Hardhat", "no_helmet" and "head" all register.
NEGATIVE_MARKERS = ("no-", "no_", "without", "bare")
NEGATIVE_EXACT = ("head", "none")

PERSON_NAMES = ("person", "worker", "people")
CCTV_MIN_PX, CCTV_MAX_PX = 40, 200
SAMPLE_IMAGES = 600


def load_names(root, override=None):
    if override:
        return {i: n for i, n in enumerate(override)}
    for candidate in ("data.yaml", "dataset.yaml", "data.yml"):
        path = os.path.join(root, candidate)
        if not os.path.exists(path):
            continue
        names = {}
        with open(path) as fh:
            in_names = False
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("names:"):
                    in_names = True
                    # Inline list form: names: [a, b, c]
                    if "[" in stripped:
                        items = stripped.split("[", 1)[1].rstrip("]").split(",")
                        return {i: v.strip().strip("'\"")
                                for i, v in enumerate(items) if v.strip()}
                    continue
                if in_names:
                    if not stripped or not (stripped[0].isdigit() or stripped.startswith("-")):
                        break
                    if ":" in stripped:
                        key, value = stripped.split(":", 1)
                        try:
                            names[int(key.strip())] = value.strip().strip("'\"")
                        except ValueError:
                            break
                    elif stripped.startswith("-"):
                        names[len(names)] = stripped[1:].strip().strip("'\"")
        if names:
            return names
    return None


def is_negative(name):
    low = name.lower()
    return low in NEGATIVE_EXACT or any(m in low for m in NEGATIVE_MARKERS)


def label_files(root):
    found = []
    for dirpath, _, filenames in os.walk(root):
        if os.path.basename(dirpath.rstrip("/")) in ("images",):
            continue
        for name in filenames:
            if name.endswith(".txt") and name not in ("classes.txt", "notes.txt"):
                found.append(os.path.join(dirpath, name))
    return found


def image_for_label(label_path):
    parts = label_path.replace("/labels/", "/images/")
    for ext in (".jpg", ".jpeg", ".png", ".JPG", ".PNG"):
        candidate = os.path.splitext(parts)[0] + ext
        if os.path.exists(candidate):
            return candidate
    return None


def profile(root, override_names=None):
    names = load_names(root, override_names)
    labels = label_files(root)
    print(f"===== {root} =====")
    print(f"  {len(labels):,} label files")
    if not labels:
        print("  no YOLO label files found")
        return

    counts = collections.Counter()
    boxes_by_class = collections.defaultdict(list)
    for path in labels:
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    cid = int(float(parts[0]))
                    h = float(parts[4])
                except ValueError:
                    continue
                counts[cid] += 1
                boxes_by_class[cid].append((path, h))

    if names is None:
        names = {cid: f"class_{cid}" for cid in counts}
        print("  no data.yaml found — class names unknown, pass --names")

    print(f"  {sum(counts.values()):,} boxes across {len(counts)} classes")
    print(f"\n  {'class':<14} {'boxes':>9}  {'negative?':<10}")
    print("  " + "-" * 38)
    negatives = 0
    for cid, n in counts.most_common():
        name = names.get(cid, f"class_{cid}")
        neg = is_negative(name)
        negatives += n if neg else 0
        print(f"  {name:<14} {n:>9,}  {'YES' if neg else '':<10}")

    print(f"\n  negative-class boxes: {negatives:,} "
          f"({negatives / max(1, sum(counts.values())):.1%} of all boxes)")
    if negatives == 0:
        print("  WARNING: no negative PPE classes. Cannot train no-helmet/no-vest "
              "from this set alone.")

    # Person pixel heights, sampled. Needs real image dimensions since YOLO
    # heights are normalised.
    person_ids = [cid for cid, n in names.items()
                  if str(n).lower() in PERSON_NAMES]
    target_ids = person_ids or [cid for cid, n in names.items()
                                if str(n).lower() in ("helmet", "head")]
    scope = "person" if person_ids else "helmet/head (no person class)"
    pool = [(p, h) for cid in target_ids for p, h in boxes_by_class.get(cid, [])]
    if not pool:
        print("\n  no person-like boxes to measure scale from")
        return

    random.seed(0)
    random.shuffle(pool)
    heights = []
    seen_dims = {}
    for path, norm_h in pool:
        if len(heights) >= SAMPLE_IMAGES:
            break
        if path not in seen_dims:
            image = image_for_label(path)
            if image is None:
                seen_dims[path] = None
            else:
                img = cv2.imread(image)
                seen_dims[path] = None if img is None else img.shape[0]
        page_h = seen_dims[path]
        if page_h:
            heights.append(norm_h * page_h)

    if not heights:
        print("\n  could not resolve image dimensions to compute pixel scale")
        return

    heights.sort()
    q = lambda p: heights[int(len(heights) * p)]
    in_band = sum(1 for h in heights if CCTV_MIN_PX <= h <= CCTV_MAX_PX)
    print(f"\n  {scope} box height in px (n={len(heights)}):")
    print(f"    p10={q(.10):.0f}  p50={q(.50):.0f}  p90={q(.90):.0f}  max={heights[-1]:.0f}")
    print(f"    within CCTV band {CCTV_MIN_PX}-{CCTV_MAX_PX} px: "
          f"{in_band / len(heights):.1%}")
    if q(.50) > CCTV_MAX_PX * 1.5:
        print(f"    -> OUT OF DOMAIN: median {q(.50):.0f} px is far above the "
              f"CCTV band; needs downscaling augmentation (see plan 8.3)")
    elif in_band / len(heights) > 0.5:
        print("    -> broadly in domain for CCTV")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--names", nargs="*", default=None,
                        help="class names in id order, when data.yaml is absent")
    args = parser.parse_args()
    for root in args.roots:
        profile(root, args.names)
        print()


if __name__ == "__main__":
    sys.exit(main())
