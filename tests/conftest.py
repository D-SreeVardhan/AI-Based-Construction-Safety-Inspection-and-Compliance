from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import cloud.config
from llm import embedding_cache

_CLOUD_ENV = (
    "GEMINI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_BUCKET",
    "HF_TOKEN",
    "HF_SPACE",
)


@pytest.fixture(autouse=True)
def _hermetic_cloud_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Keep the developer's .env and shell keys from switching tests onto live APIs."""
    for name in _CLOUD_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cloud.config, "PROJECT_ROOT", tmp_path)
    embedding_cache.invalidate()
    yield
    embedding_cache.invalidate()
