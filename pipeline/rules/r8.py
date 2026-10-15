"""R8 — possible fire or smoke on site (v3).

Hot works, generators and stored fuel make fire a real site risk, and smoke is often the
first visible sign. The subject is the detected fire or smoke itself (its track), not a
worker, so one fire gives one incident however many people are nearby. Confidence must
clear `min_confidence` and the engine's debounce (2 s): orange safety netting, dust and
low sun are easy to mistake for fire, and the incident is graded and reviewable.
"""

from __future__ import annotations

from pipeline.rules.base import ResultFactory
from shared.enums import RuleId, RuleStatus
from shared.schemas.frame import FrameContext
from shared.schemas.incidents import RuleResult

ALERT_REASON = "fire_or_smoke_visible"
CLASSES = ("fire", "smoke")


class R8FireSmoke:
    rule_id = RuleId.R8

    def __init__(self, *, basis: str, min_confidence: float) -> None:
        self.basis = basis
        self.min_confidence = min_confidence

    def evaluate(self, context: FrameContext) -> list[RuleResult]:
        make = ResultFactory(self.rule_id, self.basis, context)
        if not any(c in context.capabilities.hazard_classes for c in CLASSES):
            return make.frame(RuleStatus.UNSUPPORTED, "fire_smoke_detection_unavailable")
        sightings = [h for h in context.hazards if h.class_name in CLASSES]
        if not sightings:
            return make.frame(RuleStatus.EVALUATED_CLEAR, "no_fire_or_smoke_observed")
        results = []
        for hazard in sightings:
            confident = (hazard.confidence or 0.0) >= self.min_confidence
            results.append(
                make.make(
                    RuleStatus.EVALUATED_ALERT if confident else RuleStatus.INCONCLUSIVE,
                    ALERT_REASON if confident else "fire_smoke_confidence_low",
                    track_id=hazard.object_id,
                    object_id=hazard.object_id,
                    confidence=hazard.confidence,
                )
            )
        return results
