from __future__ import annotations

import pytest

from llm import embedding_cache


def test_empty_when_supabase_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    def _must_not_fetch() -> dict[str, list[float]]:
        raise AssertionError("should not hit Supabase without credentials")

    monkeypatch.setattr(embedding_cache, "fetch_embeddings_from_supabase", _must_not_fetch)
    assert embedding_cache.get_embeddings() == {}


def test_success_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _fetch() -> dict[str, list[float]]:
        calls.append(1)
        return {"chunk": [0.1, 0.2]}

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setattr(embedding_cache, "fetch_embeddings_from_supabase", _fetch)

    assert embedding_cache.get_embeddings() == {"chunk": [0.1, 0.2]}
    assert embedding_cache.get_embeddings() == {"chunk": [0.1, 0.2]}
    assert len(calls) == 1


def test_failure_is_retried_after_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    outcomes: list[Exception | dict[str, list[float]]] = [
        OSError("dns failure"),
        {"chunk": [1.0]},
    ]

    def _fetch() -> dict[str, list[float]]:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setattr(embedding_cache, "fetch_embeddings_from_supabase", _fetch)
    monkeypatch.setattr(embedding_cache.time, "monotonic", lambda: clock[0])

    assert embedding_cache.get_embeddings() == {}
    assert embedding_cache.get_embeddings() == {}
    assert len(outcomes) == 1

    clock[0] += embedding_cache.FAILURE_RETRY_S + 1
    assert embedding_cache.get_embeddings() == {"chunk": [1.0]}
