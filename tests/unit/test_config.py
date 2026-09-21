from __future__ import annotations

from shared.config import load_config
from shared.coordinates import Box2
from shared.enums import CoordinateSpace


def test_default_config_loads() -> None:
    config = load_config()
    assert config.schema_version == 1
    assert config.intake.target_width == 1920
    assert config.intake.target_height == 1080
    assert config.render.output_width == 1920
    assert config.uncertainty.seed == 42017
    assert config.rules.r4_near_max_wh < config.rules.r4_caution_max_wh


def test_box_dimensions() -> None:
    box = Box2(x1=10.0, y1=20.0, x2=40.0, y2=80.0, space=CoordinateSpace.RAW)
    assert box.width() == 30.0
    assert box.height() == 60.0
