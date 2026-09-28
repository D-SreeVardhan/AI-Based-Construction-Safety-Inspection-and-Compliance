# Construction Safety 2.5D Twin

Construction-safety triage for fixed-camera site video. The local worker produces a
side-by-side MP4, rule coverage, incident records, and grounded legal briefings. The cloud
demo publishes those runs to Supabase and reviews them in a public Hugging Face Space.

This is a heuristic triage tool, not a certified safety system and not legal advice.
Distances are relative risk bands, not metres. The twin does not reconstruct hidden
geometry or BIM.

Public demo: [Vardhan220805/safety-twin](https://huggingface.co/spaces/Vardhan220805/safety-twin)

## Current Status

- Local pipeline: `safety-twin process` creates `output/<run_id>/` with synthetic Week-1
  detections, a placeholder safety-twin MP4, incident JSON, R1-R5 coverage, grounded
  briefings, and an HTML report.
- Local UI: `safety-twin app` serves the desktop review desk at `http://127.0.0.1:8765/`.
- Regulation RAG: deterministic BM25-style retrieval over a bootstrap BOCW clause corpus
  with citation grounding and legal-verdict refusal.
- Run Q&A: `/api/runs/<run_id>/ask` locally and the Space "Ask this run" panel answer
  run-scoped questions from incidents, rule coverage, and retrieved clauses.
- Cloud publish path: `safety-twin publish output/<run_id>` uploads runs, incidents,
  clauses, briefings, and private media objects to Supabase.
- Cloud demo: Gradio Space reads from Supabase, displays published runs, signs media URLs,
  shows grounded briefings, and records Q&A messages.

Real computer-vision detection is still future work; current detections are controlled
fixtures for validating the product, cloud, and LLM/RAG workflows.

## Hazard Rules

| Id | Meaning |
|---|---|
| R1 | Apparent missing helmet |
| R2 | Apparent missing hi-vis near machinery or traffic |
| R3 | Restricted-zone intrusion |
| R4 | Approximate machinery proximity |
| R5 | Possible missing fall protection near an elevated/open edge |

## Repository Layout

```text
app/           local server, browser UI, and CLI entrypoint
cloud/         Supabase schema/client, publisher, and Hugging Face Space app
jobs/          pipeline job orchestration
pipeline/      intake, rule evaluation, and processing components
twin/          2.5D rendering components
shared/        enums, config, coordinates, and pydantic schemas
llm/           retrieval, regulation corpus, deterministic briefing/Q&A layer
evaluation/    demo inventory and evaluation scaffolding
tools/         dataset and CCTV utilities
config/        runtime defaults
data/          local datasets and source clips, gitignored
docs/          project plan and deployment documentation
```

## Local Setup

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/). ffmpeg is required for MP4
generation.

```bash
uv sync --group dev
uv run pytest tests/unit tests/e2e
uv run safety-twin status
uv run safety-twin process path/to/clip.mp4
uv run safety-twin app
```

The pipeline writes run bundles under `output/<run_id>/`. Runtime media, datasets, model
weights, and `.env` files are intentionally gitignored.

## Cloud Setup

Copy `.env.example` to `.env` and fill:

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon-public-key>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_BUCKET=run-media
HF_TOKEN=<write-token>
HF_SPACE=Vardhan220805/safety-twin
GEMINI_API_KEY=<optional>
LANGFUSE_PUBLIC_KEY=<optional>
LANGFUSE_SECRET_KEY=<optional>
LANGFUSE_HOST=https://cloud.langfuse.com
```

Apply the database schema once in the Supabase SQL editor:

```sql
-- paste cloud/schema.sql
```

Publish a generated run:

```bash
uv run safety-twin publish output/<run_id>
```

Deploy the Space bundle:

```bash
tmpdir=$(mktemp -d)
cp -R cloud llm shared "$tmpdir"/
cp cloud/space_app.py "$tmpdir/app.py"
cp cloud/README.space.md "$tmpdir/README.md"
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

More details: [`docs/cloud-deployment.md`](docs/cloud-deployment.md).

## Data

Datasets and working videos are local-only and must not be committed. See
[`data/README.md`](data/README.md).

```bash
python3 tools/fetch_sard.py --list complementary
python3 tools/cctv.py vet data/source/your_clip.mp4
```

## Specification

Full project plan: [`docs/plan/construction-safety-2.5d-twin-plan-v7.md`](docs/plan/construction-safety-2.5d-twin-plan-v7.md)

## License

AGPL-3.0-or-later. Ultralytics / YOLO components used for academic open-source work
require AGPL-compatible distribution.
