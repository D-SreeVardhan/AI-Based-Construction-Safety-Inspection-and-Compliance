"""HTML for published run media (evidence crops, PPE-review crops) in the Space.

Kept free of gradio so it can be unit-tested without the Space runtime.
"""

from __future__ import annotations

import html
import json
from typing import Any

from cloud.supabase import SupabaseClient

_CARD = (
    "display:flex;gap:14px;align-items:flex-start;background:#232220;"
    "border:1px solid #3a3733;border-left:4px solid #e8590c;border-radius:4px;"
    "padding:12px;margin:0 0 10px"
)
_IMG = "width:200px;flex:none;border:1px solid #3a3733;border-radius:3px"
_GRID = "display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px"
_FIG = "margin:0;background:#232220;border:1px solid #3a3733;border-radius:4px;padding:6px"


def object_path(client: SupabaseClient, stored_path: str | None) -> str | None:
    if not stored_path:
        return None
    prefix = f"{client.config.supabase_bucket}/"
    if stored_path.startswith(prefix):
        return stored_path[len(prefix) :]
    return stored_path


def load_media(client: SupabaseClient, run_id: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Signed evidence URLs by incident id, and PPE-review entries with a ``url`` key.

    Runs published before media upload have no ``media.json``; both results are empty.
    """
    raw = client.download(f"runs/{run_id}/media.json")
    if raw is None:
        return {}, []
    media = json.loads(raw.decode("utf-8"))
    evidence = {
        incident_id: path
        for incident_id, stored in media.get("evidence", {}).items()
        if (path := object_path(client, stored))
    }
    review = [
        (path, entry)
        for entry in media.get("ppe_review", [])
        if (path := object_path(client, entry.get("object")))
    ]
    signed = client.signed_urls(sorted({*evidence.values(), *(path for path, _ in review)}))
    evidence_urls = {i: signed[p] for i, p in evidence.items() if p in signed}
    review_out = [{**entry, "url": signed[path]} for path, entry in review if path in signed]
    return evidence_urls, review_out


def incident_cards_html(incidents: list[dict[str, Any]], evidence_urls: dict[str, str]) -> str:
    if not incidents:
        return "<p>No incidents in this run.</p>"
    cards = []
    for row in incidents:
        payload = row["payload"]
        url = evidence_urls.get(payload["incident_id"])
        image = (
            f'<img src="{html.escape(url, quote=True)}" style="{_IMG}" '
            f'alt="evidence crop" loading="lazy">'
            if url
            else '<div style="width:200px;flex:none;color:#8a847c">No evidence crop</div>'
        )
        end = payload.get("resolved_at_s") or payload["first_seen_s"]
        cards.append(
            f'<div style="{_CARD}">{image}<div>'
            f'<div style="color:#ff8c42;font-weight:700">'
            f"{html.escape(row['rule_id'])} &mdash; {html.escape(row['status'])}</div>"
            f'<div style="color:#8a847c;font-size:.85em">'
            f"t {payload['first_seen_s']:.1f}s&ndash;{end:.1f}s &middot; "
            f"track {html.escape(str(payload.get('canonical_track_id') or '-'))}</div>"
            f'<p style="margin:.4em 0">{html.escape(payload["observation_text"])}</p>'
            f'<p style="margin:0;color:#c9c2b8"><b style="color:#f2a900">Action:</b> '
            f"{html.escape(payload.get('action_text', ''))}</p>"
            "</div></div>"
        )
    return "".join(cards)


def _verdict(labels: dict[str, str] | None) -> str:
    if not labels:
        return "-"
    return f"{labels.get('helmet', '?')} / {labels.get('vest', '?')}"


def review_gallery_html(review: list[dict[str, Any]]) -> str:
    if not review:
        return "<p>No PPE-review crops published for this run.</p>"
    figures = []
    for entry in review:
        caption = html.escape(entry.get("track_id") or entry["crop"].rsplit("/", 1)[-1])
        details = ""
        if "gemini" in entry:
            details = (
                f"<br>classifier: {html.escape(_verdict(entry.get('classifier')))}"
                f"<br>Gemini: {html.escape(_verdict(entry.get('gemini')))}"
                f"<br><span style='color:#f2a900'>{html.escape(entry.get('action', ''))}</span>"
            )
        figures.append(
            f'<figure style="{_FIG}">'
            f'<img src="{html.escape(entry["url"], quote=True)}" loading="lazy" '
            'style="width:100%;height:180px;object-fit:contain;background:#141414" alt="crop">'
            f'<figcaption style="font-size:.78em;color:#c9c2b8;margin-top:4px">'
            f"{caption}{details}</figcaption></figure>"
        )
    return f'<div style="{_GRID}">{"".join(figures)}</div>'
