# Hosted demo: published runs, reports, risk register and chatbot (app/cloud.py).
# No GPU and no torch: processing happens on a workstation and finished bundles are
# published (tools/publish_run.py). See docs/deploy/cloud.md.
FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /bin/uv

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first, so code changes rebuild in seconds.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra serve --no-install-project

COPY app ./app
COPY jobs ./jobs
COPY llm ./llm
COPY pipeline ./pipeline
COPY shared ./shared
COPY twin ./twin
COPY tools ./tools
COPY evaluation ./evaluation
COPY regulations ./regulations
COPY config ./config
RUN uv sync --frozen --no-dev --extra serve --no-editable

# Published bundles baked into the image (fetched by CI; see .github/workflows/deploy.yml).
# The directory may be empty; SAFETY_RUNS_REPO can fetch bundles at startup instead.
COPY --chown=app:app runs ./runs
ENV SAFETY_RUNS_DIR=/app/runs

USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz', timeout=4)"
# Cloud Run and Render set $PORT; the proxy in front terminates HTTPS.
CMD ["sh", "-c", "exec uvicorn app.cloud:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
