"""Real-model regression test on 8 s of SARD 9 (needs the GPU stack, models and the clip).

    uv run pytest tests/gpu -m gpu

Skipped automatically in CI (no CUDA, no clip). Catches what unit tests cannot: a broken
detector or PPE load, a stride/interpolation regression, a PPE slowdown, a pass-two crash
on real tracks.
"""

from __future__ import annotations

import itertools
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gpu
torch = pytest.importorskip("torch")
pytest.importorskip("ultralytics")

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "data/external/sard/9.mp4"
FRAMES = 120  # 8 s at 15 fps

if not torch.cuda.is_available() or not CLIP.is_file():
    pytest.skip("needs CUDA and data/external/sard/9.mp4", allow_module_level=True)


def test_pass_one_and_two_on_real_footage(tmp_path: Path) -> None:
    from jobs.pass2 import run_pass2
    from pipeline.cache.pass1_store import Pass1Store
    from pipeline.intake.frames import FrameSource
    from pipeline.intake.geometry_gate import CameraMode
    from pipeline.mapping.frame_context import FrameContextBuilder
    from pipeline.mapping.stitching import StitchedStore, stitch
    from pipeline.output.summaries import TrackSummaryBuilder
    from pipeline.rules.engine import RuleEngine
    from pipeline.vision.detector import Stage1Detector, resolve_weights
    from pipeline.vision.pass1 import VisionPass
    from pipeline.vision.ppe_model import PPEClassifier
    from pipeline.vision.tracker import ByteTrackAdapter
    from shared.config import load_config
    from shared.schemas.scene import SceneCache

    config = load_config()
    weights, _ = resolve_weights(config.stage1, ROOT)
    detector = Stage1Detector(config.stage1, weights)
    every = config.stage1.detect_every_frames
    tracker = ByteTrackAdapter(
        config.tracker,
        config.intake.target_fps / every,
        sorted(set(detector.classes.values()) - set(config.stage1.evidence_classes)),
    )
    ppe = PPEClassifier(
        ROOT / config.ppe.model_path, detector.device, batch_size=config.ppe.batch_size
    )
    source = FrameSource(CLIP, target_fps=config.intake.target_fps, canvas_size=(1920, 1080))
    frames = list(itertools.islice(iter(source), FRAMES))
    store = Pass1Store(tmp_path / "pass1.sqlite")
    started = time.perf_counter()
    summary = VisionPass(detector, tracker, config, camera_mode=CameraMode.FIXED, ppe=ppe).run(
        frames, store
    )
    elapsed = time.perf_counter() - started

    assert summary.frames == FRAMES
    rows = list(store.frames_with_observations())
    people = [o for _, obs in rows for o in obs if o.object_class == "person"]
    assert len(people) > 5 * FRAMES  # SARD 9 is a crowded site
    if every > 1:
        assert any(o.interpolated for o in people) and any(not o.interpolated for o in people)
    assert sum(o.helmet is not None for o in people) > 0.5 * len(people)
    # PPE once took ~0.34 s per classified frame from shape churn; keep it honest.
    assert summary.ppe_s < 0.1 * FRAMES, f"PPE {summary.ppe_s:.1f}s for {FRAMES} frames"
    assert elapsed < 60, f"pass one took {elapsed:.0f}s for {FRAMES} frames"

    result = stitch(store.frames_with_observations())
    assert result.tracks_after <= result.tracks_before
    scene = SceneCache(cache_key="none", video_sha256="x", shot_proposals={})
    builder = FrameContextBuilder(
        run_id="gpu-test",
        scene=scene,
        geometry_supported=False,
        ppe_available=True,
        machinery_classes=config.stage1.machinery_classes,
        rules=config.rules,
    )
    pass2 = run_pass2(
        StitchedStore(store, result.mapping),
        builder,
        RuleEngine(run_id="gpu-test", config=config.rules),
        TrackSummaryBuilder("gpu-test"),
    )
    assert pass2.insights is not None
    assert [e.rule_id.value for e in pass2.rules.coverage] == ["R1", "R2", "R3", "R4", "R5"]
