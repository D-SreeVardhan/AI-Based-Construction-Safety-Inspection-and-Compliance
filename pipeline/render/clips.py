"""Short evidence clips: the annotated source pane around each incident (v3).

Reviewers decide faster from a few seconds of video than from one still. Each clip is
cut from the finished 1080p video (so it carries the same overlays, and the same face
pixelation), cropped to the source pane, from 2 s before the incident began to 2 s
after it ended, at most `MAX_CLIP_S`. Clips are encoded a few at a time in parallel.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shared.schemas.incidents import IncidentRecord

PRE_S = 2.0
POST_S = 2.0
MAX_CLIP_S = 12.0
CLIP_HEIGHT = 480
WORKERS = 3
TIMEOUT_S = 120


def clip_window(incident: IncidentRecord, duration_s: float) -> tuple[float, float]:
    end = incident.resolved_at_s if incident.resolved_at_s is not None else duration_s
    start = max(0.0, incident.first_seen_s - PRE_S)
    stop = min(duration_s, end + POST_S, start + MAX_CLIP_S)
    return start, max(stop, start + 1.0)


def cut_clips(
    video: Path,
    incidents: Sequence[IncidentRecord],
    run_dir: Path,
    *,
    pane: tuple[int, int, int, int],
    duration_s: float,
) -> dict[str, str]:
    """{incident_id: relative clip path} for every clip that encoded successfully."""
    x, y, width, height = pane

    def one(incident: IncidentRecord) -> tuple[str, str | None]:
        start, stop = clip_window(incident, duration_s)
        relative = f"evidence/{incident.incident_id}.mp4"
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg", "-v", "error", "-y",
            "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{stop - start:.3f}",
            "-vf", f"crop={width}:{height}:{x}:{y},scale=-2:{CLIP_HEIGHT}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(target),
        ]  # fmt: skip
        try:
            done = subprocess.run(command, capture_output=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired):
            return incident.incident_id, None
        ok = done.returncode == 0 and target.is_file() and target.stat().st_size > 0
        return incident.incident_id, relative if ok else None

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(one, incidents))
    return {incident_id: path for incident_id, path in results if path}
