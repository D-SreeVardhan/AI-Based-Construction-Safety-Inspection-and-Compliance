"""Lazy singleton cache for corpus embeddings.

On first access, attempts to load 768-dim vectors from Supabase ``clause_chunks``.
If Supabase is not configured or the fetch fails, returns an empty dict so
retrieval falls back to lexical-only mode — the system degrades gracefully.

Usage::

    from llm.embedding_cache import get_embeddings
    embeddings = get_embeddings()   # dict[chunk_id, list[float]] or {}
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Final

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict[str, list[float]] | None = None
_SENTINEL: Final = object()


def _load_from_supabase() -> dict[str, list[float]]:
    """Fetch all embeddings from Supabase clause_chunks."""
    # Inline import to avoid hard dependency on cloud at import time
    from cloud.config import load_cloud_config  # noqa: PLC0415
    from cloud.supabase import SupabaseClient  # noqa: PLC0415

    config = load_cloud_config()
    client = SupabaseClient(config)
    rows = client.select("clause_chunks", select="id,embedding")
    result: dict[str, list[float]] = {}
    for row in rows:
        vec = row.get("embedding")
        if isinstance(vec, list):
            result[row["id"]] = [float(v) for v in vec]
        elif isinstance(vec, str):
            try:
                parsed = json.loads(vec)
                if isinstance(parsed, list):
                    result[row["id"]] = [float(v) for v in parsed]
            except (json.JSONDecodeError, ValueError):
                pass
    return result


def get_embeddings() -> dict[str, list[float]]:
    """Return the cached corpus embedding dict, loading once on first call.

    Returns an empty dict if Supabase is unreachable or not configured.
    Dense retrieval is silently disabled in that case.
    """
    global _cache  # noqa: PLW0603
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        supabase_url = os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supabase_url:
            _log.debug("SUPABASE_URL not set — dense retrieval disabled")
            _cache = {}
            return _cache
        try:
            _cache = _load_from_supabase()
            _log.info("Loaded %d clause embeddings from Supabase", len(_cache))
        except Exception as exc:  # noqa: BLE001
            _log.warning("Could not load embeddings from Supabase (%s) — using lexical-only", exc)
            _cache = {}
    return _cache


def invalidate() -> None:
    """Clear the cache so the next call to ``get_embeddings()`` re-fetches."""
    global _cache  # noqa: PLW0603
    with _lock:
        _cache = None
