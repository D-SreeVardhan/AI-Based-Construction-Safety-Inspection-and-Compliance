from __future__ import annotations

from pathlib import Path

from jobs.pipeline_job import _sha256_file, fingerprint_input


def test_fingerprint_full_for_small_files(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"tiny-input")
    digest, complete = fingerprint_input(path, full_below_bytes=64)
    assert complete is True
    assert digest == _sha256_file(path)


def test_fingerprint_samples_large_files(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"HEAD" + b"x" * 24 + b"TAIL")
    digest, complete = fingerprint_input(path, full_below_bytes=8, sample_bytes=4)
    assert complete is False
    assert digest != _sha256_file(path)
    again, _ = fingerprint_input(path, full_below_bytes=8, sample_bytes=4)
    assert again == digest
