#!/usr/bin/env python3
"""Profile SARD annotation files to rank candidate twin feeds.

Annotation format is whitespace-separated, with an action field that may be
empty or contain parenthesised codes, so coordinates are read from the right:

    frame_id  track_id  class  [action]  x1 y1 x2 y2

Reports the properties that decide whether a video can serve as a twin feed:
camera drift (measured on static scene objects), person pixel scale, crowding,
labelled duration, and PPE compliance split.

    python3 tools/profile_sard.py data/external/sard/*.txt
"""

import argparse
import collections
import os
import statistics
import sys

# Scene furniture that should not move if the camera is fixed. Scaffolding is
# excluded: it gets erected and repositioned, so its motion is genuine.
STATIC_CLASSES = ("slogan", "ebox", "board", "hopper", "hook", "rebar")
ASSUMED_FPS = 25
MIN_PERSON_PX = 40


def load(path):
    rows = []
    unparsed = 0
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 7:
                unparsed += 1
                continue
            try:
                frame = int(parts[0])
                track = int(parts[1])
                x1, y1, x2, y2 = (int(v) for v in parts[-4:])
            except ValueError:
                unparsed += 1
                continue
            rows.append((frame, track, parts[2], x1, y1, x2, y2))
    return rows, unparsed


def camera_drift(rows):
    """Worst-case positional spread of a long-lived static object, in pixels."""
    worst = None
    tracks = collections.defaultdict(list)
    for frame, track, cls, x1, y1, _, _ in rows:
        if cls in STATIC_CLASSES:
            tracks[(cls, track)].append((x1, y1))
    for (cls, track), obs in tracks.items():
        if len(obs) < 300:
            continue
        sd = max(
            statistics.pstdev([o[0] for o in obs]),
            statistics.pstdev([o[1] for o in obs]),
        )
        if worst is None or sd > worst[0]:
            worst = (sd, cls, track, len(obs))
    return worst


def wears(person, items, lo_frac, hi_frac, slack=0):
    px1, py1, px2, py2 = person
    height = py2 - py1
    lo = py1 + height * lo_frac - slack
    hi = py1 + height * hi_frac
    for x1, y1, x2, y2 in items:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if px1 <= cx <= px2 and lo <= cy <= hi:
            return True
    return False


def compliance(rows, sample_target=4000):
    by_frame = collections.defaultdict(lambda: collections.defaultdict(list))
    for frame, _, cls, x1, y1, x2, y2 in rows:
        by_frame[frame][cls].append((x1, y1, x2, y2))

    frames = sorted(by_frame)
    step = max(1, len(frames) // sample_target)
    tally = collections.Counter()
    for frame in frames[::step]:
        scene = by_frame[frame]
        helmets = scene.get("helmet", [])
        vests = scene.get("vest", [])
        for person in scene.get("person", []):
            if person[3] - person[1] < MIN_PERSON_PX:
                continue
            tally["n"] += 1
            if wears(person, helmets, 0.0, 0.45, slack=8):
                tally["helmet"] += 1
            if wears(person, vests, 0.15, 0.75):
                tally["vest"] += 1
    return tally, len(frames[::step])


def profile(path):
    rows, unparsed = load(path)
    name = os.path.basename(path)
    if not rows:
        print(f"{name}: no parsable rows")
        return None

    counts = collections.Counter(r[2] for r in rows)
    frames = {r[0] for r in rows}
    width = max(r[5] for r in rows)
    height = max(r[6] for r in rows)
    heights = sorted(r[6] - r[4] for r in rows if r[2] == "person")
    per_frame = sorted(collections.Counter(r[0] for r in rows if r[2] == "person").values())
    drift = camera_drift(rows)
    tally, sampled = compliance(rows)

    def pct(k):
        return tally[k] / tally["n"] if tally["n"] else 0.0

    def q(seq, p):
        return seq[int(len(seq) * p)] if seq else 0

    record = {
        "name": name,
        "boxes": len(rows),
        "unparsed": unparsed,
        "frames": len(frames),
        "minutes": len(frames) / ASSUMED_FPS / 60,
        "res": f"{width + 1}x{height + 1}",
        "person_p50": q(heights, 0.50),
        "person_p10": q(heights, 0.10),
        "person_p90": q(heights, 0.90),
        "crowd_p90": q(per_frame, 0.90),
        "crowd_max": per_frame[-1] if per_frame else 0,
        "drift": drift,
        "no_helmet": 1 - pct("helmet"),
        "no_vest": 1 - pct("vest"),
        "sampled": sampled,
        "classes": counts,
    }

    print(f"===== {name} =====")
    print(f"  {record['boxes']:,} boxes ({unparsed} unparsed) | {record['frames']:,} "
          f"labelled frames ~= {record['minutes']:.1f} min at {ASSUMED_FPS} fps")
    print(f"  frame size ~{record['res']}")
    print(f"  person height px: p10={record['person_p10']} p50={record['person_p50']} "
          f"p90={record['person_p90']}")
    print(f"  persons/frame: p90={record['crowd_p90']} max={record['crowd_max']}")
    if drift:
        sd, cls, track, n = drift
        verdict = "FIXED" if sd < 5 else "CHECK" if sd < 25 else "MOVING?"
        print(f"  camera: {verdict} (worst static '{cls}' track {track}, "
              f"{n:,} frames, sd {sd:.1f} px)")
    else:
        print("  camera: no long-lived static object to measure")
    print(f"  bare head {record['no_helmet']:.1%} | no vest {record['no_vest']:.1%} "
          f"(n={tally['n']:,} over {sampled:,} sampled frames)")
    print(f"  classes: {counts.most_common(7)}")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    records = [r for r in (profile(p) for p in sorted(args.paths)) if r]
    if len(records) < 2:
        return

    print("\n===== ranking =====")
    header = (f"{'file':>8} {'min':>7} {'p50px':>6} {'max/fr':>7} "
              f"{'bare%':>6} {'novest%':>8} {'drift':>7} {'boxes':>10}")
    print(header)
    print("-" * len(header))
    for r in sorted(records, key=lambda r: -r["minutes"]):
        drift = f"{r['drift'][0]:.1f}" if r["drift"] else "n/a"
        print(f"{r['name']:>8} {r['minutes']:7.1f} {r['person_p50']:6d} "
              f"{r['crowd_max']:7d} {r['no_helmet']:6.1%} {r['no_vest']:8.1%} "
              f"{drift:>7} {r['boxes']:10,}")


if __name__ == "__main__":
    sys.exit(main())
