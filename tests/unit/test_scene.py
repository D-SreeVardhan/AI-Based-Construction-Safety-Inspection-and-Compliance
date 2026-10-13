from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline.intake import FrameSampler
from pipeline.rules.zone_rules import evaluate_r3
from pipeline.scene import bootstrap_scene
from pipeline.scene.geometry import (
    chamfer_distance,
    mask_iou,
    polygon_self_intersects,
    polyline_self_intersects,
    rasterise,
    signed_distance_to_polygon,
)
from pipeline.scene.keyframes import candidate_indices
from pipeline.scene.proposals import SceneParseError, parse_response
from shared.config import AppConfig, load_config
from shared.coordinates import Box2, Point2
from shared.enums import CoordinateSpace, RuleId, RuleStatus
from shared.schemas.scene import SceneModel, SceneProposal
from shared.schemas.tracks import Pass1TrackObservation

W, H = 1920, 1080
SQUARE = [(100.0, 100.0), (500.0, 100.0), (500.0, 500.0), (100.0, 500.0)]


def _pts(points: list[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"y": y, "x": x} for x, y in points]


def _zone(x1: int = 100, y1: int = 100, x2: int = 500, y2: int = 500) -> dict[str, object]:
    return {
        "proposal_type": "restricted_zone",
        "geometry_type": "polygon",
        "points": _pts([(x1, y1), (x2, y1), (x2, y2), (x1, y2)]),
        "rationale": "cones",
    }


def _edge(drop: object = True) -> dict[str, object]:
    return {
        "proposal_type": "open_edge",
        "geometry_type": "polyline",
        "points": _pts([(100, 800), (900, 800)]),
        "visible_drop_or_open_side": drop,
        "protection_visibility": "sufficient",
        "protection_state": "unguarded_or_inadequate",
    }


def _reply(frames: int, proposals: list[dict[str, object]]) -> str:
    return json.dumps(
        {"frames": [{"keyframe_index": i, "proposals": proposals} for i in range(frames)]}
    )


# --- geometry ---------------------------------------------------------------


