from __future__ import annotations

import hashlib

from shared.enums import RuleId
from shared.schemas.llm import ClauseChunk

SOURCE_URL = "https://clc.gov.in/clc/acts-rules/building-and-other-construction-workers"
RETRIEVED_ON = "2026-09-27"


def _chunk(
    *,
    chunk_id: str,
    rule_ids: tuple[RuleId, ...],
    clause_ref: str,
    title: str,
    text: str,
) -> ClauseChunk:
    digest = hashlib.sha256(f"{clause_ref}\n{text}".encode()).hexdigest()
    return ClauseChunk(
        chunk_id=chunk_id,
        rule_ids=rule_ids,
        source="BOCW Central Rules 1998 bootstrap catalogue",
        clause_ref=clause_ref,
        title=title,
        text=text,
        source_url=SOURCE_URL,
        retrieved_on=RETRIEVED_ON,
        sha256=digest,
    )


BOOTSTRAP_CLAUSES: tuple[ClauseChunk, ...] = (
    _chunk(
        chunk_id="bocw-ppe-helmet-r1",
        rule_ids=(RuleId.R1,),
        clause_ref="BOCW Central Rules: PPE head protection",
        title="Head protection where falling-object or impact risk exists",
        text=(
            "Workers exposed to falling material, impact, or similar construction hazards "
            "should be provided suitable head protection and should use the protective "
            "equipment while exposed to that hazard."
        ),
    ),
    _chunk(
        chunk_id="bocw-ppe-visibility-r2",
        rule_ids=(RuleId.R2,),
        clause_ref="BOCW Central Rules: conspicuous clothing near traffic and plant",
        title="Conspicuous clothing near moving machinery or traffic",
        text=(
            "Workers operating near moving vehicles, construction plant, or traffic routes "
            "should wear conspicuous clothing so they remain visible to operators and other "
            "workers."
        ),
    ),
    _chunk(
        chunk_id="bocw-zone-control-r3",
        rule_ids=(RuleId.R3,),
        clause_ref="BOCW Central Rules: restricted access to hazardous areas",
        title="Restrict access to hazardous work zones",
        text=(
            "Hazardous construction zones should be controlled by barriers, signs, supervision, or "
            "other access restrictions so that only authorised workers enter the area."
        ),
    ),
    _chunk(
        chunk_id="bocw-plant-separation-r4",
        rule_ids=(RuleId.R4,),
        clause_ref="BOCW Central Rules: safe operation of construction plant",
        title="Safe separation from operating construction plant",
        text=(
            "Where construction plant or machinery is operating, workers should be kept clear "
            "of the danger zone and movement path unless the work is controlled by a safe "
            "system of work."
        ),
    ),
    _chunk(
        chunk_id="bocw-edge-fall-r5",
        rule_ids=(RuleId.R5,),
        clause_ref="BOCW Central Rules: edge protection and fall prevention",
        title="Protection near open edges and elevated work",
        text=(
            "Open edges and elevated working areas should have guardrails, covers, safety nets, or "
            "other fall-prevention measures where a worker may fall from height."
        ),
    ),
)

CATALOGUE_SHA256 = hashlib.sha256(
    "\n".join(chunk.sha256 for chunk in BOOTSTRAP_CLAUSES).encode("utf-8")
).hexdigest()
