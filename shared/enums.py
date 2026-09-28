from __future__ import annotations

from enum import Enum


class CoordinateSpace(str, Enum):
    RAW = "raw"
    ORIENTED = "oriented_canvas"
    UNDISTORTED = "undistorted"
    REFERENCE = "reference"
    MODEL_INPUT = "model_input"
    RELATIVE_PLANE = "relative_plane"


class RuleId(str, Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class RuleStatus(str, Enum):
    EVALUATED_CLEAR = "evaluated_clear"
    EVALUATED_ALERT = "evaluated_alert"
    NOT_APPLICABLE = "not_applicable"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported_for_feed"


class HelmetState(str, Enum):
    HELMET = "helmet"
    NO_HELMET = "no_helmet"
    UNKNOWN = "unknown"


class VestState(str, Enum):
    VEST = "vest"
    NO_VEST = "no_vest"
    UNKNOWN = "unknown"


class OperatingState(str, Enum):
    ACTIVE = "active"
    STATIONARY = "stationary"
    UNKNOWN = "unknown"


class DistanceBand(str, Enum):
    NEAR = "near"
    CAUTION = "caution"
    CLEAR = "clear"
    INDETERMINATE = "indeterminate"


class ProcessingStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(str, Enum):
    INTAKE = "intake"
    DETECTION = "detection"
    MAPPING_RULES = "mapping_rules"
    RENDER = "render"
    PUBLISH = "publish"
