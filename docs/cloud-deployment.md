# Cloud Deployment

This project has two deployables:

- Local worker: runs video processing and writes `output/<run_id>/`.
- Hugging Face Space: reads published runs from Supabase and serves the public review UI.

The cloud tier is intentionally small: Supabase Postgres stores run records and RAG
artifacts, Supabase Storage stores private media, and the Space signs media URLs at view
time.

## Required Services

| Service | Purpose | Free-tier use |
|---|---|---|
| Supabase | Postgres, `pgvector`, Storage bucket | stores runs, incidents, clause chunks, briefings, chat messages, and media |
| Hugging Face Spaces | public Gradio demo | hosts `cloud/space_app.py` as `app.py` |
| Google AI Studio | optional Gemini API key | reserved for future multimodal adjudication |
| Langfuse | optional tracing | reserved for future LLM observability |

## Environment

Create `.env` from `.env.example` and fill only local secrets there. Do not commit `.env`.

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon-public-key>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_BUCKET=run-media
HF_TOKEN=<write-token>
HF_SPACE=<username>/safety-twin
GEMINI_API_KEY=<optional>
LANGFUSE_PUBLIC_KEY=<optional>
LANGFUSE_SECRET_KEY=<optional>
LANGFUSE_HOST=https://cloud.langfuse.com
```

Mirror the same runtime keys into the Hugging Face Space secrets:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_BUCKET`
- `GEMINI_API_KEY` if enabled
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` if enabled

## Supabase Schema

Enable `pgvector`, create the private `run-media` bucket, then run
[`cloud/schema.sql`](../cloud/schema.sql) once in the Supabase SQL editor.

The schema creates:

- `runs`
- `incidents`
- `clause_chunks`
- `briefings`
- `chat_messages`

Public read policies are enabled for the demo. Writes use the service-role key from the
local publisher or Space runtime.

Verify table access:

```bash
uv run python - <<'PY'
from cloud.config import load_cloud_config
from cloud.supabase import SupabaseClient

client = SupabaseClient(load_cloud_config())
for table in ("runs", "incidents", "clause_chunks", "briefings", "chat_messages"):
    print(table, len(client.select(table, limit=1)))
PY
```

## Publish A Run

Generate a run locally:

```bash
uv run safety-twin process path/to/clip.mp4
```

Publish the run bundle:

```bash
uv run safety-twin publish output/<run_id>
```

The publisher uploads:

- `runs.manifest`
- incident payloads
- grounded briefing payloads
- bootstrap legal clause chunks
- `safety_twin.mp4`
- `report.html`

## Deploy The Hugging Face Space

The Space repo expects:

- `app.py` copied from `cloud/space_app.py`
- `README.md` copied from `cloud/README.space.md`
- `requirements.txt` copied from `cloud/requirements-space.txt`
- `cloud/`, `llm/`, and `shared/`

Deploy:

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

The current Space was created with ZeroGPU hardware. `cloud/space_app.py` includes a small
registered `@spaces.GPU` healthcheck so the ZeroGPU runtime boots, while normal run
browsing and Q&A remain CPU-light.

## Verification

Local handler smoke test:

```bash
uv run --with 'gradio>=4,<6' --with 'spaces>=0.30,<1' python - <<'PY'
from cloud.space_app import ask_run, load_run, zero_gpu_healthcheck

summary, briefings, video = load_run("run-7fec5e53c39b")
print("summary_ok", "run-7fec5e53c39b" in summary)
print("briefing_ok", "Cites:" in briefings)
print("video_ok", bool(video))
print("ask_ok", "R1" in ask_run("run-7fec5e53c39b", "Which helmet alerts were found?"))
print("zerogpu_probe", zero_gpu_healthcheck())
PY
```

Space runtime check:

```bash
uv run --with huggingface_hub python - <<'PY'
from cloud.config import load_cloud_config
from huggingface_hub import HfApi

cfg = load_cloud_config()
runtime = HfApi(token=cfg.hf_token).space_info(repo_id=cfg.hf_space).runtime
print(runtime)
PY
```

Expected user workflow:

1. Open the Space URL.
2. Click "Refresh runs".
3. Pick a run.
4. Confirm the safety-twin video, incident summary, and grounded briefing appear.
5. Ask: `Which helmet alerts were found?`
6. Confirm the answer cites R1 evidence and includes a tool trace.