def test_self_intersection_detection() -> None:
    assert not polygon_self_intersects(SQUARE)
    assert polygon_self_intersects([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert polyline_self_intersects([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert not polyline_self_intersects([(0, 0), (5, 5), (10, 0)])


def test_signed_distance_sign_convention() -> None:
    assert signed_distance_to_polygon((300, 300), SQUARE) == pytest.approx(200.0)
    assert signed_distance_to_polygon((600, 300), SQUARE) == pytest.approx(-100.0)


def test_mask_iou_and_chamfer() -> None:
    a = rasterise(SQUARE, W, H, 0.25)
    shifted = rasterise([(x + 200, y) for x, y in SQUARE], W, H, 0.25)
    assert mask_iou(a, a) == pytest.approx(1.0)
    assert mask_iou(a, shifted) == pytest.approx(1 / 3, abs=0.02)
    line = [(0.0, 0.0), (100.0, 0.0)]
    assert chamfer_distance(line, line) == pytest.approx(0.0)
    assert chamfer_distance(line, [(0.0, 10.0), (100.0, 10.0)]) == pytest.approx(10.0, abs=0.5)


# --- response validation ----------------------------------------------------


def test_parse_scales_normalised_coordinates() -> None:
    accepted, rejected = parse_response(
        _reply(1, [_zone(0, 0, 500, 500)]), keyframe_count=1, width=W, height=H
    )
    assert rejected == []
    assert accepted[0].points[2] == pytest.approx((960.0, 540.0))


def test_parse_rejects_bad_proposals_without_failing_the_reply() -> None:
    bad_range = _zone()
    bad_range["points"] = [{"y": 5000, "x": 1}, {"y": 2, "x": 3}, {"y": 9, "x": 9}]
    bowtie = _zone()
    bowtie["points"] = _pts([(0, 0), (500, 500), (500, 0), (0, 500)])
    tiny = _zone(10, 10, 12, 12)
    edge_without_flag = _edge(drop="maybe")
    wrong_geometry = _zone()
    wrong_geometry["geometry_type"] = "polyline"
    unknown = {**_zone(), "proposal_type": "swimming_pool"}
    reply = _reply(
        1, [bad_range, bowtie, tiny, edge_without_flag, wrong_geometry, unknown, _zone()]
    )
    accepted, rejected = parse_response(reply, keyframe_count=1, width=W, height=H)
    assert len(accepted) == 1
    assert len(rejected) == 6


def test_parse_converts_box_to_polygon() -> None:
    box = {
        "proposal_type": "restricted_zone",
        "geometry_type": "box",
        "points": _pts([(100, 100), (400, 300)]),
    }
    accepted, _ = parse_response(_reply(1, [box]), keyframe_count=1, width=W, height=H)
    assert accepted[0].geometry_type == "polygon"
    assert len(accepted[0].points) == 4


def test_parse_rejects_unknown_and_duplicate_keyframes() -> None:
    reply = json.dumps(
        {
            "frames": [
                {"keyframe_index": 0, "proposals": []},
                {"keyframe_index": 0, "proposals": [_zone()]},
                {"keyframe_index": 9, "proposals": [_zone()]},
            ]
        }
    )
    accepted, rejected = parse_response(reply, keyframe_count=2, width=W, height=H)
    assert accepted == []
    assert len(rejected) == 2


@pytest.mark.parametrize("raw", ["not json", "[]", '{"frames": "x"}', "{}"])
def test_parse_raises_on_unusable_reply(raw: str) -> None:
    with pytest.raises(SceneParseError):
        parse_response(raw, keyframe_count=1, width=W, height=H)


# --- keyframe selection -----------------------------------------------------


def test_candidate_indices_cover_the_clip_in_order() -> None:
    picks = candidate_indices([], total_samples=120, count=8)
    assert picks == sorted(picks)
    assert len(picks) == 8
    assert picks[0] < 15 and picks[-1] >= 105
    assert candidate_indices([], total_samples=0, count=8) == []


# --- bootstrap --------------------------------------------------------------


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 180))
    rng = np.random.default_rng(0)
    for _ in range(300):
        writer.write(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))
    writer.release()
    return path


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    base = load_config()
    scene = base.scene.model_copy(update={"cache_dir": str(tmp_path / "scene-cache")})
    return base.model_copy(update={"scene": scene})


def _boot(
    clip: Path, config: AppConfig, requester: object, api_key: str = "k"
) -> tuple[SceneModel, str]:
    return bootstrap_scene(
        sampler=FrameSampler(clip, target_fps=15.0, target_width=W, target_height=H),
        observations=[],
        video_sha256="a" * 64,
        detector_id="det",
        config=config,
        api_key=api_key,
        requester=requester,  # type: ignore[arg-type]
    )


def test_bootstrap_builds_consensus_and_caches(clip: Path, config: AppConfig) -> None:
    calls: list[int] = []

    def requester(_key: str, _model: str, jpegs: object) -> str:
        calls.append(len(jpegs))  # type: ignore[arg-type]
        return _reply(len(jpegs), [_zone(), _edge()])  # type: ignore[arg-type]

    scene, status = _boot(clip, config, requester)
    assert status == "miss" and scene.status == "ok"
    zone = scene.of_type("restricted_zone")
    edge = scene.of_type("open_edge")
    assert len(zone) == 1 and len(edge) == 1
    assert zone[0].agreement_score == pytest.approx(1.0)
    assert zone[0].heuristic and zone[0].proposal_id == "restricted_zone-1"
    assert edge[0].visible_drop_or_open_side is True
    assert edge[0].protection_state == "unguarded_or_inadequate"

    again, status2 = _boot(clip, config, requester, api_key="")
    assert status2 == "hit"
    assert again == scene
    assert len(calls) == 1


def test_bootstrap_drops_clusters_without_enough_keyframe_support(
    clip: Path, config: AppConfig
) -> None:
    def requester(_key: str, _model: str, jpegs: object) -> str:
        n = len(jpegs)  # type: ignore[arg-type]
        frames = [
            {
                "keyframe_index": i,
                "proposals": [_zone(), _zone(700, 700, 900, 900)] if i < 2 else [_zone()],
            }
            for i in range(n)
        ]
        return json.dumps({"frames": frames})

    scene, _ = _boot(clip, config, requester)
    assert len(scene.of_type("restricted_zone")) == 1
    assert any("support" in reason for reason in scene.rejected)


def test_bootstrap_without_key_is_disabled(clip: Path, config: AppConfig) -> None:
    scene, status = _boot(clip, config, None, api_key="")
    assert status == "disabled"
    assert scene.status == "unavailable" and scene.status_reason == "gemini_api_key_missing"


def test_bootstrap_unusable_reply_is_unavailable_and_not_cached(
    clip: Path, config: AppConfig
) -> None:
    scene, status = _boot(clip, config, lambda *_: "garbage")
    assert status == "unavailable" and "unusable_gemini_reply" in (scene.status_reason or "")
    assert not Path(config.scene.cache_dir).exists()


def test_bootstrap_unreadable_video_is_unavailable(tmp_path: Path, config: AppConfig) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    scene, status = _boot(broken, config, lambda *_: "")
    assert status == "unavailable" and "keyframe_read_failed" in (scene.status_reason or "")


# --- R3 ---------------------------------------------------------------------


def _zone_proposal() -> SceneProposal:
    return SceneProposal(
        proposal_id="restricted_zone-1",
        proposal_type="restricted_zone",
        geometry_type="polygon",
        points=tuple(SQUARE),
        source="gemini_consensus",
        agreement_score=0.9,
        supporting_keyframes=(0, 1, 2, 3, 4, 5, 6),
        eligible_keyframes=8,
    )


def _scene(*proposals: SceneProposal) -> SceneModel:
    return SceneModel(cache_key="k", status="ok", proposals=proposals)


def _track(anchor_x: float, anchor_y: float, seconds: float = 3.0) -> list[Pass1TrackObservation]:
    out = []
    for i in range(int(seconds * 10) + 1):
        out.append(
            Pass1TrackObservation(
                shot_id="s0",
                frame_index=i,
                video_time_s=i * 0.1,
                track_id=1,
                canonical_track_id="s0/person-1",
                object_class="person",
                box_reference=Box2(
                    x1=anchor_x - 20,
                    y1=anchor_y - 100,
                    x2=anchor_x + 20,
                    y2=anchor_y,
                    space=CoordinateSpace.REFERENCE,
                ),
                anchor_reference=Point2(x=anchor_x, y=anchor_y, space=CoordinateSpace.REFERENCE),
            )
        )
    return out


def _r3(scene: SceneModel | None, tracks: dict[str, list[Pass1TrackObservation]]):  # noqa: ANN202
    return evaluate_r3(
        run_id="r",
        shot_id="s0",
        catalogue_sha256="c",
        scene=scene,
        person_tracks=tracks,
        debounce_s=1.0,
    )


def test_r3_alerts_when_worker_stays_inside_zone() -> None:
    incidents, cov = _r3(_scene(_zone_proposal()), {"s0/person-1": _track(300, 400)})
    assert cov.status == RuleStatus.EVALUATED_ALERT and cov.rule_id == RuleId.R3
    assert len(incidents) == 1
    assert incidents[0].proposal_ids == ("restricted_zone-1",)


def test_r3_clear_when_worker_outside() -> None:
    incidents, cov = _r3(_scene(_zone_proposal()), {"s0/person-1": _track(900, 900)})
    assert incidents == [] and cov.status == RuleStatus.EVALUATED_CLEAR


def test_r3_brief_entry_is_debounced() -> None:
    incidents, cov = _r3(_scene(_zone_proposal()), {"s0/person-1": _track(300, 400, 0.5)})
    assert incidents == [] and cov.status == RuleStatus.EVALUATED_CLEAR


def test_r3_boundary_straddle_is_inconclusive_not_alert() -> None:
    incidents, cov = _r3(_scene(_zone_proposal()), {"s0/person-1": _track(502, 300)})
    assert incidents == []
    assert cov.status == RuleStatus.INCONCLUSIVE and cov.reason_code == "zone_boundary_uncertain"


def test_r3_scene_states() -> None:
    tracks = {"s0/person-1": _track(300, 400)}
    _, cov = _r3(None, tracks)
    assert cov.status == RuleStatus.INCONCLUSIVE
    assert cov.reason_code == "restricted_zone_scene_state_unavailable"
    unavailable = SceneModel(cache_key="k", status="unavailable", status_reason="x")
    assert _r3(unavailable, tracks)[1].status == RuleStatus.INCONCLUSIVE
    assert _r3(_scene(), tracks)[1].reason_code == "no_supported_restricted_zone"
    assert _r3(_scene(_zone_proposal()), {})[1].status == RuleStatus.NOT_APPLICABLE
