#!/usr/bin/env python3
"""Vet and condition clips against the CCTV deployment domain.

The system is aimed at fixed CCTV, so every feed must plausibly have come from
one. Four subcommands:

    vet        measure a clip against the feed criteria, including a real
               static-camera test rather than an eyeballed frame comparison
    segments   find contiguous fixed-view windows inside a long recording
    stabilise  lock a drifting clip onto one reference frame
    condition  transcode to the working CCTV profile

The static-camera test matches ORB features against a reference frame and fits a
partial affine with RANSAC, so workers moving through the scene fall out as
outliers. A fixed camera holds sub-pixel displacement; a pan or a zoom does not.
This is how SARD videos 2, 3 and 4 were rejected, and how slab_pour was caught
drifting 145 px after v4 declared it static.

Reference domain is SARD ComplementarySet: 1920x1080, person heights
p10 76 px / p50 122 px / p90 200 px. Feeds are conditioned toward that so the
detector trains and runs in one domain.

    python3 tools/cctv.py vet data/source/slab_pour.mp4
    python3 tools/cctv.py segments data/external/sard/1.mp4
    python3 tools/cctv.py condition data/source/yard_truck.mp4 --crop-16x9 \
        --out data/working/yard_truck.mp4
"""

import argparse
import json
import os
import subprocess
import sys

import cv2
import numpy as np

TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 15
TARGET_CRF = 28

MIN_DURATION_S = 60.0
PROBE_SAMPLES = 24

# Drift tiers, in native pixels, measured as peak corner displacement.
# Native fixed CCTV sits under a pixel: SARD videos 9 and 8 measure 0.15 and
# 0.52 px. Stabilised stock footage does not reach that, but slab_pour comes
# down from 141.7 px to 3.39 px on the working plane, which bounds the metric
# error to a few centimetres against thresholds of 1.5 m and 3.0 m.
DRIFT_NATIVE_PX = 2.0
DRIFT_STABILISED_PX = 5.0


def _has_filter(name):
    """Whether the local ffmpeg build provides a given filter.

    Homebrew's ffmpeg is not always built with libfreetype, so `drawtext` may be
    missing. Timestamp burn-in is cosmetic, so a missing filter warns rather than
    aborting a transcode.
    """
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                         capture_output=True, text=True)
    return any(line.split()[1:2] == [name]
               for line in out.stdout.splitlines() if line.strip())


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,codec_name",
         "-show_entries", "format=duration,size", "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    duration = float(data["format"]["duration"])
    size = int(data["format"]["size"])
    return {
        "width": stream["width"],
        "height": stream["height"],
        "fps": float(num) / float(den),
        "codec": stream["codec_name"],
        "duration": duration,
        "size": size,
        "kbps": size * 8 / duration / 1000,
    }


