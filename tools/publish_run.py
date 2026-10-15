"""Publish a finished run for the hosted demo, or stage published runs for an image build.

    # upload output/<run> to a Hugging Face dataset (HF_TOKEN with write access)
    uv run python tools/publish_run.py output/sard9-final --repo <user>/safety-twin-runs

    # copy runs into ./runs for `docker build` (what CI does after downloading the dataset)
    uv run python tools/publish_run.py output/sard9-final --stage runs

A run is only published if its bundle validates and its media were privacy-filtered
(`render.privacy: faces`): footage of identifiable workers never leaves the workstation.
The 1080p master video stays behind; the report plays the 720p proxy.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path, PureWindowsPath

from pipeline.output.bundle import validate_bundle
from shared.schemas.bundle import RUN_MANIFEST_FILE, VIDEO_FILE

SKIP = (VIDEO_FILE, "*.partial", "__pycache__")


def check(run_dir: Path) -> list[str]:
    problems = list(validate_bundle(run_dir).problems)
    manifest = json.loads((run_dir / RUN_MANIFEST_FILE).read_text(encoding="utf-8"))
    if manifest.get("diagnostics", {}).get("privacy") != "faces":
        problems.append("media were not privacy-filtered (render.privacy must be 'faces')")
    if not (run_dir / "report.html").is_file():
        problems.append("report.html missing")
    return problems


def redact(manifest: dict) -> dict:
    """Keep the workstation's paths (user name, folders) out of anything published."""
    video = manifest.get("input_video") or {}
    if video.get("path"):
        video["path"] = PureWindowsPath(video["path"]).name  # handles / and \
    diagnostics = manifest.get("diagnostics") or {}
    if "work_dir" in diagnostics:
        diagnostics["work_dir"] = "<local>"
    return manifest


def stage(run_dir: Path, target: Path) -> Path:
    destination = target / run_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(run_dir, destination, ignore=shutil.ignore_patterns(*SKIP))
    manifest_path = destination / RUN_MANIFEST_FILE
    manifest = redact(json.loads(manifest_path.read_text(encoding="utf-8")))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return destination


def upload(run_dir: Path, repo: str, *, private: bool) -> str:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(repo, repo_type="dataset", private=private, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        staged = stage(run_dir, Path(scratch))  # the redacted copy is what leaves the machine
        api.upload_folder(
            repo_id=repo,
            repo_type="dataset",
            folder_path=staged,
            path_in_repo=run_dir.name,
            commit_message=f"Publish run {run_dir.name}",
        )
    return f"https://huggingface.co/datasets/{repo}/tree/main/{run_dir.name}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="output/<run_id> directories")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo", help="Hugging Face dataset, e.g. user/safety-twin-runs")
    target.add_argument("--stage", type=Path, help="copy into this directory instead")
    parser.add_argument("--private", action="store_true", help="create the dataset private")
    args = parser.parse_args(argv)

    failed = False
    for run_dir in args.runs:
        problems = check(run_dir)
        if problems:
            failed = True
            print(f"{run_dir}: not published", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            continue
        if args.stage:
            print(f"{run_dir.name}: staged at {stage(run_dir, args.stage)}")
        else:
            print(f"{run_dir.name}: {upload(run_dir, args.repo, private=args.private)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
