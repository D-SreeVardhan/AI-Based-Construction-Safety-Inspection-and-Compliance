from __future__ import annotations

from enum import StrEnum


class CoordinateSpace(StrEnum):
    RAW = "raw"
    ORIENTED = "oriented_canvas"
    UNDISTORTED = "undistorted"
    REFERENCE = "reference"
    MODEL_INPUT = "model_input"
    RELATIVE_PLANE = "relative_plane"


class RuleId(StrEnum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"  # v3: worker down / possible fall
    R7 = "R7"  # v3: worker under a suspended load
    R8 = "R8"  # v3: fire or smoke on site


class Posture(StrEnum):
    UPRIGHT = "upright"
    CROUCHED = "crouched"  # bent, kneeling or squatting: normal work, not a hazard
    LYING = "lying"


class RuleStatus(StrEnum):
    EVALUATED_CLEAR = "evaluated_clear"
    EVALUATED_ALERT = "evaluated_alert"
    NOT_APPLICABLE = "not_applicable"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported_for_feed"


class HelmetState(StrEnum):
    HELMET = "helmet"
    NO_HELMET = "no_helmet"
    UNKNOWN = "unknown"


class VestState(StrEnum):
    VEST = "vest"
    NO_VEST = "no_vest"
    UNKNOWN = "unknown"


class OperatingState(StrEnum):
    ACTIVE = "active"
    STATIONARY = "stationary"
    UNKNOWN = "unknown"


class DistanceBand(StrEnum):
    NEAR = "near"
    CAUTION = "caution"
    CLEAR = "clear"
    INDETERMINATE = "indeterminate"


class ProcessingStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(StrEnum):
    INTAKE = "intake"
    DETECTION = "detection"
    MAPPING_RULES = "mapping_rules"
    RENDER = "render"
    PUBLISH = "publish"


class AlertState(StrEnum):
    """Temporal state of one (rule, subject) pair inside the rule engine (v7 §40.1)."""

    CLEAR = "clear"
    PENDING_ALERT = "pending_alert"
    ALERT = "alert"
    PENDING_RESOLUTION = "pending_resolution"
    COOLDOWN = "cooldown"


PERSON_CLASS = "person"
