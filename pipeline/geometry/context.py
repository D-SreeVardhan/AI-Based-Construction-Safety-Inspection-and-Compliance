"""What R4 and R5 need from the geometry pass, bundled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.config import UncertaintyConfig
from shared.schemas.geometry import GeometryModel

if TYPE_CHECKING:
    from pipeline.geometry.plane import PlaneEnsemble


@dataclass(frozen=True)
class GeometryContext:
    geometry: GeometryModel
    ensemble: PlaneEnsemble | None
    uncertainty: UncertaintyConfig
    # Lowest row of the visible image in reference pixels; boxes reaching it are cut off.
    content_bottom: float
    image_diagonal_px: float

    @property
    def feed_unstable(self) -> bool:
        return self.geometry.status != "ok" and self.geometry.feed_unstable

    @property
    def plane_ready(self) -> bool:
        return self.geometry.status == "ok" and self.ensemble is not None
