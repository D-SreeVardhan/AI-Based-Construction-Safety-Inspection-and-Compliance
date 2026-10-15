"""Leading indicators and decision traces, recorded alongside the rule engine (v3).

The engine decides incidents; this module only watches it:

* `ExposureRecorder` adds up worker-seconds in each hazard condition, keeps the brief
  exposures that never reached the debounce, and the closest worker-machine and
  worker-edge approaches, whether or not they alerted;
* `TraceRecorder` keeps each (rule, subject) pair's recent history so that an incident
  can show *why* it fired: the condition over time, from 2 s before it began to 2 s
  after it ended;
* `evidence_quality` grades how well the video supports an incident, for triage.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pipeline.rules.temporal import (
    Predicate,
    SubjectTimeline,
    Transition,
    TransitionKind,
    predicate_for,
)
from shared.coordinates import DistanceInterval
from shared.enums import AlertState, DistanceBand, RuleId
from shared.schemas.incidents import IncidentTrace, RuleResult, TracePoint
from shared.schemas.insights import (
    AreaExposure,
    BriefExposure,
    ClosestApproach,
    InsightsFile,
    RuleExposure,
    WorkerExposure,
)

# A held condition shorter than this is detector flicker, not an exposure (~4 frames).
BRIEF_MINIMUM_S = 0.25
# Longest frame gap that still counts as continuous exposure (the engine's grace).
MAX_FRAME_GAP_S = 0.25
PRE_ROLL_S = 2.0
POST_ROLL_S = 2.0
TRACE_SPACING_S = 0.2
HISTORY_S = 12.0
TOP_CLOSEST = 12
TOP_WORKERS = 10

Key = tuple[RuleId, str]


def _distance_key(distance: DistanceInterval) -> float:
    return distance.median_wh


@dataclass
class _Pending:
    start_s: float
    last_s: float
    proposal_ids: tuple[str, ...] = ()
    object_id: str | None = None
    closest: DistanceInterval | None = None


@dataclass
class ExposureRecorder:
    observed_s: float = 0.0
    exposure: dict[RuleId, float] = field(default_factory=lambda: defaultdict(float))
    workers: dict[RuleId, set[str]] = field(default_factory=lambda: defaultdict(set))
    by_worker: dict[str, dict[RuleId, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    by_area: dict[tuple[RuleId, str], float] = field(default_factory=lambda: defaultdict(float))
    area_workers: dict[tuple[RuleId, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    brief: list[BriefExposure] = field(default_factory=list)
    closest: dict[tuple[RuleId, str, str], tuple[float, DistanceInterval, DistanceBand | None]] = (
        field(default_factory=dict)
    )
    _pending: dict[Key, _Pending] = field(default_factory=dict)

    def frame(self, dt: float) -> None:
        self.observed_s += dt

    def observe(self, result: RuleResult, time_s: float, dt: float, holds: bool) -> None:
        if result.track_id is None:
            return
        rule, track = result.rule_id, result.track_id
        if holds:
            self.exposure[rule] += dt
            self.workers[rule].add(track)
            self.by_worker[track][rule] += dt
            for proposal_id in result.proposal_ids:
                self.by_area[(rule, proposal_id)] += dt
                self.area_workers[(rule, proposal_id)].add(track)
        if result.distance is not None:
            target = result.object_id or (result.proposal_ids[0] if result.proposal_ids else "")
            key = (rule, track, target)
            best = self.closest.get(key)
            if best is None or _distance_key(result.distance) < _distance_key(best[1]):
                self.closest[key] = (time_s, result.distance, result.relative_band)

    def settle(
        self,
        key: Key,
        timeline: SubjectTimeline,
        transition: Transition | None,
        result: RuleResult | None,
        time_s: float,
    ) -> None:
        """After the timeline moved: start, extend, promote or close a pending exposure."""
        pending = self._pending.get(key)
        if timeline.state is AlertState.PENDING_ALERT:
            since = timeline.pending_since_s
            if pending is not None and abs(pending.start_s - since) > 1e-9:
                self._close(key, pending)  # the old condition lapsed and a new one began
                pending = None
            if pending is None:
                pending = _Pending(start_s=since, last_s=since)
                self._pending[key] = pending
            if result is not None and predicate_holds(result):
                pending.last_s = time_s
                pending.proposal_ids = pending.proposal_ids or result.proposal_ids
                pending.object_id = pending.object_id or result.object_id
                if result.distance is not None and (
                    pending.closest is None
                    or _distance_key(result.distance) < _distance_key(pending.closest)
                ):
                    pending.closest = result.distance
            return
        if pending is None:
            return
        del self._pending[key]
        promoted = transition is not None and transition.kind in (
            TransitionKind.OPENED,
            TransitionKind.REOPENED,
        )
        if not promoted and timeline.state is not AlertState.ALERT:
            self._close(key, pending)

    def close_all(self) -> None:
        for key, pending in list(self._pending.items()):
            self._close(key, pending)
        self._pending.clear()

    def _close(self, key: Key, pending: _Pending) -> None:
        if pending.last_s - pending.start_s < BRIEF_MINIMUM_S:
            return
        rule, track = key
        self.brief.append(
            BriefExposure(
                rule_id=rule,
                canonical_track_id=track,
                start_s=round(pending.start_s, 3),
                end_s=round(pending.last_s, 3),
                proposal_ids=pending.proposal_ids,
                object_id=pending.object_id,
                closest=pending.closest,
            )
        )

    def build(
        self,
        run_id: str,
        incident_counts: Mapping[RuleId, int],
        labels: Mapping[str, str] | None = None,
    ) -> InsightsFile:
        labels = labels or {}
        brief_counts: dict[RuleId, int] = defaultdict(int)
        for exposure in self.brief:
            brief_counts[exposure.rule_id] += 1
        closest = sorted(self.closest.items(), key=lambda item: _distance_key(item[1][1]))
        workers = sorted(self.by_worker.items(), key=lambda item: -sum(item[1].values()))[
            :TOP_WORKERS
        ]
        return InsightsFile(
            run_id=run_id,
            observed_s=round(self.observed_s, 2),
            workers_exposed=sum(
                1 for by_rule in self.by_worker.values() if sum(by_rule.values()) > 0
            ),
            exposure=tuple(
                RuleExposure(
                    rule_id=rule,
                    exposure_s=round(self.exposure.get(rule, 0.0), 2),
                    workers_exposed=len(self.workers.get(rule, ())),
                    brief_exposures=brief_counts.get(rule, 0),
                    confirmed_incidents=incident_counts.get(rule, 0),
                )
                for rule in RuleId
            ),
            brief_exposures=tuple(sorted(self.brief, key=lambda b: (b.start_s, b.rule_id))),
            closest_approaches=tuple(
                ClosestApproach(
                    rule_id=rule,
                    canonical_track_id=track,
                    target_id=target,
                    time_s=round(time_s, 3),
                    distance=distance,
                    band=band,
                )
                for (rule, track, target), (time_s, distance, band) in closest[:TOP_CLOSEST]
            ),
            area_exposure=tuple(
                AreaExposure(
                    rule_id=rule,
                    proposal_id=proposal_id,
                    label=labels.get(proposal_id, ""),
                    exposure_s=round(seconds, 2),
                    workers=len(self.area_workers[(rule, proposal_id)]),
                )
                for (rule, proposal_id), seconds in sorted(
                    self.by_area.items(), key=lambda item: -item[1]
                )
            ),
            top_workers=tuple(
                WorkerExposure(
                    canonical_track_id=track,
                    exposure_s=round(sum(by_rule.values()), 2),
                    by_rule={rule.value: round(s, 2) for rule, s in sorted(by_rule.items())},
                )
                for track, by_rule in workers
            ),
        )


def predicate_holds(result: RuleResult) -> bool:
    return predicate_for(result.status) is Predicate.HOLDS


# ---------------------------------------------------------------------- traces


def trace_point(time_s: float, predicate: Predicate, result: RuleResult | None) -> TracePoint:
    if result is not None and result.distance is not None:
        d = result.distance
        return TracePoint(
            t=round(time_s, 3),
            state=predicate.value,
            value=round(d.median_wh, 3),
            lower=round(d.lower_wh, 3),
            upper=round(d.upper_wh, 3),
        )
    value = None if result is None or result.confidence is None else round(result.confidence, 3)
    return TracePoint(t=round(time_s, 3), state=predicate.value, value=value)


@dataclass
class _Recording:
    points: list[TracePoint]
    stop_at_s: float | None = None


class TraceRecorder:
    def __init__(self) -> None:
        self._history: dict[Key, deque[TracePoint]] = defaultdict(deque)
        self._recordings: dict[Key, dict[int, _Recording]] = defaultdict(dict)
        self.finished: dict[int, list[TracePoint]] = {}

    def add(self, key: Key, point: TracePoint, transition: Transition | None) -> None:
        history = self._history[key]
        history.append(point)
        while history and history[0].t < point.t - HISTORY_S:
            history.popleft()
        recordings = self._recordings[key]
        episode_key = id(transition.episode) if transition is not None else None
        if transition is not None and transition.kind is TransitionKind.OPENED:
            start = transition.episode.first_seen_s - PRE_ROLL_S
            recordings[episode_key] = _Recording([p for p in history if p.t >= start])
        for key_id, recording in list(recordings.items()):
            if key_id == episode_key and transition.kind is TransitionKind.OPENED:
                pass  # already includes this point
            elif recording.stop_at_s is None or point.t <= recording.stop_at_s:
                recording.points.append(point)
            if transition is not None and key_id == episode_key:
                if transition.kind is TransitionKind.RESOLVED:
                    recording.stop_at_s = point.t + POST_ROLL_S
                elif transition.kind is TransitionKind.REOPENED:
                    recording.stop_at_s = None
            if recording.stop_at_s is not None and point.t > recording.stop_at_s:
                self.finished[key_id] = recording.points
                del recordings[key_id]

    def flush(self) -> None:
        for recordings in self._recordings.values():
            for key_id, recording in recordings.items():
                self.finished[key_id] = recording.points
        self._recordings.clear()

    def trace_for(
        self, episode_key: int, *, debounce_s: float, start_s: float, end_s: float
    ) -> IncidentTrace | None:
        points = self.finished.get(episode_key)
        if not points:
            return None
        window = [p for p in points if start_s <= p.t <= end_s]
        seen = sum(1 for p in window if p.state != Predicate.UNKNOWN.value)
        metric = (
            "distance_wh"
            if any(p.lower is not None for p in points)
            else "confidence"
            if any(p.value is not None for p in points)
            else "state"
        )
        return IncidentTrace(
            metric=metric,
            debounce_s=debounce_s,
            observed_fraction=round(seen / len(window), 3) if window else 0.0,
            points=tuple(thin(points)),
        )


def thin(points: Iterable[TracePoint], spacing_s: float = TRACE_SPACING_S) -> list[TracePoint]:
    """Keep every state change and at most one point per `spacing_s` otherwise."""
    kept: list[TracePoint] = []
    last: TracePoint | None = None
    for point in points:
        last = point
        if not kept or point.state != kept[-1].state or point.t - kept[-1].t >= spacing_s:
            kept.append(point)
    if last is not None and kept[-1] is not last:
        kept.append(last)  # the trace always ends where the recording ended
    return kept


def evidence_quality(
    *,
    observed_fraction: float,
    mean_confidence: float | None,
    duration_s: float,
    debounce_s: float,
    confidence_floor: float,
    margin: float,
) -> str:
    """strong / moderate / weak, from what the video actually showed of the episode.

    weak: the subject was visible for under half of the episode, or the model's
    confidence sat within `margin` of the floor. strong: visible for at least 80 %,
    lasting at least twice the debounce, and (when there is one) confident.
    """
    confident = mean_confidence is None or mean_confidence >= confidence_floor + margin
    if observed_fraction < 0.5 or not confident:
        return "weak"
    if observed_fraction >= 0.8 and duration_s >= 2 * debounce_s:
        return "strong"
    return "moderate"
