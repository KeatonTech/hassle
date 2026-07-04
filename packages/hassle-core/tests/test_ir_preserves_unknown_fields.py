"""M0 test 2 — invented fields at every nesting level survive the round-trip (I3)."""

from __future__ import annotations

from typing import Any

from hassle.ir import parse, serialize

# Unknown fields planted at every level: top-level, inside a trigger item, inside
# a condition item, inside an action item, inside a nested choose branch, and
# inside the choose default sequence.
CONFIG: dict[str, Any] = {
    "id": "unknown_fields_everywhere",
    "alias": "Invented fields survive",
    "future_top_level_key": {"nested": [1, 2, {"deep": "value"}]},
    "trigger": [
        {
            "platform": "state",
            "entity_id": "binary_sensor.x",
            "invented_trigger_field": {"a": 1, "b": [True, None, "z"]},
        }
    ],
    "condition": [
        {
            "condition": "numeric_state",
            "entity_id": "sensor.y",
            "above": 5,
            "invented_condition_field": ["nested", {"still_here": 42}],
        }
    ],
    "action": [
        {
            "service": "light.turn_on",
            "invented_action_field": {"deep": {"deeper": {"deepest": 3.14}}},
        },
        {
            "choose": [
                {
                    "conditions": [],
                    "sequence": [{"service": "x.y", "unknown_in_branch": 9}],
                    "invented_branch_field": "kept",
                }
            ],
            "default": [{"delay": {"seconds": 1}, "unknown_default_field": "z"}],
        },
    ],
}


def test_ir_preserves_unknown_fields() -> None:
    obj = parse(CONFIG, kind="automation")
    assert serialize(obj) == CONFIG
