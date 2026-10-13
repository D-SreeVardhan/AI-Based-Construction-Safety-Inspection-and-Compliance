"""One Gemini request per video that proposes static scene geometry (v7 §9.2, §39.2).

The reply is untrusted: `pipeline.scene.proposals.parse_response` validates it and
`pipeline.scene.consensus` decides what survives. Nothing here is per-frame.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from llm.adjudicator import _GEMINI_BASE, _RETRYABLE_STATUS, _retry_delay_s
from shared.schemas.scene import POLYGON_TYPES, POLYLINE_TYPES

_PROMPT = """You analyze fixed construction-site frames only for visible scene geometry.
You receive numbered keyframes from one camera. For every keyframe return the static
regions you can directly see, as JSON matching the supplied schema.

Rules:
- Coordinates are {"y": int, "x": int} normalized from 0 to 1000 (top-left is 0,0).
- restricted_zone: a region supported by visible barriers, signs, operating plant, or a
  clearly separated exclusion area. Return a polygon.
- open_edge: an edge where the visible surface ends in a drop, opening, or exposed side.
  Return a polyline along the edge. Set visible_drop_or_open_side true only when the drop
  or opening is itself visible.
- visible_guardrail / barrier / warning_sign / traffic_zone / machinery_operating_region
  are optional context.
- protection_state: "guarded" only if a guardrail or barrier is visibly present along the
  edge, "unguarded_or_inadequate" only if you can see the edge is open, otherwise
  "unknown". Never infer that protection is absent merely because you did not notice it.
- protection_visibility: "sufficient" when the whole edge is clearly visible, otherwise
  "insufficient" or "unknown".
- Do not identify people, mention laws, or make compliance claims.
- If a keyframe shows nothing relevant, return an empty proposals list for it.
"""

_POINT = {
    "type": "object",
    "properties": {"y": {"type": "integer"}, "x": {"type": "integer"}},
    "required": ["y", "x"],
}
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyframe_index": {"type": "integer"},
                    "proposals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "proposal_type": {
                                    "type": "string",
                                    "enum": sorted(POLYGON_TYPES | POLYLINE_TYPES),
                                },
                                "geometry_type": {
                                    "type": "string",
                                    "enum": ["polygon", "polyline", "box"],
                                },
                                "points": {"type": "array", "items": _POINT},
                                "visible_drop_or_open_side": {"type": "boolean"},
                                "protection_visibility": {
                                    "type": "string",
                                    "enum": ["sufficient", "insufficient", "unknown"],
                                },
                                "protection_state": {
                                    "type": "string",
                                    "enum": ["guarded", "unguarded_or_inadequate", "unknown"],
                                },
                                "rationale": {"type": "string"},
                            },
                            "required": ["proposal_type", "geometry_type", "points", "rationale"],
                        },
                    },
                },
                "required": ["keyframe_index", "proposals"],
            },
        }
    },
    "required": ["frames"],
}


class SceneRequestError(RuntimeError):
    """The scene request failed; callers fall back to an unavailable scene."""


def request_scene_proposals(
    api_key: str,
    model: str,
    keyframe_jpegs: Sequence[bytes],
    *,
    timeout_s: int = 120,
    max_retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Raw JSON text for all keyframes, sent as a single request."""
    if not api_key:
        raise SceneRequestError("GEMINI_API_KEY is not set")
    parts: list[dict] = [{"text": _PROMPT}]
    for ordinal, jpeg in enumerate(keyframe_jpegs):
        parts.append({"text": f"Keyframe {ordinal}:"})
        parts.append(
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}
        )
    body = json.dumps(
        {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }
    ).encode()
    request = Request(
        f"{_GEMINI_BASE}/{model}:generateContent?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=timeout_s) as response:
                data = json.loads(response.read())
            break
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            delay = _retry_delay_s(detail, attempt)
            if exc.code in _RETRYABLE_STATUS and delay is not None and attempt < max_retries:
                sleep(delay)
                attempt += 1
                continue
            raise SceneRequestError(f"Gemini {model} failed {exc.code}: {detail[:300]}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise SceneRequestError(f"Gemini {model} request failed: {exc}") from exc
    candidates = data.get("candidates") or []
    if not candidates:
        raise SceneRequestError(f"Gemini returned no candidates: {json.dumps(data)[:200]}")
    try:
        return candidates[0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SceneRequestError(f"Gemini reply had no text part: {json.dumps(data)[:200]}") from exc
