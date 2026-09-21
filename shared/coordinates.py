from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.enums import CoordinateSpace


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _reject_non_finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("coordinates must be finite")
    return value


class Point2(StrictModel):
    x: float
    y: float
    space: CoordinateSpace

    @field_validator("x", "y")
    @classmethod
    def _finite(cls, value: float) -> float:
        return _reject_non_finite(value)


class Box2(StrictModel):
    x1: float
    y1: float
    x2: float
    y2: float
    space: CoordinateSpace

    @field_validator("x1", "y1", "x2", "y2")
    @classmethod
    def _finite(cls, value: float) -> float:
        return _reject_non_finite(value)

    @model_validator(mode="after")
    def _ordered(self) -> Box2:
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError("box corners must not be inverted")
        return self

    def width(self) -> float:
        return self.x2 - self.x1

    def height(self) -> float:
        return self.y2 - self.y1


class DistanceInterval(StrictModel):
    lower_wh: float = Field(ge=0.0)
    median_wh: float = Field(ge=0.0)
    upper_wh: float = Field(ge=0.0)
    confidence_level: float = Field(default=0.95, gt=0.0, le=1.0)
    successful_bootstraps: int = Field(default=0, ge=0)
    total_bootstraps: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _ordered_band(self) -> DistanceInterval:
        if not (self.lower_wh <= self.median_wh <= self.upper_wh):
            raise ValueError("distance interval must be ordered lower <= median <= upper")
        if self.successful_bootstraps > self.total_bootstraps:
            raise ValueError("successful_bootstraps cannot exceed total_bootstraps")
        return self
