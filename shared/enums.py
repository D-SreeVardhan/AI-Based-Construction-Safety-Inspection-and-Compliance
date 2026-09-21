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
