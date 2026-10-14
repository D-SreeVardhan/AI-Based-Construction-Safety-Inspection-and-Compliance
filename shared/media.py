"""Stdlib-only helpers for run media, safe to import in the Space."""

from __future__ import annotations

from pathlib import Path

JPEG_MAGIC = b"\xff\xd8\xff"


def is_jpeg(path: Path) -> bool:
    """True for real JPEGs; the fake pipeline writes text placeholders under ``.jpg`` names."""
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.read(3) == JPEG_MAGIC
