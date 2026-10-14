#!/usr/bin/env python3
"""Pick and cut 60 s demo clips from long SARD recordings.

SARD annotation frame ids are native frame indices, so every window of a long
recording can be scored without decoding it. Two subcommands:

    rank   score sliding 60 s windows by crowding, bare heads, missing vests,
           worker size, crane hooks / hoppers in view and camera stillness;
           writes a mid-window thumbnail per shortlisted window for review
    cut    re-encode one window to the demo profile (1920x1080, H.264, no audio)

    python3 tools/demo_clips.py rank data/external/sard/1.mp4 --thumbs /tmp/thumbs
    python3 tools/demo_clips.py cut data/external/sard/1.mp4 --start 3120 \
        --out data/demo/scaffold_bare_heads.mp4
"""

import argparse
import collections
import os
import statistics
import subprocess
import sys

import cv2
from profile_sard import MIN_PERSON_PX, STATIC_CLASSES, load, wears

WINDOW_S = 60.0
STEP_S = 30.0
SAMPLE_EVERY_S = 0.5
MACHINERY_CLASSES = ("hook", "hopper")
FIXED_SD_PX = 5.0


def _fps(path):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    num, den = out.stdout.strip().split("/")
    return float(num) / float(den)


def _window_drift(rows):
    """Worst positional spread of a static object inside one window, in pixels."""
    tracks = collections.defaultdict(list)
    for _, track, cls, x1, y1, _, _ in rows:
        if cls in STATIC_CLASSES:
            tracks[(cls, track)].append((x1, y1))
    spreads = [
        max(statistics.pstdev([o[0] for o in obs]), statistics.pstdev([o[1] for o in obs]))
        for obs in tracks.values()
        if len(obs) >= 20
    ]
    return max(spreads) if spreads else None


def score_windows(annotation, fps):
    rows, _ = load(annotation)
    by_frame = collections.defaultdict(list)
    for row in rows:
        by_frame[row[0]].append(row)
    last = max(by_frame)
    window, step, every = int(WINDOW_S * fps), int(STEP_S * fps), max(1, int(SAMPLE_EVERY_S * fps))
    results = []
    for start in range(0, last - window, step):
        sampled = [by_frame[f] for f in range(start, start + window, every) if f in by_frame]
        if len(sampled) < 0.8 * (window // every):
            continue
        persons = heads = vests = machinery = 0
        heights, ids = [], set()
        for frame_rows in sampled:
            scene = collections.defaultdict(list)
            for _, track, cls, x1, y1, x2, y2 in frame_rows:
                scene[cls].append((x1, y1, x2, y2))
                if cls == "person":
                    ids.add(track)
            machinery += any(scene[c] for c in MACHINERY_CLASSES)
            for person in scene["person"]:
                if person[3] - person[1] < MIN_PERSON_PX:
                    continue
                persons += 1
                heights.append(person[3] - person[1])
                heads += wears(person, scene["helmet"], 0.0, 0.45, slack=8)
                vests += wears(person, scene["vest"], 0.15, 0.75)
        if not persons:
            continue
        window_rows = [r for f in range(start, start + window) for r in by_frame.get(f, ())]
        results.append(
            {
                "start_s": start / fps,
                "workers": len(ids),
                "per_frame": persons / len(sampled),
                "bare": 1 - heads / persons,
                "no_vest": 1 - vests / persons,
                "p50_px": statistics.median(heights),
                "machinery": machinery / len(sampled),
                "drift": _window_drift(window_rows),
            }
        )
    return results


def _thumb(video, start_s, out_path):
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_MSEC, (start_s + WINDOW_S / 2) * 1000)
    ok, frame = cap.read()
    cap.release()
    if ok:
        cv2.imwrite(out_path, cv2.resize(frame, (640, 360)))
    return ok


def rank(video, annotation, top, thumbs):
    fps = _fps(video)
    windows = [
        w
        for w in score_windows(annotation, fps)
        if w["drift"] is not None and w["drift"] < FIXED_SD_PX and w["per_frame"] >= 1.5
    ]
    print(
        f"{os.path.basename(video)}: {len(windows)} fixed-camera windows with >= 1.5 "
        f"workers in view (fps {fps:g})"
    )
    header = (
        f"{'start':>8} {'workers':>7} {'/frame':>6} {'bare%':>6} {'novest%':>7} "
        f"{'p50px':>5} {'mach%':>5} {'drift':>5}"
    )
    for label, key in (
        ("bare heads", "bare"),
        ("missing vests", "no_vest"),
        ("crowded", "per_frame"),
        ("machinery", "machinery"),
        ("large workers", "p50_px"),
    ):
        print(f"\n-- top {top} by {label}\n{header}")
        for w in sorted(windows, key=lambda w: -w[key])[:top]:
            print(
                f"{w['start_s']:8.0f} {w['workers']:7d} {w['per_frame']:6.1f} "
                f"{w['bare']:6.0%} {w['no_vest']:7.0%} {w['p50_px']:5.0f} "
                f"{w['machinery']:5.0%} {w['drift']:5.1f}"
            )
            if thumbs:
                os.makedirs(thumbs, exist_ok=True)
                stem = os.path.splitext(os.path.basename(video))[0]
                _thumb(video, w["start_s"], os.path.join(thumbs, f"{stem}-{w['start_s']:.0f}.jpg"))


def cut(video, start_s, out, duration_s=WINDOW_S):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{start_s:.2f}",
            "-i",
            video,
            "-t",
            f"{duration_s:.2f}",
            "-an",
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            out,
        ],
        check=True,
    )
    print(f"wrote {out}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rank", help="score 60 s windows from the SARD annotation")
    r.add_argument("video")
    r.add_argument("--annotation", help="defaults to <video stem>.txt beside the video")
    r.add_argument("--top", type=int, default=5)
    r.add_argument("--thumbs", help="directory for mid-window thumbnails")
    c = sub.add_parser("cut", help="re-encode one window to the demo profile")
    c.add_argument("video")
    c.add_argument("--start", type=float, required=True, help="window start, seconds")
    c.add_argument("--duration", type=float, default=WINDOW_S)
    c.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.cmd == "rank":
        annotation = args.annotation or os.path.splitext(args.video)[0] + ".txt"
        rank(args.video, annotation, args.top, args.thumbs)
    else:
        cut(args.video, args.start, args.out, args.duration)


if __name__ == "__main__":
    sys.exit(main())
