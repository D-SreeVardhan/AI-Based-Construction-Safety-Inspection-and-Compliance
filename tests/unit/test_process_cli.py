from __future__ import annotations

from pathlib import Path

from _pytest.capture import CaptureFixture

from app.__main__ import main


def test_process_cli_skip_video(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    video = tmp_path / "in.bin"
    video.write_bytes(b"clip")
    out = tmp_path / "out"
    code = main(
        [
            "process",
            str(video),
            "--output-root",
            str(out),
            "--run-id",
            "cli-run",
            "--skip-video",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "run_id=cli-run" in captured.out
    assert (out / "cli-run" / "run_manifest.json").is_file()
