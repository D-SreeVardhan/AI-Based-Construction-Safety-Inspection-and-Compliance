from __future__ import annotations

from pathlib import Path

from evaluation.inventory import load_demo_inventory
from shared.enums import RuleId


def test_inventory_covers_all_rules() -> None:
    inventory = load_demo_inventory()
    assert set(inventory.rules) == set(RuleId)
    held = set(inventory.splits.heldout)
    dev = set(inventory.splits.development)
    assert not (held & dev)
    assert "source-yard-truck" in held
    for entry in inventory.rules.values():
        assert entry.clip_id in inventory.clips
        if not entry.licensed_real_positive:
            assert entry.use_for_precision_recall is False
        start, end = entry.expected_interval_s
        assert end > start


def test_synthetic_fixtures_exist() -> None:
    inventory = load_demo_inventory()
    root = Path(__file__).resolve().parents[2]
    for rule_id in (RuleId.R3, RuleId.R5):
        clip = inventory.clips[inventory.rules[rule_id].clip_id]
        assert (root / clip.path).is_file()
