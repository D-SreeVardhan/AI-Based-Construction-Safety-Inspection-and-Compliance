import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline.render import (
    _C_OK,
    _C_VIOLATION,
    _FONT,
    _draw_scene_shapes,
    _draw_status_panel,
    _fit_text,
    _Letterbox,
    _load_scene_shapes,
    _reencode_h264,
    _to_map_coords,
    render_twin_video,
)


def test_letterbox_maps_portrait_detector_canvas_to_half_pane() -> None:
    detector = _Letterbox.fit(2160, 3840, 1920, 1080)
    pane = _Letterbox.fit(2160, 3840, 960, 1080)

    assert (detector.x_off, detector.w, detector.h) == (656, 608, 1080)
    assert detector.to_other(pane, 656, 0) == (pane.x_off, 0)
    assert detector.to_other(pane, 656 + 608, 1080) == (pane.x_off + pane.w, 1080)


def test_letterbox_maps_landscape_detector_canvas_with_scale_change() -> None:
    detector = _Letterbox.fit(1920, 1080, 1920, 1080)
    pane = _Letterbox.fit(1920, 1080, 960, 1080)

    assert pane.scale == pytest.approx(0.5)
    assert pane.y_off == (1080 - 540) // 2
    assert detector.to_other(pane, 960, 540) == (480, pane.y_off + 270)
    assert detector.to_other(pane, 1920, 1080) == (960, pane.y_off + 540)


def test_map_projection_compresses_far_edge_and_respects_vertical_offset() -> None:
    lb = _Letterbox(1.0, 0, 100, 1000, 800)

    far_left, far_y = _to_map_coords(0, 100, lb=lb, map_w=1000, map_h=1000)
    near_left, near_y = _to_map_coords(0, 900, lb=lb, map_w=1000, map_h=1000)
    far_right, _ = _to_map_coords(1000, 100, lb=lb, map_w=1000, map_h=1000)

    assert far_y == 0
    assert near_y == 1000
    assert far_left > near_left
    assert far_right - far_left < 1000 - 2 * near_left


def test_status_panel_draws_alert_rows_in_violation_colour() -> None:
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    _draw_status_panel(frame, [{"rule_id": "R1", "status": "alert"}])
    panel = frame[150:200, 6:266].reshape(-1, 3)

    def has(colour: tuple[int, int, int]) -> bool:
        return bool(np.any(np.all(np.abs(panel.astype(int) - colour) < 30, axis=1)))

    assert has(_C_VIOLATION)
    assert not has(_C_OK)


def test_fit_text_truncates_to_pixel_width() -> None:
    long = "worker detected without hi-vis vest in proximity of vehicle " * 3
    fitted = _fit_text(long, 300, 0.55)

    assert fitted.endswith("...")
    assert cv2.getTextSize(fitted, _FONT, 0.55, 1)[0][0] <= 300
    assert _fit_text("short", 300, 0.55) == "short"


def test_reencode_keeps_original_when_ffmpeg_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "twin.mp4"
    output.write_bytes(b"original")

    class Failed:
        returncode = 1
        stderr = "boom"

    monkeypatch.setattr("pipeline.render.shutil.which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr("pipeline.render.subprocess.run", lambda *a, **k: Failed())

    _reencode_h264(output, crf=22)

    assert output.read_bytes() == b"original"
    assert not output.with_suffix(".tmp.mp4").exists()


def _write_clip(path: Path, width: int, height: int, frames: int = 6) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (width, height))
    for _ in range(frames):
        writer.write(np.full((height, width, 3), 90, dtype=np.uint8))
    writer.release()


def test_render_twin_video_outputs_side_by_side_frames(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _write_clip(clip, 320, 180)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    obs = {
        "video_time_s": 0.0,
        "canonical_track_id": "shot-0/person-1",
        "object_class": "person",
        "box_reference": {"x1": 300, "y1": 100, "x2": 340, "y2": 300},
        "anchor_reference": {"x": 320, "y": 300},
        "helmet": {"state": "no_helmet"},
        "vest": {"state": "vest"},
    }
    (run_dir / "tracks.jsonl").write_text(json.dumps(obs) + "\n", encoding="utf-8")
    incident = {
        "rule_id": "R1",
        "canonical_track_id": "shot-0/person-1",
        "first_seen_s": 0.0,
        "observation_text": "person-1 without helmet",
    }
    (run_dir / "incidents.json").write_text(json.dumps({"incidents": [incident]}))
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"rule_coverage": [{"rule_id": "R1", "status": "alert"}]})
    )
    output = tmp_path / "twin.mp4"

    render_twin_video(
        input_video=clip,
        run_dir=run_dir,
        output_path=output,
        target_width=640,
        target_height=360,
        output_fps=15.0,
    )

    cap = cv2.VideoCapture(str(output))
    ok, frame = cap.read()
    cap.release()
    assert ok
    assert frame.shape[:2] == (360, 640)
    if shutil.which("ffmpeg"):
        data = output.read_bytes()
        assert 0 <= data.find(b"moov") < data.find(b"mdat")


def test_scene_shapes_are_drawn_and_filtered_by_status(tmp_path: Path) -> None:
    zone = {
        "proposal_id": "restricted_zone-1",
        "proposal_type": "restricted_zone",
        "geometry_type": "polygon",
        "points": [[50, 50], [250, 50], [250, 150], [50, 150]],
    }
    guardrail = {**zone, "proposal_id": "g-1", "proposal_type": "visible_guardrail"}
    scene = tmp_path / "scene.json"
    scene.write_text(json.dumps({"status": "ok", "proposals": [zone, guardrail]}))
    shapes = _load_scene_shapes(tmp_path)
    assert [s["proposal_id"] for s in shapes] == ["restricted_zone-1"]

    canvas = np.zeros((200, 300, 3), dtype=np.uint8)
    _draw_scene_shapes(canvas, shapes, lambda x, y: (int(x), int(y)))
    assert canvas[100, 150].any()
    assert not canvas[190, 10].any()

    scene.write_text(json.dumps({"status": "unavailable", "proposals": [zone]}))
    assert _load_scene_shapes(tmp_path) == []
    scene.unlink()
    assert _load_scene_shapes(tmp_path) == []
