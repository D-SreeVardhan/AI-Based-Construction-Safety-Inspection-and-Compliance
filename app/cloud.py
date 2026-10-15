"""Hosted demo (Section 11): published runs, their reports, the risk register and the chatbot.

    GET  /                          the run gallery
    GET  /runs/{run_id}/            that run's report, with the live chat switched on
    GET  /runs/{run_id}/{path}      bundle files (video with Range requests, evidence, assets)
    GET  /api/runs                  published runs: clip, duration, incidents, top risk
    GET  /api/runs/{run_id}/risk    the risk register as JSON
    POST /api/runs/{run_id}/chat    {question, history} -> a grounded, checked answer
    POST /api/runs/{run_id}/reviews reviewer verdicts (stored when a database is configured)
    GET  /api/stats                 chatbot monitoring: answers, model share, latency, failures
    GET  /healthz                   liveness and configuration (never secrets)
    GET  /docs                      OpenAPI

Processing stays on a GPU workstation; finished bundles are published (tools/publish_run.py)
to a Hugging Face dataset that this service downloads at startup, so the public URL works
whether or not the workstation is on.

Configuration, all from the environment (cloud secrets; never committed):

    SAFETY_RUNS_DIR          where bundles live (default output/)
    SAFETY_RUNS_REPO         Hugging Face dataset with published bundles (optional)
    HF_TOKEN                 only if that dataset is private
    SAFETY_LLM_*             the chatbot's model (llm/assistant/providers.py)
    SUPABASE_URL, SUPABASE_SERVICE_KEY   optional: chat logs and reviews in Postgres
    SAFETY_CHAT_PER_MINUTE   per-client limit on chat requests (default 8)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.request
from collections import Counter, defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from llm.assistant.chat import RiskAssistant
from llm.assistant.providers import ProviderError, from_env
from pipeline.output.run_bundle import RunBundle
from shared.schemas.bundle import REPORT_FILE, RUN_MANIFEST_FILE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Client addresses are logged only as salted hashes (stable while SAFETY_LOG_SALT is set).
LOG_SALT = os.environ.get("SAFETY_LOG_SALT") or secrets.token_hex(16)
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
log = logging.getLogger("safety.cloud")


# ---------------------------------------------------------------------- runs


class RunStore:
    """Published bundles on disk, each loaded once on first use."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._assistants: dict[str, RiskAssistant] = {}
        self._lock = threading.Lock()

    def ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / RUN_MANIFEST_FILE).is_file())

    def path(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id) or run_id not in self.ids():
            raise HTTPException(404, "no such run")
        return self.root / run_id

    def assistant(self, run_id: str) -> RiskAssistant:
        with self._lock:
            if run_id not in self._assistants:
                self._assistants[run_id] = RiskAssistant(
                    RunBundle.load(self.path(run_id)), provider
                )
            return self._assistants[run_id]


