"""Deterministic acceptance checks for narration (v7 §45.5, §45.6).

One function decides whether a generation may be shown. It uses no model, and every failure
is a named check so the evaluation can report which gate rejected what. Any failure discards
the whole generation, and callers fall back to the deterministic template.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from llm.narration.schema import WordingRequest, WordingResponse

REASONING_WORDS = (8, 60)
WORDING_WORDS = (4, 35)

# Output may not cite law, pass a verdict, or name a rule.
_CITATION = re.compile(r"(§|\b(rule|rules|act|bocw|section|clause|regulation)\b|\bIS\s*\d+)", re.I)
_VERDICT = re.compile(
    r"\b(compliant|non-compliant|violation|violates|illegal|unlawful|required by law|liable|penalty"
    r"|must legally|breach)\b",
    re.I,
)
_AUTHORITY = re.compile(r"\b(R[1-5]|severity|high severity|medium severity)\b")

# A claim the request never made: equipment, protective items, and harm.
_CLAIM_LEXICON = {
    "machinery": (
        "excavator",
        "crane",
        "truck",
        "loader",
        "roller",
        "bulldozer",
        "forklift",
        "lorry",
        "digger",
    ),
    "protective item": (
        "harness",
        "goggles",
        "gloves",
        "boots",
        "respirator",
        "glasses",
        "earplugs",
        "scaffold",
    ),
    "harm": ("injur", "accident", "fatal", "crush", "collision", "collide", "hurt", "died"),
    "environment": ("rain", "wet", "night", "dark", "wind", "storm", "slippery"),
}

# Each action concept is satisfied by any one of its tokens.
CONCEPT_TOKENS: dict[str, tuple[str, ...]] = {
    "helmet": ("helmet", "hard hat", "hardhat", "head protection", "headwear"),
    "vest": ("vest", "hi-vis", "high-visibility", "reflective", "high visibility"),
    "zone_access": (
        "zone",
        "area",
        "region",
        "authoris",
        "authoriz",
        "permit",
        "access",
        "allowed",
    ),
    "machinery_separation": (
        "clear",
        "away",
        "separat",
        "distance",
        "gap",
        "reach",
        "apart",
        "path",
    ),
    "edge_protection": ("edge", "guardrail", "rail", "barrier", "protect", "fall", "drop"),
}

_WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_TRACK = re.compile(r"\b(?:person|vehicle|worker)-\d+\b", re.I)

# Near-synonyms of the distance band, to catch outputs that contradict it.
_FAR_WORDS = re.compile(r"\b(far|distant|remote|safe distance away|well clear)\b", re.I)
_STOPWORDS = frozenset(
    "a an and are as at be been by for from has have in is it its of on or that the this to was "
    "were while with worker workers seen seems appears appear visible".split()
)


@dataclass(frozen=True)
class Verdict:
    valid: bool
    failures: tuple[str, ...]
    response: WordingResponse | None

    @property
    def claim_failures(self) -> tuple[str, ...]:
        return tuple(f for f in self.failures if f.split(":")[0] in _CLAIM_CHECKS)


# Checks that mean the output asserted something the input did not support.
_CLAIM_CHECKS = frozenset({"numbers", "entities", "claims", "citation", "verdict", "authority"})


def _words(text: str) -> list[str]:
    return text.split()


def _parse(raw: str) -> tuple[WordingResponse | None, str | None]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, "schema:not_json"
    if not isinstance(payload, dict) or set(payload) != {"reasoning", "recommended_wording"}:
        return None, "schema:keys"
    if not all(isinstance(v, str) for v in payload.values()):
        return None, "schema:types"
    return WordingResponse(**payload), None


def _source_text(request: WordingRequest) -> str:
    return " ".join(
        [
            request.observed_subject,
            request.observed_condition,
            request.deterministic_action,
            *request.allowed_entities,
            "" if request.duration_s is None else str(request.duration_s),
            "" if request.relative_band is None else request.relative_band.value,
        ]
    )


def _content_tokens(text: str) -> set[str]:
    return {w.lower().strip("'-") for w in _WORD.findall(text)} - _STOPWORDS


def validate(request: WordingRequest, action_code: str, raw: str) -> Verdict:
    """Apply every gate to one raw generation."""
    response, error = _parse(raw)
    if response is None:
        return Verdict(False, (error or "schema",), None)

    failures: list[str] = []
    for name, text, (low, high) in (
        ("reasoning", response.reasoning, REASONING_WORDS),
        ("recommended_wording", response.recommended_wording, WORDING_WORDS),
    ):
        count = len(_words(text))
        if not low <= count <= high:
            failures.append(f"schema:length_{name}")

    combined = f"{response.reasoning} {response.recommended_wording}"
    source = _source_text(request).lower()

    if _CITATION.search(combined):
        failures.append("citation:law_reference")
    if _VERDICT.search(combined):
        failures.append("verdict:compliance_language")
    if _AUTHORITY.search(combined):
        failures.append("authority:rule_or_severity")

    allowed_numbers = set(_NUMBER.findall(source))
    if any(n not in allowed_numbers for n in _NUMBER.findall(combined)):
        failures.append("numbers:not_in_request")

    for track in _TRACK.findall(combined):
        if track.lower() not in source:
            failures.append("entities:unknown_track")
            break
    lowered = combined.lower()
    for kind, terms in _CLAIM_LEXICON.items():
        unsupported = [t for t in terms if t in lowered and t not in source]
        if unsupported:
            failures.append(f"claims:{kind}")

    if not any(token in lowered for token in CONCEPT_TOKENS.get(action_code, ())):
        failures.append("action:concept_missing")
    if not _content_tokens(response.reasoning) & _content_tokens(request.observed_condition):
        failures.append("observation:condition_not_reflected")
    if request.relative_band is not None and _FAR_WORDS.search(combined):
        failures.append("observation:band_contradicted")
    return Verdict(not failures, tuple(failures), response if not failures else None)
