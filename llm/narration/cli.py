"""Commands for the narration experiment (v7 §45.8)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from llm.narration.corpus import (
    DEFAULT_COUNTS,
    MLX_DATA,
    WORK_DIR,
    gate_and_export,
    generate_teacher,
    leakage_report,
    load_scenarios,
    seed_corpus,
)
from llm.narration.evaluate import (
    ARMS,
    EVAL_SPLITS,
    export_blind_sheet,
    promotion_gate,
    run_arm,
    score,
)
from llm.narration.params import assert_parameter_count
from llm.narration.runner import (
    STUDENT_REPO,
    TEACHER_REPO,
    TEACHER_REVISION,
    Generation,
    MlxChat,
)
from llm.narration.schema import Scenario

corpus_app = typer.Typer(no_args_is_help=True, help="Seed, gate and export the narration corpus.")
teacher_app = typer.Typer(no_args_is_help=True, help="Teacher (Qwen2.5-7B) generation.")
student_app = typer.Typer(no_args_is_help=True, help="Student (Qwen2.5-1.5B) LoRA training.")
eval_app = typer.Typer(no_args_is_help=True, help="Four-arm evaluation.")

CONFIG = Path("llm/configs/student-lora.yaml")
ADAPTER = Path("artifacts/adapters/qwen2.5-1.5b-safety-wording")
REPORT = Path("evaluation/results/narration.json")


def _timed(chat: MlxChat):  # noqa: ANN202
    def generate(messages: list[dict[str, str]]) -> tuple[str, float]:
        result: Generation = chat.generate(messages)
        return result.text, result.seconds

    return generate


@corpus_app.command("seed")
def corpus_seed(
    train: int = DEFAULT_COUNTS["train"],
    val: int = DEFAULT_COUNTS["val"],
    test: int = DEFAULT_COUNTS["test"],
) -> None:
    """Freeze scenarios and splits (data/working/llm/)."""
    scenarios = seed_corpus({"train": train, "val": val, "test": test})
    typer.echo(f"scenarios={len(scenarios)} leakage={leakage_report(scenarios)}")


@teacher_app.command("generate")
def teacher_generate(limit: int | None = None) -> None:
    """Greedy, batch-1 teacher outputs for every scenario; safe to interrupt and rerun."""
    scenarios = load_scenarios()
    chat = MlxChat(TEACHER_REPO, TEACHER_REVISION)
    typer.echo(f"teacher revision {chat.resolved_revision}")
    written = generate_teacher(scenarios, _timed(chat), limit=limit)
    typer.echo(f"generated={written}")


@corpus_app.command("gate")
def corpus_gate() -> None:
    """Apply the teacher gates and export MLX training files."""
    report = gate_and_export(load_scenarios())
    typer.echo(json.dumps(report, indent=2))


@student_app.command("train")
def student_train() -> None:
    """Assert the LoRA parameter arithmetic, then run mlx_lm.lora."""
    counts = assert_parameter_count(STUDENT_REPO)
    typer.echo(f"trainable parameters {counts['actual']:,} match the arithmetic")
    if not (MLX_DATA / "train.jsonl").exists():
        raise typer.BadParameter("run `corpus gate` first")
    subprocess.run([sys.executable, "-m", "mlx_lm", "lora", "--config", str(CONFIG)], check=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "param_counts.json").write_text(json.dumps(counts, indent=2) + "\n")


@eval_app.command("run")
def eval_run() -> None:
    """Score every arm on the test split and the blind holdout; write the report."""
    scenarios = load_scenarios()
    chats = {
        "base": MlxChat(STUDENT_REPO, None),
        "lora": MlxChat(STUDENT_REPO, None, adapter_path=ADAPTER),
    }
    generators = {
        "base_zeroshot": _timed(chats["base"]),
        "base_fewshot": _timed(chats["base"]),
        "lora_zeroshot": _timed(chats["lora"]),
    }
    results: dict[str, dict[str, dict[str, object]]] = {}
    outputs: dict[str, dict[str, tuple[str, float]]] = {arm: {} for arm in ARMS}
    for split in EVAL_SPLITS:
        subset: list[Scenario] = [s for s in scenarios if s.split == split]
        for arm in ARMS:
            produced = run_arm(subset, arm, generators)
            outputs[arm].update(produced)
            results.setdefault(arm, {})[split] = score(subset, produced)
            typer.echo(f"{split:8s} {arm:16s} {results[arm][split]['fully_valid_rate']}")

    report = {
        "prompt_version": "narration-v1",
        "models": {
            "teacher": {"repo": TEACHER_REPO, "requested_revision": TEACHER_REVISION},
            "student": {"repo": STUDENT_REPO, "revision": chats["base"].resolved_revision},
            "adapter": str(ADAPTER),
        },
        "counts": {
            s: sum(1 for x in scenarios if x.split == s)
            for s in ("train", "val", "test", "holdout")
        },
        "leakage": leakage_report(scenarios),
        "parameter_counts": json.loads((WORK_DIR / "param_counts.json").read_text())
        if (WORK_DIR / "param_counts.json").exists()
        else None,
        "arms": results,
        "ablation_c": {
            split: {
                "base_zeroshot": results["base_zeroshot"][split],
                "lora_zeroshot": results["lora_zeroshot"][split],
            }
            for split in EVAL_SPLITS
        },
        "promotion_gate": promotion_gate(results["lora_zeroshot"]["holdout"]),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    test_scenarios = [s for s in scenarios if s.split == "test"]
    export_blind_sheet(test_scenarios, outputs, WORK_DIR / "blind")
    typer.echo(f"report -> {REPORT}")
