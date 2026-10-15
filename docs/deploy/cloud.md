# Cloud hosting and deployment (Section 11)

The project's public demo runs entirely on free tiers. **No account involved has a payment
method**, so nothing can be billed: if a free quota runs out, the provider suspends or
rate-limits the service instead of charging.

## What is deployed

```text
 GPU workstation (offline)                         Public cloud (free tiers)
 ──────────────────────────                        ──────────────────────────────────────────────
 safety-twin process clip.mp4  ──►  output/<run>/  Hugging Face dataset (private)
   detection, tracking, PPE, pose,      │          <you>/safety-twin-runs: published bundles
   rules R1–R8, twin, report, LoRA      │                    │ downloaded at startup
   narrator                             │                    ▼
 tools/publish_run.py ──────────────────┘          Render web service (Docker, Singapore)
   refuses runs without face pixelation            FastAPI app (app/cloud.py), HTTPS
                                                     /               run gallery
                                                     /runs/<id>/     report: twin, incidents,
                                                                     risk register + chatbot
                                                     /api/...        risk, chat, reviews, stats
                                                       │        │
                                       Gemini API ◄────┘        └────► Supabase Postgres
                                       (chatbot model)                 chat logs, reviews
 GitHub ── push ──► GitHub Actions (tests + Docker build + /healthz) ──checks pass──► Render deploy
```

Processing needs a GPU and stays on the workstation (2× real time on a GTX 1660 Ti); a free
CPU service would take hours per clip. The public URL does not depend on the workstation:
finished runs are published once and the cloud service serves them, the risk register and
the chatbot on its own.

## Section 11 table

| Item | What this project uses |
|---|---|
| **Cloud provider** | **Render** (web service, Singapore region) for the app; **Hugging Face Hub** (dataset) for run bundles; **Google AI Studio** (Gemini API) for the chatbot model; **Supabase** for Postgres. |
| **Free tier / credits** | Free tiers only, no payment method anywhere. Render Free: 750 instance-hours a month, 512 MB, sleeps after 15 min idle (about a minute to wake). Hugging Face: free dataset storage. Gemini API free tier: rate-limited per minute and per day. Supabase Free: 500 MB database; pauses after a week without activity. GitHub Actions: free minutes. |
| **Frontend hosting** | Served by the same Render service: the run gallery (`/`) and each run's report (`/runs/<id>/`) with the 3D twin, incident inbox, leading indicators, risk assessment and chat. Static HTML, CSS and JS with no build step; three.js is vendored, so no CDN either. |
| **Backend hosting** | FastAPI + uvicorn in Docker on Render's free web service. Endpoints: `/api/runs`, `/api/runs/<id>/risk`, `/api/runs/<id>/chat`, `/api/runs/<id>/reviews`, `/api/stats`, `/healthz`; OpenAPI at `/docs`. Uses about 70 MB of RAM. |
| **LLM hosting** | **Chatbot:** Gemini 3.8 Flash through Gemini's OpenAI-compatible API (free tier); any OpenAI-compatible provider can be swapped in with `SAFETY_LLM_PROVIDER`. **Incident narrator:** the LoRA-tuned Qwen2.5-1.5B runs offline at processing time, so its text ships inside the bundle. **Local development:** Ollama. |
| **Managed databases** | **Supabase Postgres:** `chat_logs`, `incident_reviews`, and the views `chat_daily` and `review_summary` ([`supabase.sql`](supabase.sql)). Row-level security is on and only the server's key can write. **Hugging Face dataset:** object storage for bundles. |
| **Containerisation** | [`Dockerfile`](../../Dockerfile): Python 3.11 slim with uv and a locked dependency set, no torch, a non-root user and a health check. [`.dockerignore`](../../.dockerignore) keeps data, models and footage out of the image. |
| **CI/CD** | **GitHub Actions** ([`ci.yml`](../../.github/workflows/ci.yml)) on every push: ruff, the test suite, a Docker build, and a `/healthz` check of the built container. **Render** redeploys the branch only after those checks pass (`autoDeployTrigger: checksPass`). Infrastructure as code: [`render.yaml`](../../render.yaml). |
| **Environment config & secrets** | Render environment variables; secrets are marked `sync: false` in `render.yaml` and typed into the dashboard, never stored in the file. Locally, `.env` is git-ignored and [`.env.example`](../../.env.example) lists every variable without values. No secret is in the repository or the image. |
| **Domain & HTTPS** | `https://<service>.onrender.com` with a Render-managed TLS certificate; HTTP redirects to HTTPS. A custom domain is optional and also free on Render. |
| **Monitoring / logging (LLMOps)** | One JSON log line per chat answer, in Render's log view and in Supabase `chat_logs`: answer source (`model` or `register`), model id, latency, tokens, which checks failed, citations, and a salted hash of the client. Live counters at `/api/stats`: model share, latency p50/p90, check failures. Supabase view `chat_daily` gives daily trends. Render health checks plus a free UptimeRobot monitor on `/healthz`. Guardrail outcomes are the quality metric: an answer that fails a check is never shown. |
| **Estimated monthly cost** | **$0.** With no payment method on file, quota exhaustion means suspension or rate limits, never a bill. Light paid upgrade if ever needed: Render Starter ($7/month, no sleep). |
| **Public demo URL** | `https://<service>.onrender.com`, filled in after the first deploy (step 4 below). |

