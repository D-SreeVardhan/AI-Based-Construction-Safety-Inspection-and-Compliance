from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import CoordinateSpace


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Point2(StrictModel):
    x: float
    y: float
    space: CoordinateSpace


class Box2(StrictModel):
    x1: float
    y1: float
    x2: float
    y2: float
    space: CoordinateSpace

    def width(self) -> float:
        return self.x2 - self.x1

    def height(self) -> float:
        return self.y2 - self.y1


class DistanceInterval(StrictModel):
    lower_wh: float = Field(ge=0.0)
    median_wh: float = Field(ge=0.0)
    upper_wh: float = Field(ge=0.0)
    confidence_level: float = Field(default=0.95, gt=0.0, le=1.0)
