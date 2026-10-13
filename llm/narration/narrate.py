"""Serve-time narration with a guaranteed deterministic fallback (v7 §45.5, §45.6)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from llm.narration.prompts import messages, template_arm
from llm.narration.schema import WordingRequest, WordingResponse
from llm.narration.validator import validate

Generate = Callable[[list[dict[str, str]]], str]
NarrationSource = Literal["student", "template"]


def narrate(
    request: WordingRequest, action_code: str, generate: Generate | None = None
) -> tuple[WordingResponse, NarrationSource]:
    """Validated model wording, or the deterministic template for any failure at all.

    A missing model, a generation error, and a rejected generation are the same outcome: the
    incident still gets readable wording, and nothing unvalidated is ever returned.
    """
    if generate is not None:
        try:
            raw = generate(messages(request, few_shot=False))
        except Exception:  # noqa: BLE001 - runtime failures of any kind must not reach the card
            raw = ""
        verdict = validate(request, action_code, raw)
        if verdict.valid and verdict.response is not None:
            return verdict.response, "student"
    return WordingResponse(**json.loads(template_arm(request))), "template"
