from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from llm.adjudicator import GeminiPPEAdjudicator, _crop_hash, _jpeg_bytes, _parse_result
from shared.enums import HelmetState, VestState


def _fake_crop() -> np.ndarray:
    return np.zeros((100, 60, 3), dtype=np.uint8)


GEMINI_RESPONSE = json.dumps(
    {
        "helmet_state": "no_helmet",
        "helmet_confidence": 0.91,
        "vest_state": "vest",
        "vest_confidence": 0.85,
        "reasoning": "bare head, green vest visible",
    }
)

GEMINI_API_PAYLOAD = json.dumps(
    {"candidates": [{"content": {"parts": [{"text": GEMINI_RESPONSE}]}}]}
)


def test_parse_result_correct_enums() -> None:
    result = _parse_result(GEMINI_RESPONSE)
    assert result.helmet.state == HelmetState.NO_HELMET
    assert result.vest.state == VestState.VEST
    assert abs(result.helmet.confidence - 0.91) < 0.01


def test_parse_result_unknown_fallback() -> None:
    raw = json.dumps(
        {
            "helmet_state": "unknown",
            "helmet_confidence": 0.0,
            "vest_state": "unknown",
            "vest_confidence": 0.0,
        }
    )
    result = _parse_result(raw)
    assert result.helmet.state == HelmetState.UNKNOWN
    assert result.helmet.visible is False


def test_jpeg_bytes_produces_valid_jpeg() -> None:
    crop = _fake_crop()
    jpeg = _jpeg_bytes(crop)
    assert jpeg[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_crop_hash_is_deterministic() -> None:
    crop = _fake_crop()
    j = _jpeg_bytes(crop)
    assert _crop_hash(j) == _crop_hash(j)
    assert len(_crop_hash(j)) == 16


def test_adjudicator_uses_cache(tmp_path: Path) -> None:
    crop = _fake_crop()
    jpeg = _jpeg_bytes(crop)
    key = _crop_hash(jpeg)
    cache_path = tmp_path / f"{key}.json"
    cache_path.write_text(GEMINI_RESPONSE, encoding="utf-8")

    adj = GeminiPPEAdjudicator("fake-key", cache_dir=tmp_path)
    result = adj.assess(crop)
    assert result.cached is True
    assert result.helmet.state == HelmetState.NO_HELMET


def test_adjudicator_calls_gemini_on_cache_miss(tmp_path: Path) -> None:
    crop = _fake_crop()
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = GEMINI_API_PAYLOAD.encode()

    with patch("llm.adjudicator.urlopen", return_value=mock_response):
        adj = GeminiPPEAdjudicator("test-key", cache_dir=tmp_path)
        result = adj.assess(crop)

    assert result.cached is False
    assert result.helmet.state == HelmetState.NO_HELMET
    assert result.vest.state == VestState.VEST


def test_adjudicator_requires_api_key() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiPPEAdjudicator("")
