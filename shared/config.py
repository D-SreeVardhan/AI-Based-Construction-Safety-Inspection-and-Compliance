from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from shared.coordinates import StrictModel


class IntakeConfig(StrictModel):
    target_fps: float
    target_width: int
    target_height: int
    portrait_policy: str
    native_drift_limit_diagonal: float
    provisional_residual_limit_diagonal: float
    geometry_residual_limit_wh: float
    interpolation_max_frames: int


class Stage1Config(StrictModel):
    model_path: str
    image_size: int
    confidence: float
    iou: float
    maximum_detections: int
    device: str


class TrackerConfig(StrictModel):
    type: str
    track_high_threshold: float
    track_low_threshold: float
    new_track_threshold: float
    match_threshold: float
    buffer_seconds: float


class PPEConfig(StrictModel):
    model_path: str
    image_size: int
    batch_size: int
    confidence_floor: float
    minimum_person_height_px: int
    temporal_alpha: float
    minimum_observations: int
    minimum_upright_aspect: float
    classify_every_frames: int = Field(ge=1)
    gemini_minimum_crop_height_px: int
    maximum_gemini_verifications: int = Field(ge=0)


class PoseConfig(StrictModel):
    model_path: str
    image_size: int
    confidence_floor: float
    sample_spacing_seconds: float
    maximum_samples_per_track: int
    maximum_total_samples: int


class RelativePlaneConfig(StrictModel):
    minimum_pairs: int
    minimum_distinct_tracks: int
    minimum_pixel_height: int
    minimum_keypoint_confidence: float
    minimum_standing_probability: float
    maximum_occlusion_fraction: float
    minimum_vertical_inlier_ratio: float
    maximum_reprojection_rms_px: float
    maximum_temporal_horizon_shift_px: float
    minimum_focal_width_ratio: float
    maximum_focal_width_ratio: float
    maximum_condition_number: float
    # A pair is an inlier when its head residual is within this many sigmas.
    inlier_sigma: float
    # Head/foot keypoint noise as a fraction of the worker's pixel height.
    head_sigma_fraction: float
    foot_sigma_fraction: float
    support_expansion_wh: float
    # Largest translation of the background across sampled frames before the feed is
    # treated as moving, in reference pixels.
    maximum_camera_shift_px: float


class UncertaintyConfig(StrictModel):
    bootstrap_samples: int
    confidence_level: float
    minimum_successful_samples: int
    temporal_block_seconds: float
    seed: int


class SceneConfig(StrictModel):
    gemini_model: str
    prompt_version: str
    minimum_keyframes: int
    maximum_keyframes: int
    minimum_support_frames: int
    minimum_support_fraction: float
    zone_cluster_iou: float
    edge_cluster_diagonal_distance: float
    cache_dir: str
    keyframe_image_width: int
    minimum_keyframe_sharpness: float


class RulesConfig(StrictModel):
    ppe_confidence_floor: float
    r1_debounce_seconds: float
    r2_debounce_seconds: float
    r3_debounce_seconds: float
    r4_debounce_seconds: float
    r5_debounce_seconds: float
    resolution_hysteresis_seconds: float
    cooldown_seconds: float
    missing_observation_grace_seconds: float
    r4_near_max_wh: float
    r4_caution_max_wh: float
    r5_edge_max_wh: float
    # Project-defined contact-footprint margin around machinery, in Worker-Heights.
    r4_vehicle_inflation_wh: float
    r4_state_window_seconds: float
    r4_active_speed_wh_s: float
    r4_active_displacement_wh: float
    # Pairs farther than this by point estimate are clear without a bootstrap.
    r4_candidate_max_wh: float


class RenderConfig(StrictModel):
    output_width: int
    output_height: int
    output_fps: float
    pane_width: int
    pane_height: int
    crf: int
    preset: str


class RuntimeConfig(StrictModel):
    processing_checkpoint_frames: int
    progress_events_per_second: int
    minimum_free_disk_gib: int
    maximum_peak_memory_gib: int


class AppConfig(StrictModel):
    schema_version: int = Field(ge=1)
    intake: IntakeConfig
    stage1: Stage1Config
    tracker: TrackerConfig
    ppe: PPEConfig
    pose: PoseConfig
    relative_plane: RelativePlaneConfig
    uncertainty: UncertaintyConfig
    scene: SceneConfig
    rules: RulesConfig
    render: RenderConfig
    runtime: RuntimeConfig


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "defaults.yaml"


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    with config_path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = yaml.safe_load(handle)
    return AppConfig.model_validate(payload)
