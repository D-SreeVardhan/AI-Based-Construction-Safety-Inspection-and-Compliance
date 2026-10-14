"""Per-incident evidence crops cut from the sampled frames."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

from pipeline.intake import FrameSampler
from shared.schemas.incidents import IncidentRecord
from shared.schemas.tracks import Pass1TrackObservation

_BOX_BGR = (0, 176, 255)
_MIN_HEIGHT = 360


def _area(obs: Pass1TrackObservation) -> float:
    box = obs.box_reference
    return max(0.0, box.x2 - box.x1) * max(0.0, box.y2 - box.y1)


def pick_evidence_observation(
    incident: IncidentRecord, observations: Sequence[Pass1TrackObservation]
) -> Pass1TrackObservation | None:
    """Largest view of the incident's track inside its alert window."""
    if incident.canonical_track_id is None:
        return None
    track = [o for o in observations if o.canonical_track_id == incident.canonical_track_id]
    end = incident.resolved_at_s if incident.resolved_at_s is not None else incident.first_seen_s
    window = [o for o in track if incident.first_seen_s <= o.video_time_s <= end]
    candidates = window or [o for o in track if o.frame_index == incident.source_frame_index]
    return max(candidates, key=_area, default=None)


def render_evidence(frame: np.ndarray, obs: Pass1TrackObservation, caption: str) -> np.ndarray:
    """Context crop around the worker with the tracked box and a caption strip."""
    h, w = frame.shape[:2]
    box = obs.box_reference
    bw, bh = box.x2 - box.x1, box.y2 - box.y1
    pad_x, pad_y = max(bw * 0.6, 40.0), max(bh * 0.35, 40.0)
    x1, y1 = max(0, int(box.x1 - pad_x)), max(0, int(box.y1 - pad_y))
    x2, y2 = min(w, int(box.x2 + pad_x)), min(h, int(box.y2 + pad_y))
    crop = frame[y1:y2, x1:x2].copy()
    scale = max(1.0, _MIN_HEIGHT / max(1, crop.shape[0]))
    if scale > 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    top_left = (int((box.x1 - x1) * scale), int((box.y1 - y1) * scale))
    bottom_right = (int((box.x2 - x1) * scale), int((box.y2 - y1) * scale))
    cv2.rectangle(crop, top_left, bottom_right, _BOX_BGR, 2)
    strip = np.full((26, crop.shape[1], 3), 24, dtype=np.uint8)
    cv2.putText(strip, caption, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, _BOX_BGR, 1, cv2.LINE_AA)
    return np.vstack([crop, strip])


def write_incident_evidence(
    *,
    sampler: FrameSampler,
    observations: Sequence[Pass1TrackObservation],
    incidents: Sequence[IncidentRecord],
    run_dir: Path,
) -> set[str]:
    """Write ``evidence/<incident_id>.jpg`` for every incident with a visible track.

    Returns the incident ids that received an image.
    """
    picks = {inc.incident_id: pick_evidence_observation(inc, observations) for inc in incidents}
    wanted = [obs.frame_index for obs in picks.values() if obs is not None]
    frames = sampler.frames_at(wanted) if wanted else {}
    written: set[str] = set()
    for incident in incidents:
        obs = picks[incident.incident_id]
        if obs is None or obs.frame_index not in frames:
            continue
        _, frame = frames[obs.frame_index]
        caption = f"{incident.rule_id.value} {obs.canonical_track_id} t={obs.video_time_s:.1f}s"
        image = render_evidence(frame, obs, caption)
        target = run_dir / incident.evidence_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            written.add(incident.incident_id)
    return written
