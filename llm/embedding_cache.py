"""Lazy singleton cache for corpus embeddings.

On first access, loads 768-dim vectors from Supabase ``clause_chunks``.
If Supabase is not configured or the fetch fails, returns an empty dict so
retrieval falls back to lexical-only mode.

Usage::

    from llm.embedding_cache import get_embeddings
    embeddings = get_embeddings()   # dict[chunk_id, list[float]] or {}
"""

from __future__ import annotations

import logging
import os
import threading
import time

from cloud.corpus_sync import fetch_embeddings_from_supabase

# A failed fetch is retried after this long instead of pinning a long-running
# server to lexical-only retrieval until restart.
FAILURE_RETRY_S = 60.0

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict[str, list[float]] | None = None
_failed_at: float | None = None


def get_embeddings() -> dict[str, list[float]]:
    """Return the cached corpus embedding dict, loading on first call.

    Returns an empty dict if Supabase is unreachable or not configured.
    Dense retrieval is disabled in that case.
    """
    global _cache, _failed_at  # noqa: PLW0603
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
            _log.info("Supabase not configured; dense retrieval disabled")
            _cache = {}
            return _cache
        if _failed_at is not None and time.monotonic() - _failed_at < FAILURE_RETRY_S:
            return {}
        try:
            _cache = fetch_embeddings_from_supabase()
            _failed_at = None
            _log.info("Loaded %d clause embeddings from Supabase", len(_cache))
        except Exception as exc:  # noqa: BLE001
            _failed_at = time.monotonic()
            _log.warning("Could not load embeddings from Supabase (%s); using lexical-only", exc)
            return {}
    return _cache


def invalidate() -> None:
    """Clear the cache so the next call to ``get_embeddings()`` re-fetches."""
    global _cache, _failed_at  # noqa: PLW0603
    with _lock:
        _cache = None
        _failed_at = None
