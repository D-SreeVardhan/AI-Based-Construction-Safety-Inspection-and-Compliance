from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class CloudConfig:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_bucket: str
    gemini_api_key: str | None
    hf_token: str | None
    hf_space: str | None
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    langfuse_host: str | None


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_cloud_config(*, require_hf: bool = False) -> CloudConfig:
    load_dotenv()
    hf_token = os.environ.get("HF_TOKEN")
    hf_space = os.environ.get("HF_SPACE")
    if require_hf and (not hf_token or not hf_space):
        raise RuntimeError("HF_TOKEN and HF_SPACE are required for deployment.")
    return CloudConfig(
        supabase_url=_required("SUPABASE_URL").rstrip("/"),
        supabase_anon_key=_required("SUPABASE_ANON_KEY"),
        supabase_service_role_key=_required("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_bucket=os.environ.get("SUPABASE_BUCKET", "run-media"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        hf_token=hf_token,
        hf_space=hf_space,
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        langfuse_host=os.environ.get("LANGFUSE_HOST"),
    )
