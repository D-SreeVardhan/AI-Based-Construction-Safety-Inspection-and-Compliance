"""R6 — possible worker down (v3).

A worker lying on the ground is the visible aftermath of a fall, a collapse or a strike,
and the first minutes matter. Posture comes from pass one: a box far wider than it is
tall, confirmed by pose keypoints (the body axis near horizontal) when the pose model is
available, so workers bent over rebar or kneeling are `crouched`, not `lying`. The
engine's debounce (3 s by default) separates someone lying still from someone briefly
reaching down.
"""

from __future__ import annotations

from pipeline.rules.base import ResultFactory
from shared.enums import Posture, RuleId, RuleStatus
from shared.schemas.frame import FrameContext
from shared.schemas.incidents import RuleResult

ALERT_REASON = "worker_lying_on_ground"


class R6WorkerDown:
    rule_id = RuleId.R6

    def __init__(self, *, basis: str) -> None:
        self.basis = basis

    def evaluate(self, context: FrameContext) -> list[RuleResult]:
        make = ResultFactory(self.rule_id, self.basis, context)
        if not context.capabilities.person_detection:
            return make.frame(RuleStatus.UNSUPPORTED, "person_detection_unavailable")
        if not context.capabilities.posture:
            return make.frame(RuleStatus.UNSUPPORTED, "posture_unavailable")
        workers = context.workers()
        if not workers:
            return make.frame(RuleStatus.NOT_APPLICABLE, "no_person_tracks")
        results = []
        for worker in workers:
            track_id = worker.canonical_track_id
            if worker.posture is None:
                # Interpolated or unjudgeable frame: pauses the debounce, never clears it.
                results.append(
                    make.make(RuleStatus.INCONCLUSIVE, "posture_unknown", track_id=track_id)
                )
            elif worker.posture == Posture.LYING.value:
                results.append(
                    make.make(RuleStatus.EVALUATED_ALERT, ALERT_REASON, track_id=track_id)
                )
            else:
                results.append(
                    make.make(
                        RuleStatus.EVALUATED_CLEAR, f"worker_{worker.posture}", track_id=track_id
                    )
                )
        return results
