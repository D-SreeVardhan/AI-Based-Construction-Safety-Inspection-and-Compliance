from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="safety-twin",
        description="Offline construction-safety video analysis with a 2.5D situational twin.",
    )
    parser.add_argument("--version", action="version", version="0.1.0")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="Print scaffold status")
    args = parser.parse_args(argv)

    if args.command in (None, "status"):
        root = Path(__file__).resolve().parents[1]
        print("construction-safety-twin 0.1.0 (scaffold)")
        print(f"root={root}")
        print(
            "Pipeline, twin renderer, and desktop UI are not implemented yet. "
            "See docs/plan/construction-safety-2.5d-twin-plan-v7.md"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
