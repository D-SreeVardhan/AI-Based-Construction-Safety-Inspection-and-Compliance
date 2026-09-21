from __future__ import annotations

from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def launch_window() -> int:
    # Tk is optional on headless CI; imported only when the desktop command runs.
    from app.desktop import run_desktop

    return run_desktop()
