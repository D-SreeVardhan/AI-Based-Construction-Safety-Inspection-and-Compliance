from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from shared.enums import HelmetState, VestState
from shared.schemas.tracks import HelmetRecord, VestRecord

PROMPT_VERSION = "ppe-v1"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_PROMPT = """You are a construction safety inspector reviewing a CCTV image crop of a single worker.

Assess whether the worker is wearing:
1. A safety helmet / hardhat (rigid shell that protects the head).
2. A high-visibility vest (fluorescent yellow, orange, or green with reflective strips).

Use these exact state values:
  helmet   — clearly wearing a helmet or hardhat
  no_helmet — clearly NOT wearing one (bare head, cap, hood, but no hard shell)
  unknown  — head not visible, occluded, image too blurry, or box too small to judge

  vest     — clearly wearing a hi-vis vest
  no_vest  — clearly NOT wearing one
  unknown  — torso not visible, occluded, or too small to judge

Set confidence between 0.0 (no confidence) and 1.0 (certain).
Respond strictly in the provided JSON schema with no extra keys."""

_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "helmet_state": {"type": "string", "enum": ["helmet", "no_helmet", "unknown"]},
        "helmet_confidence": {"type": "number"},
        "vest_state": {"type": "string", "enum": ["vest", "no_vest", "unknown"]},
        "vest_confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["helmet_state", "helmet_confidence", "vest_state", "vest_confidence"],
}


def _jpeg_bytes(crop_bgr: np.ndarray, *, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Failed to encode crop to JPEG")
    return buf.tobytes()


def _crop_hash(jpeg: bytes) -> str:
    return hashlib.sha256(jpeg).hexdigest()[:16]


class AdjudicationResult:
    """PPE state returned by the Gemini adjudicator for one person crop."""

    __slots__ = ("helmet", "vest", "raw_json", "latency_ms", "cached")

    def __init__(
        self,
        *,
        helmet: HelmetRecord,
        vest: VestRecord,
        raw_json: str,
        latency_ms: int,
        cached: bool,
    ) -> None:
        self.helmet = helmet
        self.vest = vest
        self.raw_json = raw_json
        self.latency_ms = latency_ms
        self.cached = cached


def _parse_result(raw: str) -> AdjudicationResult:
    parsed = json.loads(raw)
    h_state = parsed.get("helmet_state", "unknown")
    v_state = parsed.get("vest_state", "unknown")
    return AdjudicationResult(
        helmet=HelmetRecord(
            state=HelmetState(h_state),
            confidence=float(parsed.get("helmet_confidence", 0.0)),
            visible=h_state != "unknown",
        ),
        vest=VestRecord(
            state=VestState(v_state),
            confidence=float(parsed.get("vest_confidence", 0.0)),
            visible=v_state != "unknown",
        ),
        raw_json=raw,
        latency_ms=0,
        cached=True,
    )


class GeminiPPEAdjudicator:
    """Assess PPE state from a person crop using Gemini Vision structured output.

    Results are content-cached under *cache_dir* by JPEG SHA-256 prefix to avoid
    redundant API calls when the same crop re-appears across runs.  The adjudicator
    is intentionally read-only with respect to existing IncidentRecords; callers
    apply the returned states to update track observations.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        *,
        cache_dir: Path | None = None,
        timeout_s: int = 30,
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiPPEAdjudicator")
        self._api_key = api_key
        self._model = model
        self._cache_dir = cache_dir
        self._timeout = timeout_s
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def assess(self, crop_bgr: np.ndarray) -> AdjudicationResult:
        """Return a PPE assessment for *crop_bgr*.  Caches by JPEG content hash."""
        jpeg = _jpeg_bytes(crop_bgr)
        key = _crop_hash(jpeg)

        if self._cache_dir:
            cached = self._read_cache(key)
            if cached is not None:
                return cached

        t0 = time.monotonic()
        raw = self._call_gemini(jpeg)
        latency_ms = int((time.monotonic() - t0) * 1000)

        result = _parse_result(raw)
        result.cached = False
        result.latency_ms = latency_ms

        if self._cache_dir:
            self._write_cache(key, raw)
        return result

    def _call_gemini(self, jpeg: bytes) -> str:
        url = f"{_GEMINI_BASE}/{self._model}:generateContent?key={self._api_key}"
        body = json.dumps(
            {
                "contents": [
                    {
                        "parts": [
                            {"text": _PROMPT},
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": base64.b64encode(jpeg).decode(),
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": _SCHEMA,
                },
            }
        ).encode()
        req = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self._timeout) as response:
                data = json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini {self._model} failed {exc.code}: {detail}") from exc
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:200]}")
        return candidates[0]["content"]["parts"][0]["text"]

    def _cache_path(self, key: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> AdjudicationResult | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            return _parse_result(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def _write_cache(self, key: str, raw: str) -> None:
        self._cache_path(key).write_text(raw, encoding="utf-8")
