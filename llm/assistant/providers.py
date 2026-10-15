"""LLM backends for the chatbot, all through the OpenAI-compatible chat-completions API.

One client covers hosted APIs and local servers; which one is used is configuration:

    SAFETY_LLM_PROVIDER   gemini | groq | openrouter | hf | anthropic | ollama | custom
    SAFETY_LLM_API_KEY    the provider's key (never committed; a secret in the cloud)
    SAFETY_LLM_MODEL      optional; overrides the provider's default model
    SAFETY_LLM_BASE_URL   required for `custom`, optional override otherwise
    SAFETY_LLM_REASONING  optional `reasoning_effort` (none | low | medium | high); thinking
                          models otherwise spend the token budget before answering
    SAFETY_LLM_FALLBACK_MODELS  optional, comma-separated: tried when the model is overloaded

Standard library only, so the server image stays small.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

PRESETS: dict[str, tuple[str, str]] = {
    # provider: (base URL, default model). Model names change; SAFETY_LLM_MODEL overrides.
    # Gemini 3.8 Flash is on the free tier (ai.google.dev/gemini-api/docs/pricing, Oct 2026).
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free"),
    "hf": ("https://router.huggingface.co/v1", "Qwen/Qwen2.5-72B-Instruct"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-haiku-5-5"),
    "ollama": ("http://localhost:11434/v1", "qwen3.5:2b"),
}
# Thinking kept short by default: local thinking models answer directly ("none"); Gemini 3
# models cannot turn thinking off, so the least that grounded Q&A needs ("low").
DEFAULT_REASONING = {"ollama": "none", "gemini": "low"}
# Backup models on the same free tier, for when the main one returns "high demand".
DEFAULT_FALLBACKS = {"gemini": ("gemini-3.6-flash", "gemini-2.5-flash")}
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class ChatProvider:
    name: str
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 60.0
    reasoning: str | None = None
    # Tried in order when the main model is overloaded or down (429, 5xx, timeout); free
    # tiers see "high demand" 503s at peak hours. A bad key or request fails at once.
    fallback_models: tuple[str, ...] = ()

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> Completion:
        error: ProviderError | None = None
        for model in (self.model, *self.fallback_models):
            try:
                return self._call(model, messages, temperature, max_tokens)
            except ProviderError as failure:
                if not failure.transient:
                    raise
                error = failure
        assert error is not None
        raise error

    def _call(
        self,
        model: str,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Completion:
        body: dict[str, object] = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise ProviderError(
                f"{self.name} {model} returned HTTP {error.code}: {detail}",
                transient=error.code in TRANSIENT_HTTP,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ProviderError(f"{self.name} unreachable: {error}", transient=True) from error
        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(f"{self.name} sent an unexpected reply") from error
        usage = payload.get("usage") or {}
        return Completion(
            text=_strip_thinking(text),
            model=payload.get("model") or model,
            latency_s=round(time.perf_counter() - started, 2),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


def _strip_thinking(text: str) -> str:
    """Reasoning models may prepend <think>…</think>; only the answer is shown."""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def from_env(env: Mapping[str, str] | None = None) -> ChatProvider | None:
    """The configured provider, or None (the chatbot then answers from the register)."""
    env = os.environ if env is None else env
    name = (env.get("SAFETY_LLM_PROVIDER") or "").strip().lower()
    if not name or name == "none":
        return None
    base, model = PRESETS.get(name, ("", ""))
    base = env.get("SAFETY_LLM_BASE_URL") or base
    model = env.get("SAFETY_LLM_MODEL") or model
    key = env.get("SAFETY_LLM_API_KEY") or None
    if not base or not model:
        raise ProviderError(f"provider {name!r} needs SAFETY_LLM_BASE_URL and SAFETY_LLM_MODEL")
    if name not in ("ollama", "custom") and not key:
        raise ProviderError(f"provider {name!r} needs SAFETY_LLM_API_KEY")
    timeout = float(env.get("SAFETY_LLM_TIMEOUT_S") or 60)
    reasoning = env.get("SAFETY_LLM_REASONING") or DEFAULT_REASONING.get(name)
    listed = env.get("SAFETY_LLM_FALLBACK_MODELS")
    fallbacks = (
        tuple(m.strip() for m in listed.split(",") if m.strip())
        if listed is not None
        else DEFAULT_FALLBACKS.get(name, ())
    )
    return ChatProvider(
        name=name,
        base_url=base,
        model=model,
        api_key=key,
        timeout_s=timeout,
        reasoning=reasoning,
        fallback_models=tuple(m for m in fallbacks if m != model),
    )
