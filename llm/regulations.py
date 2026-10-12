from __future__ import annotations

import hashlib

from shared.enums import RuleId
from shared.schemas.llm import ClauseChunk

SOURCE_URL = "https://clc.gov.in/clc/acts-rules/building-and-other-construction-workers"
RETRIEVED_ON = "2026-09-27"

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768


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
        source="BOCW Central Rules 1998 expanded catalogue",
        clause_ref=clause_ref,
        title=title,
        text=text,
        source_url=SOURCE_URL,
        retrieved_on=RETRIEVED_ON,
        sha256=digest,
    )


BOOTSTRAP_CLAUSES: tuple[ClauseChunk, ...] = (
    # ── R1 — Head protection ──────────────────────────────────────────────────
    _chunk(
        chunk_id="bocw-ppe-helmet-r1",
        rule_ids=(RuleId.R1,),
        clause_ref="BOCW Central Rules r67(1): PPE head protection",
        title="Head protection where falling-object or impact risk exists",
        text=(
            "Workers exposed to falling material, impact, or similar construction hazards "
            "should be provided suitable head protection and should use the protective "
            "equipment while exposed to that hazard."
        ),
    ),
    _chunk(
        chunk_id="bocw-helmet-provision-r1",
        rule_ids=(RuleId.R1,),
        clause_ref="BOCW Central Rules r67(2): helmet provision duty",
        title="Employer duty to provide and maintain helmets",
        text=(
            "Every employer shall provide each worker with a protective helmet that conforms "
            "to the relevant Indian Standard and shall replace any helmet that is damaged, "
            "defective, or past its service life at no cost to the worker."
        ),
    ),
    _chunk(
        chunk_id="bocw-helmet-use-r1",
        rule_ids=(RuleId.R1,),
        clause_ref="BOCW Central Rules r67(3): worker duty to wear helmet",
        title="Worker obligation to wear head protection at all times on site",
        text=(
            "Every worker shall wear the protective helmet at all times while in any area of "
            "the construction site where there is a risk of head injury from falling objects, "
            "low structures, moving plant, or other construction hazards."
        ),
    ),
    _chunk(
        chunk_id="bocw-helmet-inspection-r1",
        rule_ids=(RuleId.R1,),
        clause_ref="BOCW Central Rules r67(4): helmet inspection and record",
        title="Inspection and record-keeping for personal protective equipment",
        text=(
            "PPE including helmets shall be inspected before each shift and a record maintained. "
            "Damaged or expired PPE must be withdrawn from use, logged, and replaced. "
            "Records are subject to inspection by the safety officer."
        ),
    ),
    _chunk(
        chunk_id="bocw-head-protection-exceptions-r1",
        rule_ids=(RuleId.R1,),
        clause_ref="BOCW Central Rules r67(5): exemptions and equivalents",
        title="Equivalent head protection accepted where helmet impractical",
        text=(
            "Where wearing a hard hat is genuinely impractical due to the nature of the work, "
            "the employer may substitute equivalent head protection approved in writing by the "
            "building worker welfare board. Exemptions must be site-specific and time-limited."
        ),
    ),
    # ── R2 — Hi-vis / conspicuous clothing near machinery ─────────────────────
    _chunk(
        chunk_id="bocw-ppe-visibility-r2",
        rule_ids=(RuleId.R2,),
        clause_ref="BOCW Central Rules r68(1): conspicuous clothing near traffic and plant",
        title="Conspicuous clothing near moving machinery or traffic",
        text=(
            "Workers operating near moving vehicles, construction plant, or traffic routes "
            "should wear conspicuous clothing so they remain visible to operators and other "
            "workers."
        ),
    ),
    _chunk(
        chunk_id="bocw-hiviz-spec-r2",
        rule_ids=(RuleId.R2,),
        clause_ref="BOCW Central Rules r68(2): specification for high-visibility garment",
        title="Specification of high-visibility vest or jacket",
        text=(
            "High-visibility garments shall be fluorescent yellow, orange, or lime-green with "
            "retro-reflective strips conforming to IS 15809 or equivalent. Garments that are "
            "faded, torn, or obscured by overgarments do not satisfy this requirement."
        ),
    ),
    _chunk(
        chunk_id="bocw-hiviz-zone-r2",
        rule_ids=(RuleId.R2,),
        clause_ref="BOCW Central Rules r68(3): hi-vis requirement zones",
        title="Mandatory zones for high-visibility clothing",
        text=(
            "High-visibility clothing is mandatory in: traffic management areas, plant "
            "movement corridors, loading and unloading zones, and any area where construction "
            "machinery operates within 10 metres of pedestrian routes."
        ),
    ),
    _chunk(
        chunk_id="bocw-hiviz-night-r2",
        rule_ids=(RuleId.R2,),
        clause_ref="BOCW Central Rules r68(4): night-time and low-visibility conditions",
        title="Enhanced visibility requirements at night or in poor visibility",
        text=(
            "During night-time working or in conditions of reduced visibility, workers "
            "shall wear Class 3 high-visibility garments with additional LED or reflective "
            "strips, and the site shall be adequately illuminated to a minimum of 50 lux "
            "in work areas."
        ),
    ),
    _chunk(
        chunk_id="bocw-hiviz-maintenance-r2",
        rule_ids=(RuleId.R2,),
        clause_ref="BOCW Central Rules r68(5): maintenance and replacement of hi-vis garments",
        title="Maintenance and replacement of high-visibility garments",
        text=(
            "Employers shall inspect and replace high-visibility garments that are damaged, "
            "soiled beyond cleaning, or whose retro-reflective strips have degraded below "
            "the required luminance. Replacement shall be at the employer's cost."
        ),
    ),
    # ── R3 — Restricted zones ─────────────────────────────────────────────────
    _chunk(
        chunk_id="bocw-zone-control-r3",
        rule_ids=(RuleId.R3,),
        clause_ref="BOCW Central Rules r45(1): restricted access to hazardous areas",
        title="Restrict access to hazardous work zones",
        text=(
            "Hazardous construction zones should be controlled by barriers, signs, supervision, or "
            "other access restrictions so that only authorised workers enter the area."
        ),
    ),
    _chunk(
        chunk_id="bocw-zone-barrier-r3",
        rule_ids=(RuleId.R3,),
        clause_ref="BOCW Central Rules r45(2): physical barrier specification",
        title="Physical barrier and signage specification for restricted zones",
        text=(
            "A restricted zone shall be physically defined by rigid barriers or fencing at "
            "least 1 metre high, supplemented by warning signs visible from all approach "
            "directions. Tape alone does not constitute an adequate barrier."
        ),
    ),
    _chunk(
        chunk_id="bocw-zone-permit-r3",
        rule_ids=(RuleId.R3,),
        clause_ref="BOCW Central Rules r45(3): permit-to-enter system",
        title="Permit-to-enter for high-hazard restricted zones",
        text=(
            "Entry to restricted zones where high-hazard work is in progress requires a "
            "written permit signed by the site safety officer. The permit shall specify the "
            "work allowed, PPE required, maximum number of persons, and expiry time."
        ),
    ),
    _chunk(
        chunk_id="bocw-zone-marking-r3",
        rule_ids=(RuleId.R3,),
        clause_ref="BOCW Central Rules r45(4): ground marking and lighting",
        title="Ground marking and illumination of restricted zones",
        text=(
            "Restricted zone boundaries shall be clearly marked on the ground using paint, "
            "cones, or other durable markers. At night or in reduced visibility, boundaries "
            "shall be highlighted with continuous red or amber warning lamps."
        ),
    ),
    # ── R4 — Plant and machinery separation ───────────────────────────────────
    _chunk(
        chunk_id="bocw-plant-separation-r4",
        rule_ids=(RuleId.R4,),
        clause_ref="BOCW Central Rules r55(1): safe operation of construction plant",
        title="Safe separation from operating construction plant",
        text=(
            "Where construction plant or machinery is operating, workers should be kept clear "
            "of the danger zone and movement path unless the work is controlled by a safe "
            "system of work."
        ),
    ),
    _chunk(
        chunk_id="bocw-plant-exclusion-r4",
        rule_ids=(RuleId.R4,),
        clause_ref="BOCW Central Rules r55(2): exclusion zone around operating plant",
        title="Minimum exclusion zone around operating plant and machinery",
        text=(
            "An exclusion zone of at least the maximum operating radius plus 1 metre shall "
            "be maintained around operating cranes, excavators, and other slewing plant. "
            "No worker shall enter this zone without the operator's knowledge and agreement."
        ),
    ),
    _chunk(
        chunk_id="bocw-plant-traffic-r4",
        rule_ids=(RuleId.R4,),
        clause_ref="BOCW Central Rules r55(3): plant traffic management",
        title="Traffic management plan for construction plant movement",
        text=(
            "A site traffic management plan shall designate plant routes, pedestrian routes, "
            "and crossing points. Plant and pedestrian routes shall be separated wherever "
            "practicable. Crossing points shall be controlled by a banksman or traffic signals."
        ),
    ),
    _chunk(
        chunk_id="bocw-plant-operator-r4",
        rule_ids=(RuleId.R4,),
        clause_ref="BOCW Central Rules r55(4): plant operator competence",
        title="Competence and authorisation requirements for plant operators",
        text=(
            "Only workers who hold a valid certificate of competence from a recognised training "
            "body shall operate construction plant or machinery. A copy of the certificate "
            "shall be kept on site and presented to the safety officer on request."
        ),
    ),
    _chunk(
        chunk_id="bocw-plant-inspection-r4",
        rule_ids=(RuleId.R4,),
        clause_ref="BOCW Central Rules r55(5): pre-use and periodic inspection",
        title="Pre-use and periodic inspection requirements for plant",
        text=(
            "All construction plant shall undergo a pre-use inspection before each shift and "
            "a comprehensive inspection by a competent person at intervals not exceeding "
            "three months. Defects found shall be recorded and rectified before the plant "
            "is returned to service."
        ),
    ),
    # ── R5 — Edge protection and fall prevention ──────────────────────────────
    _chunk(
        chunk_id="bocw-edge-fall-r5",
        rule_ids=(RuleId.R5,),
        clause_ref="BOCW Central Rules r38(1): edge protection and fall prevention",
        title="Protection near open edges and elevated work",
        text=(
            "Open edges and elevated working areas should have guardrails, covers, safety nets, or "
            "other fall-prevention measures where a worker may fall from height."
        ),
    ),
    _chunk(
        chunk_id="bocw-edge-guardrail-r5",
        rule_ids=(RuleId.R5,),
        clause_ref="BOCW Central Rules r38(2): guardrail specification",
        title="Minimum guardrail specification for open edges",
        text=(
            "Guardrails shall consist of a top rail at 900–1100 mm height, an intermediate "
            "rail at approximately mid-height, and a toe board at least 150 mm high. "
            "The guardrail system shall withstand a force of 740 N applied at the top rail."
        ),
    ),
    _chunk(
        chunk_id="bocw-edge-harness-r5",
        rule_ids=(RuleId.R5,),
        clause_ref="BOCW Central Rules r38(3): personal fall arrest system",
        title="Personal fall arrest system where guardrails are impractical",
        text=(
            "Where guardrails cannot be provided, workers shall wear a full-body harness "
            "attached to a certified anchor point capable of withstanding a 15 kN load. "
            "The free-fall distance shall not exceed 2 metres."
        ),
    ),
    _chunk(
        chunk_id="bocw-edge-net-r5",
        rule_ids=(RuleId.R5,),
        clause_ref="BOCW Central Rules r38(4): safety net installation",
        title="Safety net installation and inspection requirements",
        text=(
            "Safety nets shall be installed as close as practicable below the work level and "
            "shall extend at least 2 metres beyond the work area. Nets shall be inspected "
            "for damage before each shift and replaced if any defects are found."
        ),
    ),
    _chunk(
        chunk_id="bocw-edge-scaffold-r5",
        rule_ids=(RuleId.R5,),
        clause_ref="BOCW Central Rules r38(5): scaffold and working platform edge protection",
        title="Edge protection requirements on scaffolds and working platforms",
        text=(
            "All scaffolds and working platforms from which a person could fall more than "
            "2 metres shall have guardrails and toe boards on all open sides. Scaffold "
            "boards shall be secured to prevent tipping and shall not project more than "
            "4 times their thickness beyond the support."
        ),
    ),
    # ── Cross-cutting general safety ──────────────────────────────────────────
    _chunk(
        chunk_id="bocw-ppe-general-all",
        rule_ids=(RuleId.R1, RuleId.R2),
        clause_ref="BOCW Central Rules r66: general PPE duties",
        title="General duty to provide and use appropriate PPE on construction sites",
        text=(
            "Every employer engaged in building or construction work shall provide, free of "
            "charge, adequate and suitable PPE to each worker exposed to a risk that cannot "
            "be adequately controlled by other means. Workers must use the PPE provided and "
            "must not misuse or interfere with it."
        ),
    ),
    _chunk(
        chunk_id="bocw-safety-officer-all",
        rule_ids=(RuleId.R1, RuleId.R2, RuleId.R3, RuleId.R4, RuleId.R5),
        clause_ref="BOCW Central Rules r8: site safety officer duties",
        title="Duties of the site safety officer",
        text=(
            "The site safety officer shall conduct daily inspections of the site to ensure "
            "compliance with PPE requirements, access controls, plant safety, and fall "
            "prevention. Non-compliances shall be recorded and reported to the principal "
            "employer within 24 hours."
        ),
    ),
    _chunk(
        chunk_id="bocw-incident-report-all",
        rule_ids=(RuleId.R1, RuleId.R2, RuleId.R3, RuleId.R4, RuleId.R5),
        clause_ref="BOCW Central Rules r11: accident reporting obligation",
        title="Obligation to report accidents and dangerous occurrences",
        text=(
            "Every accident resulting in loss of life, serious bodily injury, or a dangerous "
            "occurrence as specified in Schedule IV shall be reported by the employer to the "
            "inspector within 4 hours. A detailed written report shall follow within 48 hours. "
            "Records of all accidents shall be maintained for a minimum of 5 years."
        ),
    ),
)

CATALOGUE_SHA256 = hashlib.sha256(
    "\n".join(chunk.sha256 for chunk in BOOTSTRAP_CLAUSES).encode("utf-8")
).hexdigest()
