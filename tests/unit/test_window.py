from __future__ import annotations

from pathlib import Path

from app.window import VIDEO_SUFFIXES, is_video_path


def test_video_suffixes() -> None:
    assert is_video_path(Path("clip.mp4"))
    assert not is_video_path(Path("notes.txt"))
    assert ".mp4" in VIDEO_SUFFIXES