def camera_drift(path, samples=PROBE_SAMPLES, region=None):
    """Peak global translation between sampled frames, in native pixels.

    `region` optionally restricts matching to a fractional band of the frame
    given as (top, bottom), e.g. (0.5, 1.0) for the lower half. Parallax means a
    single transform cannot hold a near working plane and a distant treeline at
    once, so the measurement that matters is taken over the plane the workers
    stand on, not the whole frame.

    Uses ORB features matched against the first sampled frame, with RANSAC
    fitting a partial affine transform. Workers moving through the scene become
    RANSAC outliers, so the estimate reflects camera motion rather than subject
    motion. Phase correlation was tried first and produced false peaks on scenes
    with repeating texture such as rebar grids and treelines.

    Returns None when the clip cannot be sampled or has too little static
    structure to match against.
    """
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 2:
        cap.release()
        return None

    orb = cv2.ORB_create(nfeatures=2000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    indices = np.linspace(0, total - 1, min(samples, total)).astype(int)

    reference = None
    scale = 1.0
    peak = 0.0
    measured = 0
    for index in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = cap.read()
        if not ok:
            continue
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if region is not None:
            top = int(grey.shape[0] * region[0])
            bottom = int(grey.shape[0] * region[1])
            grey = grey[top:bottom, :]
        if reference is None:
            scale = frame.shape[1] / 960
        resized = cv2.resize(grey, (960, int(960 * grey.shape[0] / grey.shape[1])))
        keypoints, descriptors = orb.detectAndCompute(resized, None)
        if descriptors is None or len(keypoints) < 50:
            continue
        if reference is None:
            reference = (keypoints, descriptors)
            continue

        pairs = matcher.knnMatch(reference[1], descriptors, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2)
                if m.distance < 0.75 * n.distance]
        if len(good) < 25:
            continue
        src = np.float32([reference[0][m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        matrix, inliers = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0
        )
        if matrix is None or inliers is None or int(inliers.sum()) < 15:
            continue

        # Report how far image corners move under the estimated transform, not
        # the matrix translation term. Translation is measured from the origin,
        # so a slow zoom about the frame centre inflates it even when nothing
        # has actually shifted. Corner displacement captures pan, rotation and
        # zoom in the one quantity that matters: how far a world point moves.
        h, w = resized.shape
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        moved = cv2.transform(corners, matrix).reshape(-1, 2)
        displacement = np.linalg.norm(moved - corners.reshape(-1, 2), axis=1)
        peak = max(peak, float(displacement.max()) * scale)
        measured += 1

    cap.release()
    return peak if measured >= 2 else None


def vet(path, region=None):
    info = probe(path)
    drift = camera_drift(path, region=region)
    aspect = info["width"] / info["height"]

    print(f"===== {os.path.basename(path)} =====")
    print(f"  {info['width']}x{info['height']} {info['codec']} "
          f"{info['fps']:.2f} fps  {info['duration']:.1f} s  "
          f"{info['size'] / 1e6:.1f} MB  {info['kbps']:.0f} kbps")

    checks = []
    checks.append((
        "landscape orientation",
        aspect >= 1.3,
        f"aspect {aspect:.2f} — CCTV is never portrait",
    ))
    checks.append((
        f"duration >= {MIN_DURATION_S:.0f} s",
        info["duration"] >= MIN_DURATION_S,
        f"{info['duration']:.1f} s — must outlast debounce plus a 30 s cooldown",
    ))
    scope = "whole frame" if region is None else f"rows {region[0]:.0%}-{region[1]:.0%}"
    if drift is None:
        checks.append(("static camera", False, "could not sample frames"))
    elif drift <= DRIFT_NATIVE_PX:
        checks.append((f"static camera ({scope})", True,
                       f"peak drift {drift:.2f} px — native fixed camera"))
    elif drift <= DRIFT_STABILISED_PX:
        checks.append((f"static camera ({scope})", True,
                       f"peak drift {drift:.2f} px — acceptable for a stabilised "
                       f"clip; state the residual as a metric error bound"))
    else:
        checks.append((f"static camera ({scope})", False,
                       f"peak drift {drift:.2f} px — above "
                       f"{DRIFT_STABILISED_PX} px, homography will not hold; "
                       f"try `cctv.py stabilise`"))
    checks.append((
        "resolution >= 1280 wide",
        info["width"] >= 1280,
        f"{info['width']} px wide",
    ))

    for label, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")

    ok = all(passed for _, passed, _ in checks)
    print(f"  verdict: {'usable as a twin feed' if ok else 'not a twin feed'}")
    return ok


def segments(path, step_s=5.0, min_length_s=MIN_DURATION_S, tolerance_px=None,
             downscale_to=960):
    """Find contiguous windows inside a long recording that hold one fixed view.

    A multi-hour recording of a site livestream is not one camera setup: the
    operator repositions the camera, the stream cuts between angles, and the
    encoder restarts. SARD video 1 measures 1,327 px of drift end to end for
    exactly this reason, yet contains long stretches that are rock steady.

    Samples a frame every `step_s` seconds and compares each against the anchor
    frame of the current run. When displacement exceeds `tolerance_px` the run
    closes and a new one opens at that frame. Runs shorter than `min_length_s`
    are discarded. Each surviving run is a candidate feed and can be cut out
    losslessly with ffmpeg -ss/-t -c copy.
    """
    if tolerance_px is None:
        tolerance_px = DRIFT_NATIVE_PX

    info = probe(path)
    cap = cv2.VideoCapture(path)
    fps = info["fps"]
    total = int(info["duration"] * fps)
    stride = max(1, int(round(step_s * fps)))
    scale = info["width"] / downscale_to

    orb = cv2.ORB_create(nfeatures=2000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def features(index):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = cap.read()
        if not ok:
            return None
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, (downscale_to,
                                  int(downscale_to * grey.shape[0] / grey.shape[1])))
        kp, desc = orb.detectAndCompute(small, None)
        if desc is None or len(kp) < 40:
            return None
        return kp, desc, small.shape

    def displacement(anchor, current):
        pairs = matcher.knnMatch(current[1], anchor[1], k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2)
                if m.distance < 0.75 * n.distance]
        if len(good) < 25:
            return None
        src = np.float32([current[0][m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([anchor[0][m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        matrix, inliers = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0
        )
        if matrix is None or inliers is None or int(inliers.sum()) < 15:
            return None
        h, w = current[2]
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        moved = cv2.transform(corners, matrix).reshape(-1, 2)
        return float(np.linalg.norm(
            moved - corners.reshape(-1, 2), axis=1
        ).max()) * scale

    print(f"scanning {os.path.basename(path)}: {info['duration'] / 60:.1f} min, "
          f"sampling every {step_s:.0f} s, tolerance {tolerance_px:.1f} px")

    runs = []
    anchor = None
    run_start = None
    last_good = None
    peak = 0.0

    for index in range(0, total, stride):
        current = features(index)
        if current is None:
            continue
        if anchor is None:
            anchor, run_start, last_good, peak = current, index, index, 0.0
            continue
        shift = displacement(anchor, current)
        if shift is None or shift > tolerance_px:
            runs.append((run_start, last_good, peak))
            anchor, run_start, last_good, peak = current, index, index, 0.0
        else:
            last_good = index
            peak = max(peak, shift)

    if anchor is not None:
        runs.append((run_start, last_good, peak))
    cap.release()

    keep = [r for r in runs if (r[1] - r[0]) / fps >= min_length_s]
    print(f"{len(runs)} runs found, {len(keep)} at least {min_length_s:.0f} s long")
    if not keep:
        print("  no usable fixed-view window; try a larger --tolerance")
        return []

    print(f"\n{'start':>10} {'end':>10} {'length':>9} {'peak drift':>11}   ffmpeg cut")
    print("-" * 78)
    for start, end, drift in sorted(keep, key=lambda r: -(r[1] - r[0])):
        t0, t1 = start / fps, end / fps
        print(f"{t0:9.1f}s {t1:9.1f}s {t1 - t0:8.1f}s {drift:10.2f}px   "
              f"-ss {t0:.1f} -t {t1 - t0:.1f}")
    return keep


def _frame_transforms(path, reference_index=None, downscale_to=960):
    """Estimate each frame's homography onto a reference frame.

    Locks every frame to one reference rather than smoothing motion, because the
    goal is a single valid homography for the whole clip, not pleasant-looking
    video. The middle frame is the default reference so the worst-case warp is
    halved relative to anchoring on the first frame.

    A 4-DoF partial affine is used deliberately. A full 8-DoF homography was
    tried and performed worse on slab_pour (12.0 px residual against 6.6 px):
    a homography only relates two views of a single plane, and these scenes mix
    the working deck, rebar cages and a distant treeline at different depths, so
    RANSAC fits an inconsistent model and over-warps. The constrained model is
    more stable on multi-depth scenes.

    Parallax means no single transform can hold every depth at once, so residual
    drift must be judged on the working plane rather than the whole frame. See
    the --region option on `vet`.
    """
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    native_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    if reference_index is None:
        reference_index = total // 2
    scale = native_width / downscale_to

    orb = cv2.ORB_create(nfeatures=3000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def features(frame):
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, (downscale_to,
                                 int(downscale_to * grey.shape[0] / grey.shape[1])))
        return orb.detectAndCompute(small, None)

    cap.set(cv2.CAP_PROP_POS_FRAMES, reference_index)
    ok, reference_frame = cap.read()
    if not ok:
        cap.release()
        raise RuntimeError(f"{path}: cannot read reference frame {reference_index}")
    ref_kp, ref_desc = features(reference_frame)

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    transforms = []
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        kp, desc = features(frame)
        matrix = None
        if desc is not None and len(kp) >= 40:
            pairs = matcher.knnMatch(desc, ref_desc, k=2)
            good = [m for m, n in (p for p in pairs if len(p) == 2)
                    if m.distance < 0.75 * n.distance]
            if len(good) >= 25:
                src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                dst = np.float32([ref_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
                candidate, inliers = cv2.estimateAffinePartial2D(
                    src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0
                )
                if candidate is not None and inliers is not None and inliers.sum() >= 20:
                    matrix = candidate.astype(np.float32)
                    # Rescale translation from downscaled to native pixels.
                    matrix[0, 2] *= scale
                    matrix[1, 2] *= scale
        transforms.append(matrix if matrix is not None else
                          (transforms[-1] if transforms else identity))
    cap.release()
    return transforms, reference_index


def stabilise(path, dest, fps=None, crf=18, reference_index=None):
    """Warp every frame onto one reference so a single homography stays valid."""
    info = probe(path)
    transforms, reference_index = _frame_transforms(path, reference_index)
    width, height = info["width"], info["height"]

    corners = np.float32(
        [[0, 0], [width, 0], [width, height], [0, height]]
    ).reshape(-1, 1, 2)
    worst = 0.0
    for matrix in transforms:
        moved = cv2.transform(corners, matrix).reshape(-1, 2)
        worst = max(worst, float(
            np.abs(moved - corners.reshape(-1, 2)).max()
        ))
    # Inset by the worst displacement so warped-in blank edges are cropped away.
    margin = int(np.ceil(worst)) + 2
    crop_w = (width - 2 * margin) // 2 * 2
    crop_h = (height - 2 * margin) // 2 * 2
    if crop_w < 320 or crop_h < 240:
        raise RuntimeError(
            f"{path}: drift of {worst:.0f} px leaves too little valid area"
        )
    print(f"  reference frame {reference_index}, worst warp {worst:.1f} px, "
          f"cropping {margin} px inset -> {crop_w}x{crop_h}")

    out_fps = fps or info["fps"]
    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{crop_w}x{crop_h}", "-r", str(out_fps), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-an", dest],
        stdin=subprocess.PIPE,
    )
    cap = cv2.VideoCapture(path)
    index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            matrix = transforms[min(index, len(transforms) - 1)]
            warped = cv2.warpAffine(
                frame, matrix, (width, height),
                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
            )
            encoder.stdin.write(
                warped[margin:margin + crop_h, margin:margin + crop_w].tobytes()
            )
            index += 1
    finally:
        cap.release()
        encoder.stdin.close()
        encoder.wait()
    print(f"{os.path.basename(path)} -> {dest}  ({index} frames)")


def condition(path, dest, crop_16x9=False, fps=TARGET_FPS, crf=TARGET_CRF,
              width=TARGET_WIDTH, height=TARGET_HEIGHT, timestamp=False):
    info = probe(path)
    filters = []

    if crop_16x9 and info["width"] / info["height"] < 1.3:
        # Take the widest full-width 16:9 window, anchored on the vertical
        # centre. Portrait source loses the top and bottom, which is where
        # stock footage puts sky and foreground clutter anyway.
        crop_h = int(info["width"] * 9 / 16)
        if crop_h > info["height"]:
            crop_h = info["height"]
        filters.append(f"crop={info['width']}:{crop_h}:0:(ih-{crop_h})/2")

    filters.append(
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    if timestamp:
        if _has_filter("drawtext"):
            filters.append(
                "drawtext=text='%{pts\\:hms}':x=12:y=12:fontsize=28:"
                "fontcolor=white:box=1:boxcolor=black@0.5"
            )
        else:
            print("  note: this ffmpeg lacks drawtext (no libfreetype); "
                  "skipping timestamp burn-in. Install with "
                  "`brew install ffmpeg` built against freetype, or omit "
                  "--timestamp. Tier 1 CCTV feeds already carry a DVR OSD.",
                  flush=True)

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    command = [
        "ffmpeg", "-y", "-v", "error", "-stats", "-i", path,
        "-vf", ",".join(filters),
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an", dest,
    ]
    subprocess.run(command, check=True)

    after = probe(dest)
    print(f"{os.path.basename(path)} -> {dest}")
    print(f"  {info['width']}x{info['height']} {info['fps']:.0f} fps "
          f"{info['kbps']:.0f} kbps  ->  {after['width']}x{after['height']} "
          f"{after['fps']:.0f} fps {after['kbps']:.0f} kbps "
          f"({after['size'] / 1e6:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    vet_parser = sub.add_parser("vet", help="measure a clip against feed criteria")
    vet_parser.add_argument("paths", nargs="+")
    vet_parser.add_argument("--region", nargs=2, type=float, metavar=("TOP", "BOTTOM"),
                            help="restrict the drift test to a fractional row band, "
                                 "e.g. 0.5 1.0 to measure only the working plane")

    cond = sub.add_parser("condition", help="transcode to the CCTV working profile")
    cond.add_argument("path")
    cond.add_argument("--out", required=True)
    cond.add_argument("--crop-16x9", action="store_true",
                      help="centre-crop a 16:9 window from portrait source")
    cond.add_argument("--fps", type=int, default=TARGET_FPS)
    cond.add_argument("--crf", type=int, default=TARGET_CRF)
    cond.add_argument("--width", type=int, default=TARGET_WIDTH)
    cond.add_argument("--height", type=int, default=TARGET_HEIGHT)
    cond.add_argument("--timestamp", action="store_true",
                      help="burn in a running timestamp, as a DVR would")

    seg = sub.add_parser("segments",
                         help="find fixed-view windows inside a long recording")
    seg.add_argument("paths", nargs="+")
    seg.add_argument("--step", type=float, default=5.0,
                     help="seconds between sampled frames, default 5")
    seg.add_argument("--min-length", type=float, default=MIN_DURATION_S,
                     help=f"discard runs shorter than this, default {MIN_DURATION_S:.0f} s")
    seg.add_argument("--tolerance", type=float, default=None,
                     help=f"px of drift allowed within a run, "
                          f"default {DRIFT_NATIVE_PX:.1f}")

    stab = sub.add_parser("stabilise",
                          help="lock a drifting clip onto one reference frame")
    stab.add_argument("path")
    stab.add_argument("--out", required=True)
    stab.add_argument("--crf", type=int, default=18)
    stab.add_argument("--fps", type=float, default=None)
    stab.add_argument("--reference", type=int, default=None,
                      help="reference frame index, default is the middle frame")

    args = parser.parse_args()
    if args.command == "vet":
        region = tuple(args.region) if args.region else None
        results = [vet(p, region=region) for p in args.paths]
        return 0 if all(results) else 1
    if args.command == "segments":
        for path in args.paths:
            segments(path, step_s=args.step, min_length_s=args.min_length,
                     tolerance_px=args.tolerance)
            print()
        return 0
    if args.command == "stabilise":
        stabilise(args.path, args.out, fps=args.fps, crf=args.crf,
                  reference_index=args.reference)
        return 0
    condition(args.path, args.out, crop_16x9=args.crop_16x9, fps=args.fps,
              crf=args.crf, width=args.width, height=args.height,
              timestamp=args.timestamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
