"""The run as short, citable facts: everything the chatbot may say, and nothing else.

Each fact has an id the answer cites in square brackets ([I-03], [RISK-R3], ...), so a
reader can check every claim, and the guardrail can check every number against the
facts the model was shown. Deterministic: the same bundle always gives the same facts,
and `register_answer` answers common questions from them with no model at all (the
chatbot's fallback and the offline report's prepared answers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.output.risk import RiskRow
from pipeline.output.run_bundle import RunBundle
from shared.enums import RuleId
from shared.identity import display_track_label
from shared.schemas.incidents import IncidentRecord

RULE_WORDS = {
    RuleId.R1: "helmet hard hat head protection ppe headgear",
    RuleId.R2: "hi-vis high visibility vest conspicuity ppe vehicle traffic",
    RuleId.R3: "restricted zone exclusion area intrusion entry boundary barrier",
    RuleId.R4: "machine machinery plant excavator proximity distance struck",
    RuleId.R5: "edge fall height opening guardrail fall protection",
    RuleId.R6: "worker down lying collapse fall injured medical first aid",
    RuleId.R7: "crane hook suspended load lift beneath under",
    RuleId.R8: "fire smoke flames burning hot work evacuation",
}


@dataclass(frozen=True)
class Fact:
    id: str
    kind: str  # summary | risk | not_observed | not_assessed | incident | worker | area | limits
    text: str
    rule: RuleId | None = None
    workers: tuple[str, ...] = ()
    time_s: float | None = None
    keywords: str = ""
    links: dict[str, str] = field(default_factory=dict)
    brief: str = ""  # a shorter form for register answers; the model always sees `text`


def clock(seconds: float) -> str:
    minutes, rest = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes)}:{rest:04.1f}"


def incident_ids(bundle: RunBundle) -> dict[str, str]:
    """Incident id → short citation id (I-01 …) in time order."""
    ordered = sorted(bundle.incidents, key=lambda i: (i.first_seen_s, i.incident_id))
    return {i.incident_id: f"I-{n:02d}" for n, i in enumerate(ordered, 1)}


def build_facts(bundle: RunBundle) -> list[Fact]:
    risk = bundle.risk
    short = incident_ids(bundle)
    facts = [_summary(bundle)]
    for row in risk.rows:
        facts.append(_risk(row, short))
    for rule_id, reason in risk.not_observed:
        facts.append(
            Fact(
                id=f"CLEAR-{rule_id.value}",
                kind="not_observed",
                rule=rule_id,
                text=f"{rule_id.value} {_title(bundle, rule_id)}: checked for the whole clip and "
                f"not observed ({reason.replace('_', ' ')}).",
                keywords=RULE_WORDS[rule_id],
            )
        )
    for rule_id, reason, why in risk.not_assessed:
        facts.append(
            Fact(
                id=f"NA-{rule_id.value}",
                kind="not_assessed",
                rule=rule_id,
                text=f"{rule_id.value} {_title(bundle, rule_id)}: not assessed in this clip "
                f"— {why} "
                f"({reason.replace('_', ' ')}). This is not the same as no risk.",
                keywords=RULE_WORDS[rule_id],
            )
        )
    ordered = sorted(bundle.incidents, key=lambda i: (i.first_seen_s, i.incident_id))
    facts += [_incident(bundle, incident, short[incident.incident_id]) for incident in ordered]
    facts += _workers(bundle, short)
    facts += _areas(bundle)
    facts.append(_limits(bundle))
    return facts


def _title(bundle: RunBundle, rule_id: RuleId) -> str:
    return bundle.catalogue.rule(rule_id).title


def _summary(bundle: RunBundle) -> Fact:
    m = bundle.manifest
    risk = bundle.risk
    top = ", ".join(f"{r.rule_id.value} {r.band} ({r.rating}/25)" for r in risk.rows[:3]) or "none"
    exposure = (
        f" Workers spent {sum(e.exposure_s for e in bundle.insights.exposure) / 60:.1f} "
        "worker-minutes in a hazard condition."
        if bundle.insights
        else ""
    )
    return Fact(
        id="RUN",
        kind="summary",
        text=(
            f"Run {m.run_id}: {bundle.duration_s:.0f} s of fixed-camera video, "
            f"{bundle.workers_seen} workers seen for at least 3 s, "
            f"{len(bundle.incidents)} confirmed incidents across "
            f"{len({i.rule_id for i in bundle.incidents})} rules.{exposure} "
            f"Highest risks: {top}."
        ),
        keywords="overview summary site run clip total how many biggest top risk",
    )


def _risk(row: RiskRow, short: dict[str, str]) -> Fact:
    cited = " ".join(short[i] for i in row.incident_ids[:6] if i in short)
    where = f" Where: {', '.join(row.areas)}." if row.areas else ""
    who = f" Most exposed workers: {', '.join(row.top_workers)}." if row.top_workers else ""
    controls = " ".join(f"{level}: {text}." for level, text in row.controls)
    return Fact(
        id=f"RISK-{row.rule_id.value}",
        kind="risk",
        rule=row.rule_id,
        workers=row.top_workers,
        text=(
            f"{row.rule_id.value} {row.title} — hazard: {row.hazard}. "
            f"Risk {row.band}, rating {row.rating}/25 = likelihood {row.likelihood_score} "
            f"({row.likelihood}) × severity {row.severity_score} ({row.severity}). {row.why} "
            f"Exposure {row.exposure_s:.1f} worker-seconds, {row.workers_exposed} workers."
            f"{where}{who} Incidents: {cited or 'none'}. "
            f"Recommended controls (hierarchy of controls, general good practice): {controls}"
        ),
        keywords=RULE_WORDS[row.rule_id] + " risk rating likelihood severity control fix",
        brief=(
            f"{row.rule_id.value} {row.title}: {row.band} risk ({row.rating}/25). {row.why} "
            f"{row.workers_exposed} workers exposed for {row.exposure_s:.1f} worker-seconds."
            f"{where}"
        ),
    )


def _incident(bundle: RunBundle, incident: IncidentRecord, short: str) -> Fact:
    worker = display_track_label(incident.canonical_track_id or "")
    end = incident.resolved_at_s
    duration = f"{end - incident.first_seen_s:.1f} s" if end is not None else "until the clip ended"
    subject = f"worker {worker}" if incident.rule_id is not RuleId.R8 else f"region {worker}"
    where = ""
    zones = [bundle.zone_labels.get(p, p) for p in incident.proposal_ids]
    if zones:
        where = f" in {', '.join(zones)}"
    if incident.object_id and incident.rule_id in (RuleId.R2, RuleId.R4):
        where += f" near machine {display_track_label(incident.object_id)}"
    if incident.object_id and incident.rule_id is RuleId.R7:
        where += f" under suspended load {display_track_label(incident.object_id)}"
    distance = (
        f" Closest distance {incident.distance.lower_wh:.1f}–{incident.distance.upper_wh:.1f} WH."
        if incident.distance
        else ""
    )
    ppe = ""
    if incident.helmet and incident.rule_id in (RuleId.R1, RuleId.R2):
        ppe = f" Helmet state {incident.helmet.state}, vest state "
        ppe += f"{incident.vest.state}." if incident.vest else "unknown."
    seen = (
        f" Visible {incident.trace.observed_fraction:.0%} of the episode." if incident.trace else ""
    )
    return Fact(
        id=short,
        kind="incident",
        rule=incident.rule_id,
        workers=(worker,) if incident.rule_id is not RuleId.R8 else (),
        time_s=incident.first_seen_s,
        text=(
            f"{incident.rule_id.value} {incident.title}: {subject}{where} from "
            f"{clock(incident.first_seen_s)} for {duration} ({incident.severity} severity, "
            f"{incident.evidence_quality or 'ungraded'} evidence, {incident.basis} rule)."
            f"{distance}{ppe}{seen} Action: {incident.action_text}"
        ),
        keywords=RULE_WORDS[incident.rule_id],
        links={
            "evidence": incident.evidence_path,
            **({"clip": incident.evidence_clip_path} if incident.evidence_clip_path else {}),
        },
    )


def _workers(bundle: RunBundle, short: dict[str, str]) -> list[Fact]:
    if not bundle.insights:
        return []
    by_worker: dict[str, list[IncidentRecord]] = {}
    for incident in bundle.incidents:
        if incident.canonical_track_id and incident.rule_id is not RuleId.R8:
            by_worker.setdefault(incident.canonical_track_id, []).append(incident)
    facts = []
    for worker in bundle.insights.top_workers:
        label = display_track_label(worker.canonical_track_id)
        rules = ", ".join(f"{rule} {seconds:.1f} s" for rule, seconds in worker.by_rule.items())
        found = by_worker.get(worker.canonical_track_id, [])
        cited = " ".join(short[i.incident_id] for i in found)
        facts.append(
            Fact(
                id=f"W-{label}",
                kind="worker",
                workers=(label,),
                text=(
                    f"Worker {label}: {worker.exposure_s:.1f} s in hazard conditions ({rules}); "
                    f"{len(found)} confirmed incident{'s' if len(found) != 1 else ''}"
                    f"{': ' + cited if cited else ''}."
                ),
                keywords="worker person who most exposed",
            )
        )
    return facts


def _areas(bundle: RunBundle) -> list[Fact]:
    if not bundle.insights:
        return []
    return [
        Fact(
            id=f"AREA-{n}",
            kind="area",
            rule=area.rule_id,
            text=(
                f"{area.label or area.proposal_id} ({area.rule_id.value}): "
                f"{area.exposure_s:.1f} worker-seconds of exposure by {area.workers} workers."
            ),
            keywords="where area zone hotspot location " + RULE_WORDS[area.rule_id],
        )
        for n, area in enumerate(bundle.insights.area_exposure, 1)
        if area.exposure_s > 0
    ]


def _limits(bundle: RunBundle) -> Fact:
    warnings = [w for w in bundle.manifest.warnings if "battery" not in w]
    synthetic = any("synthetic" in label.lower() for label in bundle.zone_labels.values())
    return Fact(
        id="LIMITS",
        kind="limits",
        text=(
            "Limits: heuristic triage from one fixed camera, not a certified safety system "
            "and not legal advice. Distances are in worker heights (WH), not metres. "
            "Workers are known only by track number; faces are pixelated."
            + (" Some zones are synthetic demo zones." if synthetic else "")
            + (f" Run warnings: {'; '.join(warnings)}." if warnings else "")
        ),
        keywords="limits reliable accuracy trust caveat how sure confidence privacy",
    )


# ---------------------------------------------------------------------- register answers

WORKER = re.compile(r"\bworker\s*#?\s*(\d+)", re.I)
RULE = re.compile(r"\bR([1-8])\b", re.I)
# Phrases that put a question about one rule (substring match on the lowered question).
INTENT = {
    RuleId.R1: ("helmet", "hard hat", "hardhat", "head protection", "headgear"),
    RuleId.R2: ("hi-vis", "high-vis", "high vis", "hi vis", "vest", "conspicu"),
    RuleId.R3: ("restricted", "exclusion", "zone", "intrusion"),
    RuleId.R4: ("machine", "excavator", "plant", "proximity", "vehicle"),
    RuleId.R5: ("edge", "fall protection", "guardrail", "opening"),
    RuleId.R6: ("worker down", "lying", "collapse", "injur", "unconscious", "man down"),
    RuleId.R7: ("crane", "suspended", "hook", "lift", "load"),
    RuleId.R8: ("fire", "smoke", "flame", "burning"),
}
# Questions the report offers as one-click prompts; answered offline from the register.
SUGGESTED = (
    "What are the biggest risks on this site?",
    "What should I fix first?",
    "What could the system not check?",
    "How reliable is this assessment?",
)


def rules_in(question: str) -> list[RuleId]:
    q = question.lower()
    found = [RuleId(f"R{n}") for n in RULE.findall(q)]
    for rule_id, phrases in INTENT.items():
        if rule_id not in found and any(phrase in q for phrase in phrases):
            found.append(rule_id)
    return found[:2]


def register_answer(bundle: RunBundle, facts: list[Fact], question: str) -> tuple[str, list[Fact]]:
    """Answer from the facts alone: bullet lines, each ending with its citation."""
    q = question.lower()
    by_id = {fact.id: fact for fact in facts}
    risk = bundle.risk
    lines: list[str] = []
    cited: list[Fact] = []

    def say(fact: Fact | None, text: str | None = None) -> None:
        if fact is None:
            return
        lines.append(f"- {text or fact.brief or fact.text} [{fact.id}]")
        cited.append(fact)

    worker = WORKER.search(question)
    rules = rules_in(question)
    if worker:
        label = worker.group(1)
        found = [f for f in facts if label in f.workers and f.kind in ("worker", "incident")]
        if not found:
            lines.append(
                f"- Worker {label} has no confirmed incident or recorded hazard exposure in "
                "this clip [RUN]."
            )
            cited.append(by_id["RUN"])
        for fact in found[:6]:
            say(fact)
    elif rules:
        for rule_id in rules:
            say(
                by_id.get(f"RISK-{rule_id.value}")
                or by_id.get(f"NA-{rule_id.value}")
                or by_id.get(f"CLEAR-{rule_id.value}")
            )
            for fact in [f for f in facts if f.kind == "incident" and f.rule is rule_id][:4]:
                say(fact)
    elif any(w in q for w in ("not check", "coverage", "miss", "blind", "not assess")):
        for fact in facts:
            if fact.kind == "not_assessed":
                say(fact)
        clear = [f for f in facts if f.kind == "not_observed"]
        if clear:
            lines.append(
                "- Checked and not observed: "
                + ", ".join(f"{f.rule.value} [{f.id}]" for f in clear if f.rule)
            )
            cited.extend(clear)
    elif re.search(r"\b(which|who|most)\b.*\b(worker|exposed|exposure|people|person)", q):
        ranked = [f for f in facts if f.kind == "worker"][:3]  # facts keep exposure order
        for fact in ranked or [by_id["RUN"]]:
            say(fact)
    elif re.search(r"\b(reliab\w*|accura\w*|trust\w*|sure|limit\w*|confiden\w*)\b", q):
        say(by_id["LIMITS"])
    elif any(w in q for w in ("do ", "fix", "priorit", "action", "recommend", "control", "first")):
        for row in risk.rows[:3]:
            now = bundle.catalogue.rule(row.rule_id).action_template.strip()
            level, text = row.controls[0]
            step = (
                f"Now: {now} Then ({level.lower()}): {text}."
                if row.incidents
                else f"No confirmed incident, only brief exposures; prevent ({level.lower()}): "
                f"{text}."
            )
            say(
                by_id[f"RISK-{row.rule_id.value}"],
                f"{row.rule_id.value} {row.title} ({row.band} risk, {row.rating}/25). {step}",
            )
    else:
        say(by_id["RUN"])
        for row in risk.rows[:3]:
            say(
                by_id[f"RISK-{row.rule_id.value}"],
                f"{row.rule_id.value} {row.title}: {row.band} risk ({row.rating}/25). {row.why}",
            )
    if not lines:
        say(by_id["RUN"])
    return "\n".join(lines), cited
