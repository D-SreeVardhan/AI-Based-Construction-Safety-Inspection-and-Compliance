"""Scene bootstrap: Gemini keyframe proposals -> cross-keyframe consensus -> cached scene.

Gemini is called once per new video. The result is cached under every input that could
change it (video hash, model, prompt, selector, detector, and the selected frames), so a
re-run is free and a changed input can never reuse a stale scene.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import cv2
from pydantic import ValidationError

from llm.scene_proposals import SceneRequestError, request_scene_proposals
from pipeline.intake import FrameSampler
from pipeline.scene.consensus import build_consensus
from pipeline.scene.keyframes import SELECTOR_VERSION, Keyframe, select_keyframes
from pipeline.scene.proposals import SceneParseError, parse_response
from shared.config import AppConfig
from shared.schemas.scene import SceneKeyframe, SceneModel
from shared.schemas.tracks import Pass1TrackObservation

PREPROCESS_VERSION = "reference-letterbox-v1"

Requester = Callable[[str, str, Sequence[bytes]], str]


def _unavailable(reason: str, cache_key: str = "") -> SceneModel:
    return SceneModel(cache_key=cache_key, status="unavailable", status_reason=reason)


def _cache_key(
    *,
    video_sha256: str,
    model: str,
    prompt_version: str,
    detector_id: str,
    keyframes: list[Keyframe],
) -> str:
    payload = json.dumps(
        {
            "video": video_sha256,
            "model": model,
            "prompt": prompt_version,
            "preprocess": PREPROCESS_VERSION,
            "selector": SELECTOR_VERSION,
            "detector": detector_id,
            "frames": [k.sha256 for k in keyframes],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _read_cache(path: Path) -> SceneModel | None:
    try:
        return SceneModel.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def bootstrap_scene(
    *,
    sampler: FrameSampler,
    observations: Sequence[Pass1TrackObservation],
    video_sha256: str,
    detector_id: str,
    config: AppConfig,
    api_key: str,
    requester: Requester | None = None,
) -> tuple[SceneModel, str]:
    """Return ``(scene, cache_status)``; status is hit, miss, disabled or unavailable."""
    scene_cfg = config.scene
    try:
        keyframes, dropped = select_keyframes(
            sampler,
            observations,
            count=scene_cfg.maximum_keyframes,
            minimum_sharpness=scene_cfg.minimum_keyframe_sharpness,
        )
    except (RuntimeError, OSError) as exc:
        return _unavailable(f"keyframe_read_failed: {exc}"[:300]), "unavailable"
    if len(keyframes) < scene_cfg.minimum_keyframes:
        usable, need = len(keyframes), scene_cfg.minimum_keyframes
        return _unavailable(f"insufficient_keyframes: {usable} usable, need {need}"), "unavailable"

    key = _cache_key(
        video_sha256=video_sha256,
        model=scene_cfg.gemini_model,
        prompt_version=scene_cfg.prompt_version,
        detector_id=detector_id,
        keyframes=keyframes,
    )
    cache_path = Path(scene_cfg.cache_dir) / video_sha256 / f"{key}.json"
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached, "hit"
    if not api_key and requester is None:
        return _unavailable("gemini_api_key_missing", key), "disabled"

    width, height = config.intake.target_width, config.intake.target_height
    jpegs = []
    for keyframe in keyframes:
        small_w = scene_cfg.keyframe_image_width
        small_h = round(small_w * height / width)
        small = cv2.resize(keyframe.image_bgr, (small_w, small_h), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return _unavailable("keyframe_encode_failed", key), "unavailable"
        jpegs.append(buffer.tobytes())

    try:
        raw = (
            requester(api_key, scene_cfg.gemini_model, jpegs)
            if requester is not None
            else request_scene_proposals(api_key, scene_cfg.gemini_model, jpegs)
        )
    except SceneRequestError as exc:
        return _unavailable(str(exc)[:300], key), "unavailable"

    try:
        frame_proposals, invalid = parse_response(
            raw, keyframe_count=len(keyframes), width=width, height=height
        )
    except SceneParseError as exc:
        return _unavailable(f"unusable_gemini_reply: {exc}"[:300], key), "unavailable"
    proposals, weak = build_consensus(
        frame_proposals,
        keyframe_indices=[k.frame_index for k in keyframes],
        width=width,
        height=height,
        config=scene_cfg,
    )
    scene = SceneModel(
        cache_key=key,
        status="ok",
        source="gemini_consensus",
        model_id=scene_cfg.gemini_model,
        prompt_version=scene_cfg.prompt_version,
        keyframes=tuple(
            SceneKeyframe(frame_index=k.frame_index, video_time_s=k.video_time_s, sha256=k.sha256)
            for k in keyframes
        ),
        proposals=tuple(proposals),
        rejected=(*dropped, *invalid, *weak),
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(scene.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return scene, "miss"
