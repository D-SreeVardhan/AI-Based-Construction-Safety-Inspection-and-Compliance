"""Risk register for one run: a 5×5 likelihood × severity assessment of what the clip showed.

Deterministic, so the chatbot and the report quote the same ratings and the LLM never
scores anything itself.

* **Severity** (1–5) is the catalogue's: critical 5, high 4, medium 3, low 2.
* **Likelihood** (1–5) is judged from this clip only:
  1 rare            assessed, the condition never held (listed as "checked, not observed")
  2 unlikely        held only briefly, under the rule's alert threshold
  3 possible        one confirmed incident
  4 likely          2–4 incidents, or at least 10 % of the workers seen were exposed
  5 almost certain  5 or more incidents, or at least 25 % of the workers seen were exposed
  When every incident of a rule has weak evidence, likelihood drops one step (not below 2).
* **Rating** = likelihood × severity: low ≤ 4, medium 5–10, high 12–16, very high ≥ 20.

A rule that could not be assessed (unsupported, inconclusive or not applicable) is never
rated low: it is listed separately with the reason. Controls follow the hierarchy of
controls and are general good practice, not legal requirements.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from shared.enums import RuleId, RuleStatus
from shared.identity import display_track_label
from shared.schemas.incidents import IncidentRecord
from shared.schemas.insights import InsightsFile
from shared.schemas.run import RunManifest

SEVERITY_SCORE = {"critical": 5, "high": 4, "medium": 3, "low": 2}
LIKELIHOOD = {1: "rare", 2: "unlikely", 3: "possible", 4: "likely", 5: "almost certain"}
LIKELY_SHARE, CERTAIN_SHARE = 0.10, 0.25

HAZARD = {
    RuleId.R1: "Struck on the head by falling objects or impact, without a helmet",
    RuleId.R2: "Struck by vehicles or plant while not conspicuous",
    RuleId.R3: "Exposure inside an area that should be kept clear",
    RuleId.R4: "Struck by or caught between moving machinery",
    RuleId.R5: "Fall from an open or elevated edge",
    RuleId.R6: "A worker down: collapse, fall or injury needing a response",
    RuleId.R7: "Struck by a falling or swinging suspended load",
    RuleId.R8: "Fire or smoke: burns, smoke inhalation, blocked escape",
}

# Hierarchy of controls: eliminate, engineer, administer, then PPE.
CONTROLS: dict[RuleId, tuple[tuple[str, str], ...]] = {
    RuleId.R1: (
        ("Eliminate", "Plan overhead work so nobody works or walks below it"),
        ("Engineering", "Toe boards, debris netting and covered walkways under work at height"),
        ("Administrative", "Hard-hat signage at entrances; supervisor check at task start"),
        ("PPE", "Issue well-fitting helmets with chin straps; replace damaged ones"),
    ),
    RuleId.R2: (
        ("Engineering", "Separate pedestrian routes from vehicle routes with barriers"),
        ("Administrative", "Traffic management plan, one-way routes, a banksman for reversing"),
        ("PPE", "High-visibility clothing of the right class in movement areas"),
    ),
    RuleId.R3: (
        ("Eliminate", "Re-plan the work so the exclusion zone is not on a walking route"),
        ("Engineering", "Replace tape with rigid barriers or fencing and a controlled gate"),
        ("Administrative", "Permit-to-work for entry, signage, and a toolbox talk on the zone"),
    ),
    RuleId.R4: (
        ("Engineering", "Physical separation from plant; proximity warning devices"),
        ("Administrative", "Marked swing radius, banksman, eye contact with the operator"),
        ("PPE", "High-visibility clothing for anyone near operating plant"),
    ),
    RuleId.R5: (
        ("Eliminate", "Prefabricate at ground level; cover or close openings"),
        ("Engineering", "Guardrails, toe boards, covers and safety nets at the edge"),
        ("Administrative", "Restrict access to trained workers; permit for edge work"),
        ("PPE", "Harness and lanyard on a rated anchor, as the last resort"),
    ),
    RuleId.R6: (
        (
            "Administrative",
            "Trained first-aiders on every shift and a clear way to raise the alarm",
        ),
        ("Administrative", "Emergency response plan, rescue access, and lone-working check-ins"),
    ),
    RuleId.R7: (
        ("Engineering", "Exclusion zone below every lift; tag lines to control the load"),
        ("Administrative", "Lift plan, appointed person and signaller; never work under a load"),
    ),
    RuleId.R8: (
        ("Eliminate", "Remove combustibles and waste from hot-work areas"),
        ("Engineering", "Extinguishers at every hot-work point; clear escape routes"),
        ("Administrative", "Hot-work permit, fire watch, alarm and evacuation drill"),
    ),
}

NOT_ASSESSED = {
    RuleStatus.UNSUPPORTED: "the feed cannot support this check",
    RuleStatus.INCONCLUSIVE: "the evidence was not good enough to decide",
    RuleStatus.NOT_APPLICABLE: "nothing to check in this clip",
}


def band(rating: int) -> str:
    if rating >= 20:
        return "very high"
    if rating >= 12:
        return "high"
    if rating >= 5:
        return "medium"
    return "low"


@dataclass(frozen=True)
class RiskRow:
    rule_id: RuleId
    title: str
    hazard: str
    severity: str
    severity_score: int
    likelihood_score: int
    rating: int
    band: str
    incidents: int
    brief_exposures: int
    exposure_s: float
    workers_exposed: int
    worker_share: float
    weak_evidence: int
    top_workers: tuple[str, ...]
    areas: tuple[str, ...]
    incident_ids: tuple[str, ...]
    why: str
    controls: tuple[tuple[str, str], ...]

    @property
    def likelihood(self) -> str:
        return LIKELIHOOD[self.likelihood_score]


@dataclass(frozen=True)
class RiskAssessment:
    run_id: str
    duration_s: float
    workers_seen: int
    rows: tuple[RiskRow, ...]
    not_observed: tuple[tuple[RuleId, str], ...]
    not_assessed: tuple[tuple[RuleId, str, str], ...]
    notes: tuple[str, ...] = field(default=())

    def row(self, rule_id: RuleId) -> RiskRow | None:
        return next((r for r in self.rows if r.rule_id is rule_id), None)


def likelihood(incidents: int, brief: int, share: float, *, all_weak: bool) -> int:
    if incidents == 0:
        return 2 if brief > 0 else 1
    score = 3
    if incidents >= 2 or share >= LIKELY_SHARE:
        score = 4
    if incidents >= 5 or share >= CERTAIN_SHARE:
        score = 5
    return max(2, score - 1) if all_weak else score


def assess(
    manifest: RunManifest,
    incidents: list[IncidentRecord],
    insights: InsightsFile | None,
    *,
    titles: dict[RuleId, str],
    severities: dict[RuleId, str],
    workers_seen: int,
) -> RiskAssessment:
    by_rule: dict[RuleId, list[IncidentRecord]] = {}
    for incident in incidents:
        by_rule.setdefault(incident.rule_id, []).append(incident)
    exposure = {e.rule_id: e for e in insights.exposure} if insights else {}
    coverage = {c.rule_id: c for c in manifest.rule_coverage}
    rows, not_observed, not_assessed = [], [], []
    for rule_id in RuleId:
        found = by_rule.get(rule_id, [])
        held = exposure.get(rule_id)
        entry = coverage.get(rule_id)
        if not found and (held is None or (held.exposure_s == 0 and held.brief_exposures == 0)):
            if entry is not None and entry.status in NOT_ASSESSED:
                not_assessed.append((rule_id, entry.reason_code, NOT_ASSESSED[entry.status]))
            else:
                not_observed.append((rule_id, entry.reason_code if entry else "no_data"))
            continue
        exposed = held.workers_exposed if held else len({i.canonical_track_id for i in found})
        share = exposed / workers_seen if workers_seen else 0.0
        brief = held.brief_exposures if held else 0
        weak = sum(i.evidence_quality == "weak" for i in found)
        score_l = likelihood(len(found), brief, share, all_weak=bool(found) and weak == len(found))
        severity = severities.get(rule_id, "medium")
        score_s = SEVERITY_SCORE.get(severity, 3)
        rating = score_l * score_s
        rows.append(
            RiskRow(
                rule_id=rule_id,
                title=titles.get(rule_id, rule_id.value),
                hazard=HAZARD[rule_id],
                severity=severity,
                severity_score=score_s,
                likelihood_score=score_l,
                rating=rating,
                band=band(rating),
                incidents=len(found),
                brief_exposures=brief,
                exposure_s=round(held.exposure_s, 1) if held else 0.0,
                workers_exposed=exposed,
                worker_share=round(share, 3),
                weak_evidence=weak,
                top_workers=_top_workers(rule_id, found, insights),
                areas=_areas(rule_id, insights),
                incident_ids=tuple(i.incident_id for i in found),
                why=_why(len(found), brief, share, weak, score_l),
                controls=CONTROLS[rule_id],
            )
        )
    rows.sort(key=lambda r: (-r.rating, -r.incidents, r.rule_id.value))
    notes = (
        "Ratings describe this clip, not the site over time.",
        "Distances and zones are estimated from one camera; heuristic rules need checking on site.",
    )
    return RiskAssessment(
        run_id=manifest.run_id,
        duration_s=manifest.input_video.duration_s or 0.0,
        workers_seen=workers_seen,
        rows=tuple(rows),
        not_observed=tuple(not_observed),
        not_assessed=tuple(not_assessed),
        notes=notes,
    )


def _why(incidents: int, brief: int, share: float, weak: int, score: int) -> str:
    parts = []
    if incidents:
        parts.append(f"{incidents} confirmed incident{'s' if incidents != 1 else ''}")
    if brief:
        parts.append(f"{brief} brief exposure{'s' if brief != 1 else ''} under the threshold")
    if share:
        parts.append(f"{share:.0%} of workers seen were exposed")
    if weak and weak == incidents:
        parts.append("all on weak evidence, so likelihood was lowered one step")
    return f"{LIKELIHOOD[score].capitalize()}: " + ", ".join(parts) + "."


def _top_workers(
    rule_id: RuleId, found: list[IncidentRecord], insights: InsightsFile | None
) -> tuple[str, ...]:
    if insights:
        ranked = sorted(
            (w for w in insights.top_workers if w.by_rule.get(rule_id.value)),
            key=lambda w: -w.by_rule[rule_id.value],
        )
        if ranked:
            return tuple(display_track_label(w.canonical_track_id) for w in ranked[:3])
    counts = Counter(i.canonical_track_id for i in found if i.canonical_track_id)
    return tuple(display_track_label(t) for t, _ in counts.most_common(3))


def _areas(rule_id: RuleId, insights: InsightsFile | None) -> tuple[str, ...]:
    if not insights:
        return ()
    ranked = sorted(
        (a for a in insights.area_exposure if a.rule_id is rule_id and a.exposure_s > 0),
        key=lambda a: -a.exposure_s,
    )
    return tuple(a.label or a.proposal_id for a in ranked[:3])
