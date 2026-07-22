"""`normalize_ha` matches HA's real POST->GET normalization.

`normalize_ha` (an extension of the frozen IR schema in `hassle.ir`) applies HA's
2024.10+ storage normalization: outer singular ``trigger/condition/action`` ->
plural ``triggers/conditions/actions``; ``service:`` -> ``action:`` recursively
(including inside script ``sequence`` and nested actions). Inner ``platform:`` is
preserved (only the outer block key becomes plural — docs/internals/ha-api-notes.md §10.1).

Golden: docs/ha-api-captures/normalize-post-get-pair.json — the real capture pair.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hassle.ir import normalize_ha


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_pairs() -> list[dict[str, object]]:
    path = _repo_root() / "docs" / "ha-api-captures" / "normalize-post-get-pair.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["pairs"]


PAIRS = _load_pairs()


@pytest.mark.parametrize("pair", PAIRS, ids=[str(p["kind"]) for p in PAIRS])
def test_normalize_matches_real_capture(pair: dict[str, object]) -> None:
    sent = pair["sent"]
    expected = dict(pair["read_back"])  # type: ignore[arg-type]
    # HA injects the config `id` (from the URL) on read-back; normalize_ha works
    # on the config body only, so drop the extrinsic id before comparing.
    expected.pop("id", None)
    kind = "script" if pair["kind"] == "script" else "automation"
    assert normalize_ha(sent, kind=kind) == expected


def test_normalize_outer_keys_automation() -> None:
    sent = {
        "alias": "x",
        "trigger": [{"platform": "state", "entity_id": "a"}],
        "condition": [{"condition": "state", "entity_id": "a", "state": "on"}],
        "action": [{"service": "light.turn_on"}],
    }
    out = normalize_ha(sent, kind="automation")
    assert "triggers" in out and "trigger" not in out
    assert "conditions" in out and "condition" not in out
    assert "actions" in out and "action" not in out
    # inner platform: preserved (only outer key pluralized)
    assert out["triggers"][0]["platform"] == "state"
    # service: -> action: inside actions
    assert out["actions"][0]["action"] == "light.turn_on"
    assert "service" not in out["actions"][0]


def test_normalize_recurses_into_nested_actions() -> None:
    sent = {
        "action": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "state", "entity_id": "a", "state": "on"}],
                        "sequence": [{"service": "light.turn_on"}],
                    }
                ],
                "default": [{"service": "light.turn_off"}],
            }
        ],
    }
    out = normalize_ha(sent, kind="automation")
    branch = out["actions"][0]
    assert branch["choose"][0]["sequence"][0]["action"] == "light.turn_on"
    assert branch["default"][0]["action"] == "light.turn_off"


def test_normalize_script_sequence() -> None:
    sent = {"alias": "s", "sequence": [{"service": "input_boolean.toggle"}]}
    out = normalize_ha(sent, kind="script")
    assert out["sequence"][0]["action"] == "input_boolean.toggle"
    assert "sequence" in out  # sequence key unchanged


def test_normalize_is_idempotent_on_plural() -> None:
    already = {
        "alias": "x",
        "triggers": [{"trigger": "state", "entity_id": "a"}],
        "conditions": [],
        "actions": [{"action": "light.turn_on"}],
    }
    assert normalize_ha(already, kind="automation") == already


def test_normalize_does_not_mutate_input() -> None:
    sent = {"action": [{"service": "light.turn_on"}]}
    snapshot = json.dumps(sent, sort_keys=True)
    normalize_ha(sent, kind="automation")
    assert json.dumps(sent, sort_keys=True) == snapshot
