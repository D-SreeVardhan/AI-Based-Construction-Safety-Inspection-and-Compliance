"""Self-contained HTML report generator for safety inspection runs.

Design principles:
- Zero external dependencies — all CSS/JS inlined.
- Construction-site aesthetic: dark charcoal base, amber/safety-yellow
  accents, safety-orange alerts. No generic SaaS blue.
- Provenance block: model id, corpus version, embedding model, run date
  so every printed or shared copy is traceable.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

from llm.regulations import CATALOGUE_SHA256, EMBEDDING_MODEL, SOURCE_URL
from llm.retrieval import MODEL_ID, RETRIEVAL_MODE
from shared.enums import RuleStatus
from shared.schemas.incidents import IncidentRecord
from shared.schemas.llm import GroundedBriefing
from shared.schemas.run import RunManifest

# ── colour tokens ──────────────────────────────────────────────────────────
_C = {
    "bg": "#141414",
    "surface": "#1e1e1e",
    "card": "#252525",
    "border": "#333333",
    "amber": "#f59e0b",
    "amber_dim": "#78450a",
    "orange": "#f97316",
    "red": "#ef4444",
    "green": "#22c55e",
    "muted": "#6b7280",
    "text": "#e2e2e2",
    "text_dim": "#9ca3af",
}

_STATUS_COLOUR: dict[RuleStatus, str] = {
    RuleStatus.EVALUATED_ALERT: _C["red"],
    RuleStatus.EVALUATED_CLEAR: _C["green"],
    RuleStatus.INCONCLUSIVE: _C["muted"],
    RuleStatus.NOT_APPLICABLE: _C["muted"],
    RuleStatus.UNSUPPORTED: _C["border"],
}


def _e(s: object) -> str:
    """HTML-escape a value."""
    return html.escape(str(s))


def _css() -> str:
    return f"""
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 14px;
  background: {_C["bg"]};
  color: {_C["text"]};
  line-height: 1.6;
}}
.wrap {{ max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}

/* ── header bar ──────────────────────────────────────────────────────── */
header {{
  border-bottom: 3px solid {_C["amber"]};
  padding-bottom: 1rem;
  margin-bottom: 2rem;
}}
header .brand {{ font-size: 11px; letter-spacing: .15em; text-transform: uppercase;
  color: {_C["amber"]}; margin-bottom: .25rem; }}
header h1 {{ font-size: 1.6rem; font-weight: 700; }}
header .sub {{ color: {_C["text_dim"]}; font-size: .85rem; margin-top: .25rem; }}

/* ── disclaimer ──────────────────────────────────────────────────────── */
.disclaimer {{
  background: {_C["amber_dim"]};
  border-left: 4px solid {_C["amber"]};
  padding: .6rem 1rem;
  border-radius: 2px;
  font-size: .82rem;
  color: {_C["amber"]};
  margin-bottom: 1.5rem;
}}

/* ── section titles ──────────────────────────────────────────────────── */
h2 {{
  font-size: .75rem;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: {_C["muted"]};
  border-bottom: 1px solid {_C["border"]};
  padding-bottom: .35rem;
  margin: 2rem 0 1rem;
}}

/* ── coverage grid ──────────────────────────────────────────────────── */
.coverage-grid {{ display: flex; flex-wrap: wrap; gap: .75rem; }}
.cov-pill {{
  background: {_C["card"]};
  border: 1px solid {_C["border"]};
  border-radius: 4px;
  padding: .4rem .75rem;
  font-size: .8rem;
  display: flex; align-items: center; gap: .4rem;
}}
.cov-pill .dot {{ width: 8px; height: 8px; border-radius: 50%; }}

/* ── incident cards ──────────────────────────────────────────────────── */
.incidents {{ display: flex; flex-direction: column; gap: .75rem; }}
.incident-card {{
  background: {_C["card"]};
  border: 1px solid {_C["border"]};
  border-radius: 6px;
  padding: 1rem 1.25rem;
}}
.incident-card .ic-header {{
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: .75rem; margin-bottom: .5rem;
}}
.incident-card .ic-rule {{
  font-weight: 700; font-size: .9rem;
  color: {_C["orange"]};
}}
.incident-card .ic-meta {{
  font-size: .78rem; color: {_C["text_dim"]}; white-space: nowrap;
}}
.incident-card .ic-obs {{
  font-size: .87rem; margin-bottom: .35rem;
}}
.incident-card .ic-action {{
  font-size: .82rem; color: {_C["text_dim"]};
}}
.incident-card .ic-action span {{ color: {_C["amber"]}; font-weight: 600; }}

/* ── briefing cards ──────────────────────────────────────────────────── */
.briefings {{ display: flex; flex-direction: column; gap: .75rem; }}
.briefing-card {{
  background: {_C["card"]};
  border: 1px solid {_C["border"]};
  border-radius: 6px;
  padding: 1rem 1.25rem;
}}
.briefing-card .bc-rule {{
  font-weight: 600; font-size: .88rem; color: {_C["amber"]}; margin-bottom: .5rem;
}}
.briefing-card .bc-text {{
  font-size: .87rem; margin-bottom: .5rem;
}}
.briefing-card .bc-clauses {{
  display: flex; flex-wrap: wrap; gap: .4rem;
}}
.clause-tag {{
  background: {_C["surface"]};
  border: 1px solid {_C["border"]};
  border-radius: 3px;
  padding: .15rem .45rem;
  font-size: .75rem;
  font-family: 'Courier New', monospace;
  color: {_C["text_dim"]};
}}

/* ── provenance ──────────────────────────────────────────────────────── */
.provenance {{
  background: {_C["surface"]};
  border: 1px solid {_C["border"]};
  border-radius: 6px;
  padding: 1rem 1.25rem;
  font-size: .78rem;
  color: {_C["text_dim"]};
}}
.provenance table {{ border-collapse: collapse; width: 100%; }}
.provenance td {{ padding: .25rem .5rem; }}
.provenance td:first-child {{ color: {_C["muted"]}; white-space: nowrap; }}
.provenance a {{ color: {_C["amber"]}; }}

/* ── empty state ─────────────────────────────────────────────────────── */
.empty {{ color: {_C["muted"]}; font-style: italic; font-size: .85rem; }}
"""


def _coverage_block(manifest: RunManifest) -> str:
    pills = []
    for entry in manifest.rule_coverage:
        colour = _STATUS_COLOUR.get(entry.status, _C["muted"])
        pills.append(
            f'<div class="cov-pill">'
            f'<span class="dot" style="background:{colour}"></span>'
            f"<strong>{_e(entry.rule_id.value)}</strong>"
            f'&nbsp;<span style="color:{_C["text_dim"]}">'
            f"{_e(entry.status.value)} ({_e(entry.reason_code)})</span>"
            f"</div>"
        )
    return '<div class="coverage-grid">' + "".join(pills) + "</div>"


def _incidents_block(incidents: tuple[IncidentRecord, ...]) -> str:
    if not incidents:
        return '<p class="empty">No incidents detected in this run.</p>'
    cards = []
    for inc in incidents:
        conf_str = f"{inc.confidence:.0%}" if inc.confidence is not None else "—"
        t_end = inc.resolved_at_s or inc.first_seen_s
        track = inc.canonical_track_id or "—"
        cards.append(
            f'<div class="incident-card">'
            f'<div class="ic-header">'
            f'<span class="ic-rule">{_e(inc.rule_id.value)} — {_e(inc.status.value)}</span>'
            f'<span class="ic-meta">'
            f"t {inc.first_seen_s:.1f}s–{t_end:.1f}s &nbsp;|&nbsp; "
            f"conf {conf_str} &nbsp;|&nbsp; track {_e(track)}"
            f"</span>"
            f"</div>"
            f'<div class="ic-obs">{_e(inc.observation_text)}</div>'
            f'<div class="ic-action"><span>Action:</span> {_e(inc.action_text)}</div>'
            f"</div>"
        )
    return '<div class="incidents">' + "".join(cards) + "</div>"


def _briefings_block(briefings: tuple[GroundedBriefing, ...]) -> str:
    if not briefings:
        return '<p class="empty">No briefings generated.</p>'
    cards = []
    for brief in briefings:
        body = " ".join(_e(s.text) for s in brief.sentences)
        clauses = "".join(
            f'<span class="clause-tag">{_e(hit.chunk.clause_ref)}</span>'
            for hit in brief.retrieved_chunks
        )
        refused_note = ""
        if brief.refused:
            refused_note = (
                f' <span style="color:{_C["muted"]};font-size:.75rem">'
                f"(low-confidence / {_e(brief.refusal_reason or '')})</span>"
            )
        cards.append(
            f'<div class="briefing-card">'
            f'<div class="bc-rule">{_e(brief.rule_id.value)}{refused_note}</div>'
            f'<div class="bc-text">{body}</div>'
            f'<div class="bc-clauses">{clauses}</div>'
            f"</div>"
        )
    return '<div class="briefings">' + "".join(cards) + "</div>"


def _provenance_block(manifest: RunManifest) -> str:
    generated_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    rows = [
        ("Report generated", generated_at),
        ("Run ID", manifest.run_id),
        ("Status", f"{manifest.status.value} ({manifest.mode})"),
        ("Input clip", manifest.input_video.path),
        ("Corpus", "BOCW Central Rules 1998 expanded catalogue"),
        ("Corpus source", f'<a href="{_e(SOURCE_URL)}" target="_blank">{_e(SOURCE_URL)}</a>'),
        ("Corpus SHA-256", CATALOGUE_SHA256[:16] + "…"),
        ("Embedding model", EMBEDDING_MODEL),
        ("Retrieval model", MODEL_ID),
        ("Retrieval mode", RETRIEVAL_MODE),
        ("Disclaimer", manifest.disclaimer),
    ]
    trs = "".join(f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in rows)
    return '<div class="provenance"><table><tbody>' + trs + "</tbody></table></div>"


def build_report_html(
    manifest: RunManifest,
    incidents: tuple[IncidentRecord, ...],
    briefings: tuple[GroundedBriefing, ...],
) -> str:
    """Return a self-contained HTML string for the run report.

    Suitable for writing to ``report.html`` in the run directory or uploading
    to Supabase storage.
    """
    n_alerts = len(incidents)
    created_at_raw = manifest.created_at
    if created_at_raw and isinstance(created_at_raw, str):
        run_date = created_at_raw[:16].replace("T", " ") + " UTC"
    elif created_at_raw and hasattr(created_at_raw, "strftime"):
        run_date = created_at_raw.strftime("%Y-%m-%d %H:%M UTC")  # type: ignore[union-attr]
    else:
        run_date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Safety Report — {_e(manifest.run_id)}</title>
  <style>{_css()}</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="brand">Construction Safety Twin &nbsp;/&nbsp; CCTV Inspection Report</div>
  <h1>{n_alerts} Alert{"s" if n_alerts != 1 else ""} &mdash; Run
    <code>{_e(manifest.run_id)}</code></h1>
  <div class="sub">{run_date} &nbsp;&bull;&nbsp; Status: {_e(manifest.status.value)}
    &nbsp;&bull;&nbsp; Mode: {_e(manifest.mode)}</div>
</header>

<div class="disclaimer">
  &#9888;&nbsp; <strong>Not a certified safety system.</strong>
  These findings are heuristic outputs from automated CCTV analysis and
  do not constitute legal advice, a compliance determination, or a professional safety audit.
  A qualified safety officer must verify all findings before any enforcement or remedial action.
</div>

<h2>Rule Coverage</h2>
{_coverage_block(manifest)}

<h2>Incidents ({len(incidents)})</h2>
{_incidents_block(incidents)}

<h2>Grounded Briefings</h2>
{_briefings_block(briefings)}

<h2>Provenance</h2>
{_provenance_block(manifest)}

</div>
</body>
</html>
"""
