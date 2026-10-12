from __future__ import annotations

import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from llm.regulations import EMBEDDING_DIM, EMBEDDING_MODEL

_GEMINI_EMBED_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_RATE_LIMIT_SLEEP_S = 0.15  # ~6 RPS — well below Gemini free-tier limit


def _embed_text(
    text: str,
    *,
    api_key: str,
    model: str = EMBEDDING_MODEL,
    task_type: str = "RETRIEVAL_DOCUMENT",
    timeout_s: int = 30,
) -> list[float]:
    """Embed a single text string using the Gemini Embeddings API."""
    url = f"{_GEMINI_EMBED_BASE}/{model}:embedContent?key={api_key}"
    body = json.dumps(
        {
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": EMBEDDING_DIM,
        }
    ).encode()
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_s) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini embed failed {exc.code}: {detail}") from exc
    values = data["embedding"]["values"]
    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"Expected {EMBEDDING_DIM}-dim embedding, got {len(values)}")
    return values


def embed_batch(
    texts: list[str],
    *,
    api_key: str,
    model: str = EMBEDDING_MODEL,
    task_type: str = "RETRIEVAL_DOCUMENT",
    sleep_between: float = _RATE_LIMIT_SLEEP_S,
) -> list[list[float]]:
    """Embed a list of texts, sleeping between calls to respect rate limits."""
    results: list[list[float]] = []
    for i, text in enumerate(texts):
        if i > 0:
            time.sleep(sleep_between)
        results.append(_embed_text(text, api_key=api_key, model=model, task_type=task_type))
    return results


def embed_query(
    query: str,
    *,
    api_key: str,
    model: str = EMBEDDING_MODEL,
) -> list[float]:
    """Embed a retrieval query (uses RETRIEVAL_QUERY task type for Gemini 004)."""
    return _embed_text(query, api_key=api_key, model=model, task_type="RETRIEVAL_QUERY")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom < 1e-9:
        return 0.0
    return float(np.dot(va, vb) / denom)


def rrf_fuse(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked document ID lists.

    Returns ``[(doc_id, rrf_score)]`` sorted by descending score.
    k=60 is the standard constant from Cormack et al. 2009.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])
