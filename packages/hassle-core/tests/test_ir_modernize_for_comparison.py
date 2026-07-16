"""``hassle.ir.modernize.modernize_for_comparison``: the bounded, context-free
transform a decompile+recompile cycle is expected to apply -- promoted from
`test_roundtrip_corpus.py`'s `_modernized` test-only helper to production code so
the pull-side self-checks can do a canonical-JSON VALUE comparison instead of a
decompiled-TEXT comparison (which false-positived on context-dependent rendering:
batch-context name-collision dedup suffixes, same-batch script-call rewriting --
neither of which changes the underlying HA value at all).

Scope, exactly two rewrites, nothing else:
- inner trigger discriminator: `platform:` -> `trigger:` (excluding `device`
  triggers, which never decompile to a typed builder).
- `delay:` format: string/numeric -> the dict-of-units form.
"""

from __future__ import annotations

from hassle.ir.canonical import sha256_hash
from hassle.ir.modernize import modernize_for_comparison


def test_platform_modernizes_to_trigger() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "condition": [],
        "action": [],
    }
    out = modernize_for_comparison(config, kind="automation")
    assert out["triggers"] == [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}]


def test_device_trigger_platform_not_modernized() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "trigger": [
            {"platform": "device", "device_id": "d1", "domain": "light", "type": "turn_on"}
        ],
        "condition": [],
        "action": [],
    }
    out = modernize_for_comparison(config, kind="automation")
    assert out["triggers"][0]["platform"] == "device"
    assert "trigger" not in out["triggers"][0]


def test_string_delay_modernizes_to_dict_of_units() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [{"delay": "00:00:05"}],
    }
    out = modernize_for_comparison(config, kind="automation")
    assert out["actions"][0]["delay"] == {"seconds": 5}


def test_numeric_delay_modernizes_to_dict_of_units() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [{"delay": 5}],
    }
    out = modernize_for_comparison(config, kind="automation")
    assert out["actions"][0]["delay"] == {"seconds": 5}


def test_nested_wait_for_trigger_platform_modernized() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {
                "wait_for_trigger": [
                    {"platform": "state", "entity_id": "binary_sensor.x", "to": "on"}
                ]
            }
        ],
    }
    out = modernize_for_comparison(config, kind="automation")
    assert out["actions"][0]["wait_for_trigger"] == [
        {"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}
    ]


def test_already_modern_config_is_unchanged() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "conditions": [],
        "actions": [{"delay": {"seconds": 5}}],
    }
    out = modernize_for_comparison(config, kind="automation")
    assert out == config


def test_idempotent() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "condition": [],
        "action": [{"delay": "00:01:00"}],
    }
    once = modernize_for_comparison(config, kind="automation")
    twice = modernize_for_comparison(once, kind="automation")
    assert once == twice


def test_never_mutates_input() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "condition": [],
        "action": [],
    }
    import copy

    before = copy.deepcopy(config)
    modernize_for_comparison(config, kind="automation")
    assert config == before


def test_hash_equal_for_modernization_only_difference() -> None:
    """The actual comparison the self-checks perform: sha256(modernize(original))
    == sha256(recompiled.to_ha()) -- must be True when the only difference is a
    modernization-eligible schema shape."""
    original = {
        "id": "a1",
        "alias": "A1",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "condition": [],
        "action": [{"delay": "00:00:05"}],
    }
    recompiled_ha = {
        "id": "a1",
        "alias": "A1",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "conditions": [],
        "actions": [{"delay": {"seconds": 5}}],
    }
    assert sha256_hash(modernize_for_comparison(original, kind="automation")) == sha256_hash(
        recompiled_ha
    )


def test_hash_differs_for_a_real_value_change() -> None:
    """Sanity check: a genuine semantic difference (not a modernization) must
    still hash-differ -- this transform must never mask a real bug."""
    original = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [{"repeat": {"for_each": "{{ x }}", "sequence": [{"action": "light.turn_on"}]}}],
    }
    recompiled_ha_wrong = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {
                "repeat": {
                    "for_each": ["{", "{", " ", "x", " ", "}", "}"],
                    "sequence": [{"action": "light.turn_on"}],
                }
            }
        ],
    }
    assert sha256_hash(modernize_for_comparison(original, kind="automation")) != sha256_hash(
        recompiled_ha_wrong
    )