## Deployment steps

You need the fork pushed to GitHub with the `feat/cv-pipeline` branch, and about 30 minutes.

1. **Publish the runs (Hugging Face, free).**
   1. Sign up at huggingface.co. Under *Settings → Access Tokens*, create a **Write** token.
   2. Run:

      ```bash
      uv run hf auth login        # paste the write token
      uv run python tools/publish_run.py output/sard9-r7fix output/sard8-v3 --repo <you>/safety-twin-runs --private
      ```

      The tool validates each bundle and refuses any run whose media were not face-pixelated. The 1080p master video stays local.
   3. Create a second, **Read** token for the server. It goes into Render in step 4.
2. **Gemini key (free).** At aistudio.google.com choose *Get API key → Create API key*. Do not enable billing; the key works on the free tier.
3. **Database (Supabase, free; optional but fills the managed-database row).**
   1. At supabase.com, create a *New project* (Free plan, region Singapore).
   2. In *SQL Editor*, paste [`supabase.sql`](supabase.sql) and run it.
   3. From *Project Settings → API*, copy the **Project URL** and the **service_role** key. The service_role key is server-only and must never go into a browser.
4. **App (Render, free, no card).**
   1. Sign up at render.com with GitHub, then choose *New → Blueprint* and pick the fork.
   2. Render reads `render.yaml` and asks for these secrets:
      - `SAFETY_RUNS_REPO` = `<you>/safety-twin-runs`
      - `HF_TOKEN` = the read token
      - `SAFETY_LLM_API_KEY` = the Gemini key
      - `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`, or leave both empty to skip the database.
   3. Choose *Apply*. The first build takes about 5 minutes.
   4. The URL appears at the top of the service page.
5. **Check it.**
   1. `https://<service>.onrender.com/healthz` should show `"runs": 2`, the Gemini model, and `"database": true` if Supabase is set.
   2. Open a run, go to *Risk assessment*, and ask a question. Each answer shows which model wrote it, or "from the risk register".
   3. Render's *Logs* tab should show `{"event": "chat", ...}` lines, and Supabase *Table editor → chat_logs* fills in.
6. **Monitoring (UptimeRobot, free).** Add an HTTP(S) monitor on `/healthz` every 5 minutes. It alerts by email if the demo is down. It also keeps the free service awake during evaluation week: one always-on service uses about 744 of Render's 750 free hours.
7. **Updates.**
   - **Code:** push to the branch. CI runs, and Render deploys once it passes.
   - **New runs:** `tools/publish_run.py`, then *Manual Deploy → Restart service* on Render to fetch them.

Local equivalent of the cloud app, with no accounts needed:

```bash
uv sync --extra serve
SAFETY_RUNS_DIR=output SAFETY_LLM_PROVIDER=ollama uv run uvicorn app.cloud:app --port 8080
```

Any other OpenAI-compatible provider works the same way: groq, openrouter, hf, anthropic or custom (`llm/assistant/providers.py`).

## Privacy and data

- **What is published.**
  - Run bundles from the public SARD research footage, with worker faces pixelated in every frame, clip and crop.
  - Workers are known only by track number; there is no identity or biometrics.
  - The Hugging Face dataset is private, and only the server's read token can fetch it.
- **What the model sees.** The chatbot sends Gemini the run's facts: counts, times, track numbers, zone names and ratings, plus the user's question. No images are sent. On Gemini's free tier, Google may use prompts to improve its products, so don't type personal data into the chat.
- **What is logged.** Chat logs keep the question text for quality review. The client is stored only as a salted hash. Logs are deleted with the Supabase project (see the shutdown plan).

## Shutdown plan

After evaluation, or if a key is ever exposed:

1. **Render:** in the service's *Settings*, choose *Suspend* to keep the config, or *Delete Web Service*. Then delete the Blueprint.
2. **Revoke keys:**
   - Google AI Studio: delete the API key.
   - Hugging Face: delete both tokens.
   - Supabase: rotate or delete the service key.
3. **Data:**
   - Supabase: pause or delete the project, which deletes the chat logs and reviews.
   - Hugging Face: delete the `safety-twin-runs` dataset, or keep it private.
4. **Monitoring:** delete the UptimeRobot monitor.

No paid resource exists at any point, so shutdown leaves no cost behind.
