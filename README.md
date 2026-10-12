# Construction Safety Twin

Automated CCTV safety-inspection triage for construction sites. Processes site footage
locally with YOLO11n + ByteTrack detection, classifies PPE compliance with Gemini Vision,
evaluates five hazard rules, and produces incident records, regulation-grounded briefings,
and a provenance-stamped HTML report. Completed runs are published to Supabase and
reviewable in a live Hugging Face Space with a Gemini-powered Q&A interface.

> **Not a certified safety system.** All outputs are heuristic triage; not legal advice
> and not a substitute for a qualified safety officer review.

**Live demo:** [Vardhan220805/safety-twin](https://huggingface.co/spaces/Vardhan220805/safety-twin)

---

## What it does

| Layer | What runs |
|---|---|
| **Intake** | Samples frames from any MP4 via OpenCV; letterboxes to model input size |
| **Detection** | YOLO11n detects persons and vehicles; ByteTrack assigns persistent track IDs |
| **PPE adjudication** | Gemini Vision assesses helmet and vest state per crop (per-run SHA-256 cache, 429 retry, fail-fast on daily quota) |
| **Rule engine** | R1–R5 hazard rules evaluated against real tracks; debounce and severity thresholds |
| **Regulation RAG** | 27-clause BOCW Central Rules corpus in Supabase; hybrid BM25 + Gemini-embedding-001 (768-dim) retrieval via Reciprocal Rank Fusion + MMR deduplication |
| **Grounded briefings** | Deterministic template grounded to retrieved clauses; ungrounded sentences refused |
| **Gemini Q&A** | Run-scoped Q&A with trigram grounding check; legal-verdict requests refused |
| **HTML report** | Self-contained provenance-stamped report per run (corpus SHA-256, model id, date) |
| **Cloud publish** | Uploads run bundle + media to Supabase; Space reads and signs URLs |

---

## Hazard Rules

| Rule | Description |
|---|---|
| R1 | Apparent missing helmet (30-frame debounce, YOLO + Gemini Vision) |
| R2 | Apparent missing hi-vis vest near machinery or traffic |
| R3 | Restricted-zone intrusion |
| R4 | Approximate machinery proximity |
| R5 | Possible missing fall protection near an elevated or open edge |

---

## Repository Layout

```
app/              local HTTP server and browser review UI
cloud/
  config.py       CloudConfig dataclass and load_cloud_config()
  corpus_sync.py  syncs 27-clause corpus to Supabase with Gemini embeddings
  publish.py      uploads run bundles to Supabase storage + DB
  space_app.py    Hugging Face Gradio Space
  supabase.py     REST client (select / upsert / upload / signed URLs)
  schema.sql      Supabase DDL (runs, incidents, briefings, clause_chunks, chat_messages)
jobs/
  pipeline_job.py FakePipelineJob (fixtures) + RealPipelineJob (YOLO + ByteTrack + Gemini)
llm/
  regulations.py  27-clause BOCW corpus (local bootstrap + Supabase sync)
  embeddings.py   Gemini embedding-001 REST wrapper + RRF fusion
  embedding_cache.py  lazy Supabase embedding singleton (thread-safe)
  retrieval.py    BM25 + dense retrieval + MMR reranking + briefing builder
  qa.py           Gemini RAG Q&A with grounding post-pass
  adjudicator.py  Gemini Vision PPE crop assessor
pipeline/
  intake/         FrameSampler — OpenCV frame extraction + letterboxing
  vision/         Stage1Detector — YOLO11n + ByteTrack
  rules/engine.py evaluate_real_rules() (R1+R2) and evaluate_fake_rules()
  report/         build_report_html() — self-contained styled HTML report
shared/           enums, config, coordinates, pydantic schemas
evaluation/       demo inventory schema + CLI scaffold
tools/            dataset fetching and CCTV clip utilities
```

---

## Local Setup

**Requirements:** Python 3.11, [uv](https://docs.astral.sh/uv/), ffmpeg

```bash
# Install all dependencies (including vision extras)
uv sync --extra vision --group dev

# Run tests
uv run pytest tests/

# Check system status
uv run safety-twin status

# Process a clip: real YOLO + Gemini pipeline when GEMINI_API_KEY is set in .env,
# synthetic fixture pipeline otherwise (force it with --fake)
uv run safety-twin process path/to/clip.mp4

# Open the local review UI at http://127.0.0.1:8765/
uv run safety-twin app
```

Run output lands in `output/<run_id>/`:

```
run_manifest.json   status, rule coverage, artifact paths, disclaimer
incidents.json      incident records with timestamps, confidence, track ids
briefings.json      regulation-grounded briefings with clause citations
tracks.jsonl        per-frame track observations
report.html         self-contained HTML report with provenance block
safety_twin.mp4     placeholder twin video (annotated rendering not implemented yet)
crops/              person crops sent to Gemini for PPE assessment
evidence/           per-incident evidence placeholders
```

**Gemini free tier:** `gemini-2.5-flash` allows 20 requests/day per project, shared by
PPE adjudication and Q&A. One 30 s clip uses roughly 17 PPE requests. When the quota is
exhausted the run still completes: R1/R2 report `inconclusive (no_ppe_evidence)`,
`gemini_status` is `failed`, and the manifest and report carry a warning. Q&A falls back
to deterministic answers that quote the retrieved BOCW clauses.

---

## Cloud Setup

Copy `.env.example` to `.env` and populate:

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon-public-key>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_BUCKET=run-media
GEMINI_API_KEY=<required for real pipeline and RAG>
HF_TOKEN=<write-token for Space deployment>
HF_SPACE=Vardhan220805/safety-twin
```

Apply the database schema once in the Supabase SQL editor:

```sql
-- paste the contents of cloud/schema.sql
```

**Sync the regulation corpus** (run once after schema is applied):

```bash
uv run python -m cloud.corpus_sync
```

This embeds all 27 BOCW clauses with `gemini-embedding-001` (768-dim) and upserts them
into the `clause_chunks` table. Required for hybrid dense retrieval to function.

**Publish a run:**

```bash
uv run safety-twin publish output/<run_id>
```

**Deploy the Hugging Face Space:**

```bash
tmpdir=$(mktemp -d)
cp -R cloud llm shared "$tmpdir"/
cp cloud/space_app.py "$tmpdir/app.py"
cp cloud/requirements-space.txt "$tmpdir/requirements.txt"
uv run --with huggingface_hub python - <<'PY' "$tmpdir"
import sys
from huggingface_hub import HfApi
from cloud.config import load_cloud_config
cfg = load_cloud_config()
HfApi(token=cfg.hf_token).upload_folder(
    repo_id=cfg.hf_space,
    repo_type="space",
    folder_path=sys.argv[1],
    commit_message="Deploy cloud safety twin app",
    ignore_patterns=["**/__pycache__/**", "**/*.pyc"],
)
PY
rm -rf "$tmpdir"
```

---

## Retrieval and Q&A Architecture

The Q&A stack uses a three-stage hybrid pipeline:

1. **BM25 lexical retrieval** — tokenised query matched against the 27-clause local corpus
   with semantic hint boosting per rule id.
2. **Dense retrieval** — `gemini-embedding-001` query embedding matched against
   768-dim clause vectors stored in Supabase `clause_chunks`.
3. **RRF fusion** — Reciprocal Rank Fusion (k=60) merges the two ranked lists.
4. **MMR reranking** — Maximal Marginal Relevance (λ=0.6) diversifies the top-k results
   so near-duplicate clauses do not fill all slots.
5. **Gemini QA** — `gemini-2.5-flash` generates a 2–4 sentence answer grounded to the
   context block (incidents + coverage + retrieved clauses).
6. **Grounding post-pass** — trigram overlap between answer and context. Answers with
   < 8% overlap receive a visible low-evidence warning.
7. **Legal guardrail** — questions requesting compliance verdicts, liability decisions, or
   legal certifications are refused outright.

---

## Data

Datasets, source clips, and model weights are local-only and gitignored:

```bash
python3 tools/fetch_sard.py --list complementary
python3 tools/cctv.py vet data/source/your_clip.mp4
```

---

## License

AGPL-3.0-or-later. YOLO/Ultralytics components require AGPL-compatible distribution for
academic and open-source use.
