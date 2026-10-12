"""Annotated twin video renderer.

Produces a 1920×1080 H.264 MP4 from the source video with per-frame overlays:
  - Bounding boxes and track labels coloured by PPE state
  - Incident banners with rule ID and severity
  - Rule status panel in the bottom-left corner
  - Heuristic disclaimer watermark

Coordinate assumptions
----------------------
Track boxes in ``tracks.jsonl`` are in the same letterbox space as the
intake frames (target_width × target_height, default 1920×1080).  They are
drawn directly onto frames that have been letterboxed to the same canvas.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette (BGR) — avoid the generic blue hue
# ---------------------------------------------------------------------------
_C_OK = (60, 200, 60)          # green  — helmet/vest confirmed
_C_VIOLATION = (40, 40, 220)   # red    — violation confirmed
_C_UNKNOWN = (40, 180, 220)    # amber  — unknown state
_C_VEHICLE = (200, 160, 50)    # teal   — vehicle box
_C_BANNER_BG = (20, 20, 20)    # near-black banner background
_C_BANNER_ALERT = (40, 40, 220)  # red banner for alert
_C_BANNER_INFO = (130, 90, 30)   # dark amber for info
_C_TEXT = (240, 240, 240)      # off-white text
_C_WATERMARK = (80, 80, 80)    # dark grey watermark

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_THICKNESS_BOX = 2
_THICKNESS_TEXT = 1

# How long to show an incident banner after it resolves (extra hold seconds)
_BANNER_HOLD_S = 2.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _box_colour(helmet_state: str, vest_state: str) -> tuple[int, int, int]:
    """Pick a single box colour representing the worst violation."""
    if "no_helmet" in (helmet_state, vest_state) or "no_vest" in (helmet_state, vest_state):
        return _C_VIOLATION
    if helmet_state == "helmet" and vest_state == "vest":
        return _C_OK
    return _C_UNKNOWN


def _put_text_with_bg(
    frame: np.ndarray,
    text: str,
    x: int,
    y: int,
    *,
    scale: float = 0.5,
    fg: tuple[int, int, int] = _C_TEXT,
    bg: tuple[int, int, int] = _C_BANNER_BG,
    thickness: int = _THICKNESS_TEXT,
    alpha: float = 0.75,
) -> None:
    """Draw text with a semi-transparent background rectangle."""
    (tw, th), baseline = cv2.getTextSize(text, _FONT, scale, thickness)
    pad = 3
    x1, y1 = x - pad, y - th - pad
    x2, y2 = x + tw + pad, y + baseline + pad
    # clamp to frame
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(fw, x2), min(fh, y2)
    roi = frame[y1:y2, x1:x2]
    if roi.size:
        overlay = roi.copy()
        overlay[:] = bg
        cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, roi)
        frame[y1:y2, x1:x2] = roi
    cv2.putText(frame, text, (x, y), _FONT, scale, fg, thickness, cv2.LINE_AA)


def _draw_box(
    frame: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    colour: tuple[int, int, int],
    label: str,
) -> None:
    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, _THICKNESS_BOX)
    _put_text_with_bg(frame, label, x1, max(y1 - 4, 12), fg=colour)


def _draw_banner(
    frame: np.ndarray,
    lines: list[str],
    *,
    alert: bool = True,
    top: int = 0,
) -> int:
    """Draw a banner at *top* y-position. Returns y after the banner."""
    fh, fw = frame.shape[:2]
    bg = _C_BANNER_ALERT if alert else _C_BANNER_INFO
    line_h = 22
    pad = 6
    banner_h = len(lines) * line_h + pad * 2
    roi = frame[top : top + banner_h, 0:fw]
    overlay = roi.copy()
    overlay[:] = bg
    cv2.addWeighted(overlay, 0.80, roi, 0.20, 0, roi)
    frame[top : top + banner_h, 0:fw] = roi
    for i, line in enumerate(lines):
        y = top + pad + (i + 1) * line_h - 4
        cv2.putText(frame, line, (10, y), _FONT, 0.55, _C_TEXT, 1, cv2.LINE_AA)
    return top + banner_h


def _draw_status_panel(
    frame: np.ndarray,
    coverage: list[dict[str, Any]],
) -> None:
    """Draw a compact rule-status block in the bottom-left corner."""
    fh, fw = frame.shape[:2]
    lines = []
    for entry in coverage:
        rule = entry.get("rule_id", "?")
        status = entry.get("status", "?")
        mark = "[X]" if "alert" in status else ("[?]" if "inconclusive" in status else "[OK]")
        lines.append(f"{mark} {rule}: {status.replace('evaluated_', '').replace('_for_feed', '')}")
    if not lines:
        return
    line_h = 17
    pad = 5
    panel_h = len(lines) * line_h + pad * 2
    panel_w = 260
    y0 = fh - panel_h - 6
    roi = frame[y0 : y0 + panel_h, 6 : 6 + panel_w]
    overlay = roi.copy()
    overlay[:] = _C_BANNER_BG
    cv2.addWeighted(overlay, 0.70, roi, 0.30, 0, roi)
    frame[y0 : y0 + panel_h, 6 : 6 + panel_w] = roi
    for i, line in enumerate(lines):
        fg = _C_VIOLATION if "✗" in line else (_C_UNKNOWN if "?" in line else _C_OK)
        y = y0 + pad + (i + 1) * line_h - 2
        cv2.putText(frame, line, (10, y), _FONT, 0.42, fg, 1, cv2.LINE_AA)


def _draw_watermark(frame: np.ndarray) -> None:
    fh, fw = frame.shape[:2]
    text = "Heuristic triage — not legal advice"
    (tw, _), _ = cv2.getTextSize(text, _FONT, 0.40, 1)
    cv2.putText(frame, text, (fw - tw - 8, fh - 6), _FONT, 0.40, _C_WATERMARK, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------

def _build_track_index(
    tracks: list[dict[str, Any]],
) -> dict[float, list[dict[str, Any]]]:
    """Group observations by video_time_s for quick per-frame lookup."""
    by_time: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for obs in tracks:
        t = round(obs["video_time_s"], 4)
        by_time[t].append(obs)
    return dict(by_time)


def _nearest_obs(
    by_time: dict[float, list[dict[str, Any]]],
    sorted_times: list[float],
    video_time_s: float,
    max_gap_s: float = 0.10,
) -> list[dict[str, Any]]:
    """Return observations at the sampled time closest to *video_time_s*."""
    if not sorted_times:
        return []
    lo, hi = 0, len(sorted_times) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_times[mid] < video_time_s:
            lo = mid + 1
        else:
            hi = mid
    # check both neighbours
    best_t = sorted_times[lo]
    if lo > 0 and abs(sorted_times[lo - 1] - video_time_s) < abs(best_t - video_time_s):
        best_t = sorted_times[lo - 1]
    if abs(best_t - video_time_s) > max_gap_s:
        return []
    return by_time.get(best_t, [])


def _active_incidents(
    incidents: list[dict[str, Any]],
    video_time_s: float,
) -> list[dict[str, Any]]:
    return [
        inc
        for inc in incidents
        if inc["first_seen_s"] <= video_time_s <= inc.get("resolved_at_s", 1e9) + _BANNER_HOLD_S
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_annotated_video(
    *,
    input_video: Path,
    run_dir: Path,
    output_path: Path,
    target_width: int = 1920,
    target_height: int = 1080,
    output_fps: float = 15.0,
) -> None:
    """Render an annotated twin video for the completed run in *run_dir*.

    Reads ``tracks.jsonl``, ``incidents.json``, and ``run_manifest.json``
    from *run_dir*.  Writes an H.264 MP4 to *output_path*.
    """
    tracks_path = run_dir / "tracks.jsonl"
    incidents_path = run_dir / "incidents.json"
    manifest_path = run_dir / "run_manifest.json"

    if not tracks_path.exists():
        raise RuntimeError(f"tracks.jsonl not found in {run_dir}")

    tracks: list[dict[str, Any]] = [
        json.loads(line)
        for line in tracks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    incidents: list[dict[str, Any]] = []
    if incidents_path.exists():
        incidents = json.loads(incidents_path.read_text(encoding="utf-8")).get("incidents", [])
    coverage: list[dict[str, Any]] = []
    if manifest_path.exists():
        coverage = json.loads(manifest_path.read_text(encoding="utf-8")).get("rule_coverage", [])

    by_time = _build_track_index(tracks)
    sorted_times = sorted(by_time)

    cap = cv2.VideoCapture(str(input_video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open source video: {input_video}")

    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Letterbox geometry — mirrors pipeline/intake
        scale = min(target_width / src_w, target_height / src_h)
        lb_w = round(src_w * scale)
        lb_h = round(src_h * scale)
        x_off = (target_width - lb_w) // 2
        y_off = (target_height - lb_h) // 2

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        dims = (target_width, target_height)
        writer = cv2.VideoWriter(str(output_path), fourcc, output_fps, dims)
        if not writer.isOpened():
            raise RuntimeError("Could not open VideoWriter for output")

        step = max(1, round(native_fps / output_fps))
        native_index = 0

        _log.info(
            "Rendering %s → %s (native %.2f fps, step %d, output %.2f fps)",
            input_video.name,
            output_path.name,
            native_fps,
            step,
            output_fps,
        )

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if native_index % step != 0:
                native_index += 1
                continue

            video_time_s = native_index / native_fps
            native_index += 1

            # Letterbox frame to target canvas
            if src_w != target_width or src_h != target_height:
                resized = cv2.resize(frame, (lb_w, lb_h), interpolation=cv2.INTER_AREA)
                canvas = np.zeros((target_height, target_width, 3), dtype=np.uint8)
                canvas[y_off : y_off + lb_h, x_off : x_off + lb_w] = resized
                frame = canvas

            # Draw active incidents as banners at the top
            active = _active_incidents(incidents, video_time_s)
            banner_y = 0
            for inc in active:
                rule = inc.get("rule_id", "?")
                sev = inc.get("severity", "medium")
                track = inc.get("canonical_track_id", "").split("/")[-1]
                t_start = inc.get("first_seen_s", 0)
                lines = [
                    f"[!] R{rule[1:]} ALERT  [{track}]  since {t_start:.1f}s  sev={sev}",
                    inc.get("observation_text", "")[:90],
                ]
                banner_y = _draw_banner(frame, lines, alert=True, top=banner_y)

            # Draw track observations
            obs_list = _nearest_obs(by_time, sorted_times, video_time_s)
            for obs in obs_list:
                box = obs.get("box_reference", {})
                x1 = int(box.get("x1", 0))
                y1 = int(box.get("y1", 0))
                x2 = int(box.get("x2", 0))
                y2 = int(box.get("y2", 0))
                obj_cls = obs.get("object_class", "person")
                track_short = obs.get("canonical_track_id", "").split("/")[-1]

                if obj_cls == "person":
                    hstate = (obs.get("helmet") or {}).get("state", "unknown")
                    vstate = (obs.get("vest") or {}).get("state", "unknown")
                    colour = _box_colour(hstate, vstate)
                    _h = {"helmet": "H:OK", "no_helmet": "H:NO", "unknown": "H:?"}
                    _v = {"vest": "V:OK", "no_vest": "V:NO", "unknown": "V:?"}
                    h_abbr = _h.get(hstate, hstate)
                    v_abbr = _v.get(vstate, vstate)
                    label = f"{track_short} {h_abbr} {v_abbr}"
                else:
                    colour = _C_VEHICLE
                    label = track_short or obj_cls

                _draw_box(frame, x1, y1, x2, y2, colour, label)

            # Rule status panel and watermark
            _draw_status_panel(frame, coverage)
            _draw_watermark(frame)

            # Timestamp
            _put_text_with_bg(
                frame,
                f"{video_time_s:.1f}s",
                target_width - 60,
                18,
                scale=0.45,
                bg=_C_BANNER_BG,
            )

            writer.write(frame)

        writer.release()

    finally:
        cap.release()

    # Re-encode with ffmpeg for better H.264 compatibility if available
    import shutil

    if shutil.which("ffmpeg"):
        tmp = output_path.with_suffix(".tmp.mp4")
        output_path.rename(tmp)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp),
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        tmp.unlink(missing_ok=True)
        if result.returncode != 0:
            _log.warning("ffmpeg re-encode failed: %s", result.stderr[:300])
            # restore original
            output_path.rename(tmp)
            tmp.rename(output_path)

    _log.info("Rendered annotated video → %s", output_path)
