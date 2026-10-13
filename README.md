# Construction Safety Twin

Automated CCTV safety-inspection triage for construction sites. Processes site footage
locally with YOLO11n + ByteTrack detection, classifies PPE compliance with a trained
two-head classifier reviewed by Gemini Vision, evaluates five hazard rules, and produces incident records, regulation-grounded briefings,
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
| **PPE assessment** | EfficientNet-B0 two-head classifier (helmet / vest / unknown) with per-track temporal smoothing; Gemini Vision reviews crops >= 160 px and overrides the classifier there (per-run SHA-256 cache, 429 retry, fail-fast on daily quota). Gemini-only when no weights are present |
| **Scene bootstrap** | One Gemini request per video proposes restricted zones and open edges from 8–12 keyframes; geometric cluster consensus keeps only shapes that recur (cached per video). Gemini's stated confidence is ignored |
| **Geometry** | `yolo26n-pose` standing head/foot pairs fit a zero-roll pinhole ground plane (Huber loss, bootstrap uncertainty). Distances are in worker-height units with interval bands. Quality gates mark moving or sparse feeds `unsupported` instead of guessing |
| **Rule engine** | R1–R5 hazard rules evaluated against real tracks; debounce and severity thresholds. R3 needs a consensus zone, R4 needs the ground plane, R5 needs an open edge plus the plane; each reports `inconclusive` or `unsupported_for_feed` with a reason code when its inputs are missing |
| **Regulation RAG** | 27-clause BOCW Central Rules corpus in Supabase; hybrid BM25 + Gemini-embedding-001 (768-dim) retrieval via Reciprocal Rank Fusion + MMR deduplication |
| **Grounded briefings** | Deterministic template grounded to retrieved clauses; ungrounded sentences refused |
| **Gemini Q&A** | Run-scoped Q&A with trigram grounding check; legal-verdict requests refused |
| **HTML report** | Self-contained provenance-stamped report per run (corpus SHA-256, model id, date) |
| **Cloud publish** | Uploads run bundle + media to Supabase; Space reads and signs URLs |

---

## Hazard Rules

| Rule | Description |
|---|---|
| R1 | Apparent missing helmet (30-frame debounce, YOLO + PPE classifier + Gemini Vision) |
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
  pipeline_job.py FakePipelineJob (fixtures) + RealPipelineJob (YOLO + PPE + Gemini)
llm/
  regulations.py  27-clause BOCW corpus (local bootstrap + Supabase sync)
  embeddings.py   Gemini embedding-001 REST wrapper + RRF fusion
  embedding_cache.py  lazy Supabase embedding singleton (thread-safe)
  retrieval.py    BM25 + dense retrieval + MMR reranking + briefing builder
  qa.py           Gemini RAG Q&A with grounding post-pass
  adjudicator.py  Gemini Vision PPE crop assessor (reviewer in hybrid mode)
  scene_proposals.py  Gemini scene-geometry request (one per video)
  narration/      LoRA wording experiment: corpus, validator, teacher/student runners, evaluation
pipeline/
  intake/         FrameSampler — OpenCV frame extraction + letterboxing
  vision/         Stage1Detector — YOLO11n + ByteTrack; ppe_model / ppe_temporal / ppe_stage
                  two-head PPE classifier, temporal filter, per-frame PPE stage
  data/           PPE person-crop labelling (ppe_crops) and MJCSD stage-1 conversion (mjcsd)
  scene/          Gemini keyframe proposals, geometric consensus, cached scene model
  geometry/       pose keypoints, ground-plane fit, worker-height distances, camera-motion gate
  rules/          engine.py (R1-R5), zone_rules (R3), proximity_rules (R4), edge_rules (R5)
  render/         render_twin_video() — side-by-side annotated feed + top-down map
  report/         build_report_html() — self-contained styled HTML report
