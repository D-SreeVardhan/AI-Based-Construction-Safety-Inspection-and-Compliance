"""Trainable-parameter arithmetic for the student LoRA (v7 §14.5).

The closed-form count from the model's config must equal the count MLX reports for the
adapter it actually builds; training refuses to start on a mismatch.
"""

from __future__ import annotations

import json
from pathlib import Path

from llm.narration.runner import resolve_snapshot

try:
    from mlx.utils import tree_flatten
    from mlx_lm import load
    from mlx_lm.tuner.utils import linear_to_lora_layers
except ImportError:  # pragma: no cover - needs the train extra on Apple silicon
    tree_flatten = load = linear_to_lora_layers = None  # type: ignore[assignment]

# mlx-lm adapts every attention and MLP projection unless ``keys`` is given; the plan's
# 311,296-parameter budget is q_proj and v_proj only.
LORA = {
    "rank": 8,
    "scale": 16.0,
    "dropout": 0.05,
    "keys": ["self_attn.q_proj", "self_attn.v_proj"],
}
LORA_LAYERS = 8


def expected_trainable(config_path: Path, rank: int = 8, layers: int = 8) -> dict[str, int]:
    """``r x (d_in + d_out)`` summed over q_proj and v_proj in the top ``layers`` blocks."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    hidden = int(config["hidden_size"])
    head_dim = hidden // int(config["num_attention_heads"])
    kv_out = int(config["num_key_value_heads"]) * head_dim
    q = rank * (hidden + hidden)
    v = rank * (hidden + kv_out)
    return {
        "q_proj_per_block": q,
        "v_proj_per_block": v,
        "per_block": q + v,
        "blocks": layers,
        "total": (q + v) * layers,
        "base_parameters": int(config.get("num_parameters", 0)),
    }


def actual_trainable(repo: str) -> int:
    """Trainable parameters of the model after MLX attaches the LoRA layers."""
    if load is None:
        raise ImportError("mlx-lm is required (uv sync --extra train, Apple silicon only)")
    path, _ = resolve_snapshot(repo, None)
    model, _ = load(str(path))
    model.freeze()
    linear_to_lora_layers(model, LORA_LAYERS, dict(LORA))
    return sum(array.size for _, array in tree_flatten(model.trainable_parameters()))


def assert_parameter_count(repo: str) -> dict[str, int]:
    path, _ = resolve_snapshot(repo, None)
    expected = expected_trainable(path / "config.json", int(LORA["rank"]), LORA_LAYERS)
    actual = actual_trainable(repo)
    if actual != expected["total"]:
        raise RuntimeError(
            f"LoRA trainable parameters {actual:,} differ from the §14.5 arithmetic "
            f"{expected['total']:,}"
        )
    return {**expected, "actual": actual}
