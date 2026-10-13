"""Local MLX generation for the teacher and student models (v7 §14.2, §45.5)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import snapshot_download

try:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
except ImportError:  # pragma: no cover - needs the train extra on Apple silicon
    generate = load = make_sampler = None  # type: ignore[assignment]

TEACHER_REPO = "mlx-community/Qwen2.5-7B-Instruct-4bit"
# The plan pins this revision; if the Hub no longer resolves it, the resolved commit is
# recorded in the evaluation report instead of silently using a moving ref.
TEACHER_REVISION = "c26a38f6a37d0a51b4e9a1eb3026530fa35d9fed"
STUDENT_REPO = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
MAX_NEW_TOKENS = 192


@dataclass(frozen=True)
class Generation:
    text: str
    seconds: float
    tokens: int


def resolve_snapshot(repo: str, revision: str | None) -> tuple[Path, str]:
    """Download (or reuse) a model snapshot; returns its path and resolved commit hash."""
    try:
        local = Path(snapshot_download(repo, revision=revision))
    except Exception:  # noqa: BLE001 - any Hub failure for a pinned ref falls back to the branch head
        if revision is None:
            raise
        local = Path(snapshot_download(repo))
    return local, local.name


class MlxChat:
    """Greedy, batch-1 chat generation, optionally with a LoRA adapter."""

    def __init__(self, repo: str, revision: str | None, adapter_path: Path | None = None) -> None:
        if load is None:
            raise ImportError("mlx-lm is required (uv sync --extra train, Apple silicon only)")
        path, self.resolved_revision = resolve_snapshot(repo, revision)
        self.repo = repo
        self.model, self.tokenizer = load(
            str(path), adapter_path=str(adapter_path) if adapter_path else None
        )
        self._sampler = make_sampler(temp=0.0)

    def generate(self, messages: list[dict[str, str]]) -> Generation:
        prompt = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        started = time.perf_counter()
        text = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=MAX_NEW_TOKENS,
            sampler=self._sampler,
            verbose=False,
        )
        seconds = time.perf_counter() - started
        return Generation(text=text, seconds=seconds, tokens=len(self.tokenizer.encode(text)))