def fetch_published(root: Path) -> None:
    """Download published bundles from the Hugging Face dataset, if one is configured."""
    repo = os.environ.get("SAFETY_RUNS_REPO")
    if not repo:
        return
    from huggingface_hub import snapshot_download

    started = time.perf_counter()
    snapshot_download(
        repo_id=repo,
        repo_type="dataset",
        local_dir=root,
        token=os.environ.get("HF_TOKEN") or None,
    )
    log.info(
        json.dumps(
            {
                "event": "runs_fetched",
                "repo": repo,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
    )


# ---------------------------------------------------------------------- monitoring


class Stats:
    """In-memory counters for /api/stats; the durable log is stdout (and Supabase if set)."""

    def __init__(self) -> None:
        self.answers: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.latency: deque[float] = deque(maxlen=500)
        self.tokens = 0
        self.started = time.time()

    def record(self, source: str, failures: list[str], latency_s: float, tokens: int) -> None:
        self.answers[source] += 1
        for failure in failures:
            self.failures[failure.split(":", 1)[0]] += 1
        if source == "model":
            self.latency.append(latency_s)
        self.tokens += tokens

    def summary(self) -> dict[str, Any]:
        total = sum(self.answers.values())
        ordered = sorted(self.latency)
        return {
            "answers": total,
            "model_share": round(self.answers["model"] / total, 3) if total else None,
            "by_source": dict(self.answers),
            "check_failures": dict(self.failures),
            "model_latency_s": {
                "median": ordered[len(ordered) // 2] if ordered else None,
                "p90": ordered[int(len(ordered) * 0.9)] if ordered else None,
            },
            "tokens": self.tokens,
            "uptime_s": round(time.time() - self.started),
        }


class Limiter:
    """A sliding one-minute window per client, so a public URL cannot drain the API quota."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.seen: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.time()
        with self._lock:
            window = self.seen[client]
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(now)
            return True


def supabase_insert(table: str, row: dict[str, Any]) -> None:
    """Fire-and-forget insert through Supabase's REST API; a failure is only logged."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return

    def send() -> None:
        request = urllib.request.Request(
            f"{url.rstrip('/')}/rest/v1/{table}",
            data=json.dumps(row).encode("utf-8"),
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except OSError as error:
            log.warning(
                json.dumps({"event": "supabase_failed", "table": table, "error": str(error)})
            )

    threading.Thread(target=send, daemon=True).start()


# ---------------------------------------------------------------------- app

logging.basicConfig(level=logging.INFO, format="%(message)s")
store = RunStore(Path(os.environ.get("SAFETY_RUNS_DIR") or PROJECT_ROOT / "output"))
try:
    provider = from_env()
except ProviderError as error:  # misconfigured: run, but answer from the register
    log.error(json.dumps({"event": "llm_config_error", "error": str(error)}))
    provider = None
stats = Stats()
limiter = Limiter(int(os.environ.get("SAFETY_CHAT_PER_MINUTE") or 8))


def _startup() -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    try:
        fetch_published(store.root)
    except Exception as error:  # noqa: BLE001 - serve what is on disk rather than fail
        log.error(json.dumps({"event": "runs_fetch_failed", "error": str(error)}))
    log.info(
        json.dumps(
            {"event": "started", "runs": store.ids(), "llm": provider.name if provider else None}
        )
    )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    _startup()
    yield


app = FastAPI(
    title="Construction Safety Twin",
    description="Published site-safety runs, their risk registers and a grounded chatbot.",
    version="0.3.0",
    lifespan=_lifespan,
)


@app.middleware("http")
async def _headers(request: Request, call_next):  # noqa: ANN001, ANN202
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


class ChatTurn(BaseModel):
    role: str
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class Review(BaseModel):
    incident_id: str = Field(max_length=120)
    verdict: str = Field(pattern="^(real|false_alarm|unsure)$")
    reason: str | None = Field(default=None, max_length=60)


@app.get("/healthz")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "runs": len(store.ids()),
        "llm": {"provider": provider.name, "model": provider.model} if provider else None,
        "database": bool(os.environ.get("SUPABASE_URL")),
    }


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    out = []
    for run_id in store.ids():
        bundle = store.assistant(run_id).bundle
        top = bundle.risk.rows[0] if bundle.risk.rows else None
        out.append(
            {
                "run_id": run_id,
                "clip": Path(bundle.manifest.input_video.path).name,
                "duration_s": round(bundle.duration_s, 1),
                "incidents": len(bundle.incidents),
                "completed_at": bundle.manifest.completed_at,
                "top_risk": {"rule": top.rule_id.value, "band": top.band, "rating": top.rating}
                if top
                else None,
                "report": f"/runs/{run_id}/",
                "thumbnail": _thumbnail(run_id),
            }
        )
    return out


@app.get("/api/runs/{run_id}/risk")
def risk(run_id: str) -> dict[str, Any]:
    assessment = store.assistant(run_id).bundle.risk
    return {
        "run_id": run_id,
        "workers_seen": assessment.workers_seen,
        "rows": [
            {
                "rule": r.rule_id.value,
                "title": r.title,
                "hazard": r.hazard,
                "likelihood": r.likelihood_score,
                "severity": r.severity_score,
                "rating": r.rating,
                "band": r.band,
                "why": r.why,
                "incidents": list(r.incident_ids),
                "workers": list(r.top_workers),
                "areas": list(r.areas),
                "controls": [{"level": level, "control": text} for level, text in r.controls],
            }
            for r in assessment.rows
        ],
        "not_assessed": [
            {"rule": rule.value, "reason": reason, "why": why}
            for rule, reason, why in assessment.not_assessed
        ],
        "not_observed": [
            {"rule": rule.value, "reason": reason} for rule, reason in assessment.not_observed
        ],
        "notes": list(assessment.notes),
    }


@app.post("/api/runs/{run_id}/chat")
def chat(run_id: str, body: ChatRequest, request: Request) -> JSONResponse:
    client = _client(request)
    if not limiter.allow(client):
        raise HTTPException(429, "too many questions; try again in a minute")
    assistant = store.assistant(run_id)
    started = time.perf_counter()
    reply = assistant.ask(body.question, [t.model_dump() for t in body.history])
    tokens = (reply.prompt_tokens or 0) + (reply.completion_tokens or 0)
    stats.record(reply.source, reply.failures, reply.latency_s, tokens)
    entry = {
        "event": "chat",
        "run_id": run_id,
        "source": reply.source,
        "model": reply.model,
        "latency_s": reply.latency_s,
        "total_s": round(time.perf_counter() - started, 2),
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "failures": reply.failures,
        "citations": [f.id for f in reply.citations],
        "question_sha": hashlib.sha256(body.question.encode()).hexdigest()[:12],
        "question_chars": len(body.question),
        "client": hashlib.sha256((LOG_SALT + client).encode()).hexdigest()[:12],
    }
    log.info(json.dumps(entry))
    supabase_insert("chat_logs", entry | {"question": body.question})
    return JSONResponse(
        {
            "text": reply.text,
            "source": reply.source,
            "model": reply.model,
            "latency_s": reply.latency_s,
            "failures": reply.failures,
            "citations": [{"id": f.id, "kind": f.kind, "text": f.text} for f in reply.citations],
        }
    )


@app.post("/api/runs/{run_id}/reviews")
def review(run_id: str, body: Review) -> dict[str, str]:
    store.path(run_id)
    if not os.environ.get("SUPABASE_URL"):
        raise HTTPException(503, "reviews are kept in the browser; no database is configured")
    supabase_insert("incident_reviews", {"run_id": run_id, **body.model_dump()})
    return {"status": "stored"}


@app.get("/api/stats")
def monitoring() -> dict[str, Any]:
    return stats.summary() | {"llm": provider.model if provider else None}


@app.get("/", response_class=HTMLResponse)
def gallery() -> str:
    cards = "".join(_card(r) for r in runs()) or ('<p class="empty">No runs published yet.</p>')
    return GALLERY.replace("{cards}", cards).replace(
        "{llm}", escape(provider.model if provider else "the risk register only")
    )


@app.get("/runs/{run_id}")
def run_root(run_id: str) -> RedirectResponse:
    store.path(run_id)
    return RedirectResponse(f"/runs/{run_id}/", status_code=308)


@app.get("/runs/{run_id}/", response_class=HTMLResponse)
def report(run_id: str) -> str:
    html = (store.path(run_id) / REPORT_FILE).read_text(encoding="utf-8")
    meta = f'<meta name="safety-api" content="/api/runs/{escape(run_id)}">'
    return html.replace("<head>", "<head>" + meta, 1)


@app.get("/runs/{run_id}/{path:path}")
def run_file(run_id: str, path: str) -> FileResponse:
    root = store.path(run_id).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.name == REPORT_FILE:
        raise HTTPException(404, "not found")
    return FileResponse(target, headers={"Cache-Control": "public, max-age=3600"})


def _client(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def _thumbnail(run_id: str) -> str | None:
    """The camera view with zones, else the exposure map, else the first evidence frame."""
    root = store.path(run_id)
    for name in ("site_view.jpg", "exposure_heatmap.jpg"):
        if (root / name).is_file():
            return f"/runs/{run_id}/{name}"
    frames = sorted(p for p in (root / "evidence").glob("*.jpg") if not p.stem.endswith("_crop"))
    if frames:
        return f"/runs/{run_id}/evidence/{frames[0].name}"
    video = root / "safety_twin_720p.mp4"
    return f"/runs/{run_id}/{video.name}#t=8" if video.is_file() else None


def _card(run: dict[str, Any]) -> str:
    top = run["top_risk"]
    risk = (
        f'<span class="pill {escape(top["band"].replace(" ", "-"))}">'
        f"{escape(top['rule'])} · {escape(top['band'])} {top['rating']}/25</span>"
        if top
        else '<span class="pill low">no hazard rated</span>'
    )
    src = run["thumbnail"]
    if not src:
        thumb = '<div class="ph">no preview</div>'
    elif ".mp4" in src:
        thumb = f'<video src="{escape(src)}" preload="metadata" muted playsinline></video>'
    else:
        thumb = f'<img src="{escape(src)}" alt="" loading="lazy">'

    return f"""<a class="run" href="{escape(run["report"])}">
  <div class="thumb">{thumb}</div>
  <div class="body">
  <div class="clip">{escape(run["clip"])}</div>
  <div class="id">{escape(run["run_id"])}</div>
  <div class="facts"><span>{run["duration_s"]:.0f} s of video</span><span>{run["incidents"]} incidents</span></div>
  {risk}
  </div>
</a>"""


GALLERY = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Construction Safety Twin</title>
<style>
:root { --bg:#f5f5f3; --surface:#fff; --line:#e3e1dc; --text:#0b0b0b; --text-2:#52514e; --text-3:#7b7a74;
  --accent:#2a78d6; --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b; }
@media (prefers-color-scheme: dark) { :root { --bg:#121211; --surface:#1a1a19; --line:#2f2f2c; --text:#fff;
  --text-2:#c3c2b7; --text-3:#8f8e87; --accent:#3987e5; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text);
  font:15px/1.55 Inter, "Segoe UI", system-ui, sans-serif; }
header { padding:48px 20px 24px; max-width:1080px; margin:0 auto; }
h1 { margin:0 0 8px; font-size:1.9rem; letter-spacing:-.01em; } header p { color:var(--text-2); max-width:760px; margin:0; }
main { max-width:1080px; margin:0 auto; padding:0 20px 48px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:14px; }
.run { display:block; background:var(--surface); border:1px solid var(--line); border-radius:14px; overflow:hidden;
  color:inherit; text-decoration:none; transition:border-color .15s, transform .15s; }
.run:hover { border-color:var(--accent); transform:translateY(-2px); }
.run .body { padding:14px 18px 18px; }
.thumb { aspect-ratio:16/9; background:#000; } .thumb img, .thumb video { width:100%; height:100%; object-fit:cover; display:block; }
.thumb .ph { height:100%; display:grid; place-items:center; color:var(--text-3); font-size:.8rem; background:var(--line); }
.steps { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:14px; margin:0 0 28px; }
.step { border-left:3px solid var(--accent); padding:4px 0 4px 14px; }
.step b { display:block; } .step span { color:var(--text-2); font-size:.88rem; }
h2 { font-size:1rem; margin:0 0 12px; color:var(--text-2); font-weight:600; }
@media (max-width:760px) { .steps { grid-template-columns:1fr; } }
.clip { font-weight:650; font-size:1.05rem; } .id { color:var(--text-3); font-size:.8rem; }
.facts { display:flex; gap:12px; color:var(--text-2); font-size:.86rem; margin:10px 0; }
.pill { display:inline-block; border-radius:999px; padding:2px 10px; font-size:.78rem; font-weight:600;
  border:1px solid var(--line); }
.pill::before { content:""; display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
.pill.very-high::before { background:var(--critical); } .pill.high::before { background:var(--serious); }
.pill.medium::before { background:var(--warning); } .pill.low::before { background:var(--good); }
.about { margin-top:28px; color:var(--text-2); font-size:.88rem; display:grid; gap:6px; }
.about a { color:var(--accent); } .empty { color:var(--text-3); }
</style></head><body>
<header><h1>Construction Safety Twin</h1>
<p>Fixed-camera construction footage turned into hazard incidents, leading indicators, a 3D digital
twin and a risk register, with a chatbot that answers only from the run and cites every fact.
Heuristic triage from video, not legal advice or certified measurement.</p></header>
<main>
<div class="steps">
  <div class="step"><b>1 · Detect</b><span>Workers, hard hats, machines, loads, fire and smoke, tracked
  through occlusion; faces pixelated in everything exported.</span></div>
  <div class="step"><b>2 · Assess</b><span>Eight hazard rules with debounce and evidence grades, leading
  indicators, and a 5×5 risk register with hierarchy-of-controls actions.</span></div>
  <div class="step"><b>3 · Explain</b><span>A 3D twin of the site, a "why it fired" trace per incident,
  and a chatbot whose every number is checked against the run.</span></div>
</div>
<h2>Processed runs</h2>
<div class="grid">{cards}</div>
<div class="about"><div>Chat answers come from <b>{llm}</b>; every number and worker is checked against
the facts it cites, and a failed check falls back to the risk register.</div>
<div><a href="/docs">API</a> · <a href="/api/stats">Chatbot monitoring</a> · <a href="/healthz">Health</a></div></div>
</main></body></html>"""
