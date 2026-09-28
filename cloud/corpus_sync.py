"""Embed the BOCW clause corpus and upsert it into the Supabase clause_chunks table.

Usage:
    uv run python -m cloud.corpus_sync          # requires GEMINI_API_KEY + Supabase env vars
    uv run python -m cloud.corpus_sync --dry-run  # print what would be upserted, no network calls
"""

from __future__ import annotations

import argparse
import os
import sys

from cloud.config import CloudConfig
from cloud.supabase import SupabaseClient
from llm.embeddings import embed_batch
from llm.regulations import BOOTSTRAP_CLAUSES, CATALOGUE_SHA256

_SLEEP_BETWEEN_BATCH_S = 1.0


def _build_row(chunk, embedding: list[float] | None) -> dict:
    return {
        "id": chunk.chunk_id,
        "catalogue_sha256": CATALOGUE_SHA256,
        "rule_ids": list(r.value for r in chunk.rule_ids),
        "clause_ref": chunk.clause_ref,
        "title": chunk.title,
        "text": chunk.text,
        "source": chunk.source,
        "source_url": chunk.source_url,
        "retrieved_on": chunk.retrieved_on,
        "sha256": chunk.sha256,
        "embedding": embedding,
    }


def sync_corpus(*, dry_run: bool = False) -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key and not dry_run:
        print("GEMINI_API_KEY not set — will upsert clauses without embeddings.", file=sys.stderr)

    config: CloudConfig | None = None
    client: SupabaseClient | None = None
    if not dry_run:
        config = CloudConfig.from_env()
        client = SupabaseClient(config)

    texts = [f"{c.clause_ref} {c.title} {c.text}" for c in BOOTSTRAP_CLAUSES]
    embeddings: list[list[float] | None] = [None] * len(texts)

    if api_key and not dry_run:
        print(f"Embedding {len(texts)} clauses via Gemini text-embedding-004 …")
        try:
            vecs = embed_batch(texts, api_key=api_key)
            embeddings = [list(v) for v in vecs]
            print(f"  Done. First vector dim: {len(embeddings[0])}")
        except Exception as exc:
            print(f"  Embedding failed ({exc}) — upserting without embeddings.", file=sys.stderr)

    rows = [_build_row(chunk, embeddings[i]) for i, chunk in enumerate(BOOTSTRAP_CLAUSES)]

    if dry_run:
        print(f"DRY RUN — {len(rows)} rows would be upserted to clause_chunks:")
        for row in rows:
            emb_status = f"{len(row['embedding'])}-dim" if row["embedding"] else "no embedding"
            print(f"  {row['id']} | {row['clause_ref'][:60]} | {emb_status}")
        return

    assert client is not None
    print(f"Upserting {len(rows)} rows to clause_chunks …")
    client.upsert("clause_chunks", rows)
    print("  Done.")

    # Verify
    count = client.count("clause_chunks")
    print(f"  Verified: {count} rows in clause_chunks.")


def fetch_embeddings_from_supabase() -> dict[str, list[float]]:
    """Fetch all chunk embeddings from Supabase for use in hybrid retrieval.

    Returns a ``{chunk_id: embedding}`` dict.  Missing or null embeddings are skipped.
    """
    config = CloudConfig.from_env()
    client = SupabaseClient(config)
    rows = client.select("clause_chunks", select="id,embedding")
    result: dict[str, list[float]] = {}
    for row in rows:
        vec = row.get("embedding")
        if vec and isinstance(vec, list):
            result[row["id"]] = vec
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync BOCW corpus to Supabase with embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Print rows without upserting")
    args = parser.parse_args()
    sync_corpus(dry_run=args.dry_run)
