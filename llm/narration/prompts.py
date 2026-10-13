"""Prompts and the deterministic template arm for incident narration (v7 §45.5)."""

from __future__ import annotations

import json

from llm.narration.schema import WordingRequest
from shared.enums import DistanceBand

PROMPT_VERSION = "narration-v1"

SYSTEM = "You write short plain-language wording for a construction-site safety review tool."

INSTRUCTION = (
    "Return exactly two JSON string fields: reasoning and recommended_wording.\n"
    "Use only the supplied observations and deterministic action.\n"
    "Do not identify rules, cite regulations, change severity, add measurements,\n"
    "make legal/compliance claims, or introduce entities absent from allowed_entities.\n"
    "reasoning is 8-60 words. recommended_wording is 4-35 words.\n"
    "\nINPUT:\n"
)

# Hand-written few-shot exemplars. Their track ids and wording appear in no split.
_EXEMPLARS: tuple[tuple[WordingRequest, dict[str, str]], ...] = (
    (
        WordingRequest(
            observed_subject="Worker person-901",
            observed_condition="no helmet visible near the mixer",
            duration_s=7.5,
            deterministic_action="Verify head protection before work continues.",
            allowed_entities=("person-901",),
        ),
        {
            "reasoning": "Worker person-901 showed no helmet near the mixer for 7.5 seconds, "
            "so head protection could not be confirmed from the footage.",
            "recommended_wording": "Check that person-901 has head protection on before work "
            "continues.",
        },
    ),
    (
        WordingRequest(
            observed_subject="Worker person-902",
            observed_condition="close to a moving excavator",
            duration_s=12.0,
            relative_band=DistanceBand.NEAR,
            deterministic_action="Confirm the worker is kept away from the machine.",
            allowed_entities=("person-902", "excavator"),
        ),
        {
            "reasoning": "Worker person-902 stayed close to a moving excavator for 12.0 seconds, "
            "inside the near distance band.",
            "recommended_wording": "Confirm person-902 is kept away from the excavator while it "
            "moves.",
        },
    ),
    (
        WordingRequest(
            observed_subject="Worker person-903",
            observed_condition="inside a region inferred as restricted",
            duration_s=None,
            deterministic_action="Check whether the worker is authorised in this area.",
            allowed_entities=("person-903", "restricted_zone-2"),
        ),
        {
            "reasoning": "Worker person-903 was seen inside restricted_zone-2, an area inferred "
            "from the video as restricted.",
            "recommended_wording": "Check whether person-903 is authorised to be in this area.",
        },
    ),
    (
        WordingRequest(
            observed_subject="Worker person-904",
            observed_condition="no hi-vis vest while a vehicle is in the frame",
            duration_s=4.2,
            deterministic_action="Make sure a hi-vis vest is worn near vehicles.",
            allowed_entities=("person-904",),
        ),
        {
            "reasoning": "Worker person-904 appeared without a hi-vis vest for 4.2 seconds while "
            "a vehicle was in the frame.",
            "recommended_wording": "Make sure person-904 wears a hi-vis vest near vehicles.",
        },
    ),
)


def _user_turn(request: WordingRequest) -> str:
    return INSTRUCTION + request.canonical_json()


def messages(request: WordingRequest, *, few_shot: bool) -> list[dict[str, str]]:
    """Chat messages for one request; few-shot adds the four exemplar turns."""
    turns: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    if few_shot:
        for example, answer in _EXEMPLARS:
            turns.append({"role": "user", "content": _user_turn(example)})
            turns.append({"role": "assistant", "content": json.dumps(answer)})
    turns.append({"role": "user", "content": _user_turn(request)})
    return turns


def template_arm(request: WordingRequest) -> str:
    """Deterministic wording: the baseline every model arm must beat on readability."""
    parts = [
        f"{request.observed_subject} was observed with this condition: "
        f"{request.observed_condition}."
    ]
    if request.duration_s is not None:
        parts.append(f"It lasted {request.duration_s} seconds.")
    if request.relative_band is not None:
        parts.append(f"The relative distance band is {request.relative_band.value}.")
    return json.dumps(
        {"reasoning": " ".join(parts), "recommended_wording": request.deterministic_action}
    )
