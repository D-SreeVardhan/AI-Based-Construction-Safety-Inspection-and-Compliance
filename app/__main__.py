from __future__ import annotations

import argparse
from pathlib import Path

from app.window import launch_window
from cloud.publish import publish_run
from jobs.pipeline_job import FakePipelineJob


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="safety-twin",
        description="Offline construction-safety video analysis with a 2.5D situational twin.",
    )
    parser.add_argument("--version", action="version", version="0.1.0")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Print scaffold status")
    sub.add_parser("app", help="Open the local Site Twin desk in the browser")
    publish = sub.add_parser("publish", help="Publish an output/<run_id> folder to Supabase")
    publish.add_argument("run_dir", type=Path, help="Run output folder")

    process = sub.add_parser(
        "process",
        help="Run the Week-1 fake pipeline on a video (placeholder twin + R1–R5 coverage)",
    )
    process.add_argument("video", type=Path, help="Path to an input video file")
    process.add_argument(
        "--output-root",
        type=Path,
        default=Path("output"),
        help="Directory for run folders (default: ./output)",
    )
    process.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional fixed run id (default: random)",
    )
    process.add_argument(
        "--skip-video",
        action="store_true",
        help="Skip ffmpeg encode (writes empty safety_twin.mp4) for schema-only smoke tests",
    )

    args = parser.parse_args(argv)

    if args.command in (None, "status"):
        root = Path(__file__).resolve().parents[1]
        print("construction-safety-twin 0.1.0")
        print(f"root={root}")
        print("Commands: status | app | process <video> | publish <run_dir>")
        print("See docs/plan/construction-safety-2.5d-twin-plan-v7.md")
        return 0

    if args.command == "app":
        return launch_window()

    if args.command == "process":
        job = FakePipelineJob(
            args.video,
            output_root=args.output_root,
            run_id=args.run_id,
            skip_video=args.skip_video,
        )
        manifest = job.run()
        print(f"run_id={manifest.run_id}")
        print(f"status={manifest.status.value}")
        print(f"output={job.run_dir}")
        print(f"video={job.run_dir / 'safety_twin.mp4'}")
        print(f"report={job.run_dir / 'report.html'}")
        print(manifest.disclaimer)
        return 0

    if args.command == "publish":
        result = publish_run(args.run_dir)
        print(f"run_id={result['run_id']}")
        print(f"incidents={result['incident_count']}")
        print(f"briefings={result['briefing_count']}")
        print("published=ok")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
