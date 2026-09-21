from __future__ import annotations

from _pytest.capture import CaptureFixture

from app.__main__ import main
from shared.enums import RuleId


def test_status_entrypoint(capsys: CaptureFixture[str]) -> None:
    assert main(["status"]) == 0
    captured = capsys.readouterr()
    assert "construction-safety-twin" in captured.out
    assert "process" in captured.out


def test_rule_ids_are_complete() -> None:
    assert [item.value for item in RuleId] == ["R1", "R2", "R3", "R4", "R5"]