shared/           enums, config, coordinates, pydantic schemas
evaluation/       demo inventory, detection metrics (AP50, precision/recall), results/*.json
tools/            dataset fetching, CCTV clip utilities, PPE and stage-1 builders and trainers
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

# Open the local review UI at http://127.0.0.1:8765/ (drop a clip, review it,
# then press "Publish to Space" to upload the run to Supabase)
uv run --extra vision safety-twin app
```

Run output lands in `output/<run_id>/`:

```
run_manifest.json   status, rule coverage, artifact paths, disclaimer
incidents.json      incident records with timestamps, confidence, track ids
briefings.json      regulation-grounded briefings with clause citations
tracks.jsonl        per-frame track observations
report.html         self-contained HTML report with provenance block
safety_twin.mp4     side-by-side twin: annotated source + approximate top-down site map
crops/              sampled person crops (one per track every 3 s)
ppe_verification.json  hybrid mode only: per reviewed crop, classifier vs Gemini verdict
evidence/           per-incident evidence placeholders
```

**PPE: hybrid classifier + Gemini, routed by resolution.** When
`artifacts/models/ppe/best.pt` exists, a two-head EfficientNet-B0 classifier (helmet / vest,
each with an `unknown` class) assesses every upright worker at least
`ppe.minimum_person_height_px` (40) tall, every `ppe.classify_every_frames` frames, and a
per-track temporal filter smooths the verdicts. Crops at least
`ppe.gemini_minimum_crop_height_px` (160) tall also go to Gemini (flagged workers first, at
most `ppe.maximum_gemini_verifications` calls), and a definite Gemini answer replaces the
classifier verdict around that frame. Small workers rely on the classifier, where Gemini
guesses; large ones rely on Gemini, because the classifier is trained on other footage and
on the yard clip reads a red-and-blue striped sweater as a hi-vis vest. Without the
weights, or without torch, the pipeline falls back to Gemini-only PPE.

Build the weights once from the Ultralytics Construction-PPE dataset in
`data/external/ultralytics-ppe/` (the trainer writes `metrics.json` with per-class
precision/recall, macro-F1 and calibration error, also at degraded 96/64/48 px):

```bash
uv run --extra vision python tools/build_ppe_crops.py data/external/ultralytics-ppe
uv run --extra vision python tools/train_ppe.py --epochs 40   # ~30 min on Apple MPS
```

**Gemini model and quota:** PPE verification and Q&A both use `scene.gemini_model` in
`config/defaults.yaml` (default `gemini-3.5-flash-lite`). Free-tier limits are per project
and per model; check the current numbers in AI Studio. Person crops shorter than
`ppe.gemini_minimum_crop_height_px` (160) are not sent to Gemini, because at that size
models guess a violation instead of answering `unknown`. When the quota is exhausted the
run still completes: in hybrid mode the classifier verdict is kept; in Gemini-only mode
R1/R2 report
`inconclusive (no_ppe_evidence)`, `gemini_status` is `failed`, and the manifest and report
carry a warning. Q&A falls back to deterministic answers (trace starts with
`gemini_qa_failed`) that quote the retrieved BOCW clauses.

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

or press **Publish to Space** in the local app after a run finishes. Publishing the same
run again overwrites its media and rows.

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
5. **Gemini QA** — the configured `scene.gemini_model` generates a 2–4 sentence answer grounded to the
   context block (incidents + coverage + retrieved clauses).
6. **Grounding post-pass** — trigram overlap between answer and context. Answers with
   < 8% overlap receive a visible low-evidence warning.
7. **Legal guardrail** — questions requesting compliance verdicts, liability decisions, or
   legal certifications are refused outright.

---

## Experiments

Results are committed under `evaluation/results/`; weights and corpora are local-only.

**Stage-1 detector (MJCSD fine-tune).** Splits are by camera/day (seed 42017); cameras are
*not* held out, so scores measure new days on known cameras.

```bash
uv run --extra vision python tools/build_stage1.py --source data/external/mjcsd/extracted/DATASET --max-train 3200
uv run --extra vision python tools/train_stage1.py train --epochs 12    # ~85 min on Apple MPS
uv run --extra vision python tools/train_stage1.py evaluate             # writes stage1.json
```

Person AP50 0.671 -> 0.871 and merged machinery AP50 0.129 -> 0.867 against the pretrained
YOLO11n on 1,505 held-out frames. Copy `best.pt` to `artifacts/models/stage1/best.pt` to use it;
the detector resolves classes by name, so the COCO and MJCSD weights are interchangeable.

**Narration LoRA (Qwen2.5-7B teacher -> Qwen2.5-1.5B student, MLX, Apple silicon).**

```bash
uv sync --extra vision --extra train
uv run safety-llm corpus seed && uv run safety-llm teacher generate   # ~45 min
uv run safety-llm corpus gate && uv run safety-llm student train      # ~2 min
uv run safety-llm eval run                                            # writes narration.json
```

The student does not pass the promotion gate (see `evaluation/results/narration.json`), so
incident wording stays on the deterministic template. `llm.narration.narrate.narrate()` is the
guarded entry point: any model failure or rejected generation falls back to the template.
Human blind ratings and false-refusal rate are not measured; the rating sheet is written to
`data/working/llm/blind/`.

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
