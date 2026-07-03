"""M0 test 3 — canonical hashing: key-order-invariant, semantics-sensitive (R8)."""

from __future__ import annotations

import copy
import json
from typing import Any

from hassle_core.ir import canonical_json, sha256_hash

BASE: dict[str, Any] = {
    "id": "hash_me",
    "alias": "Canonical hashing",
    "mode": "restart",
    "trigger": [
        {"platform": "state", "entity_id": "binary_sensor.a", "to": "on"},
        {"platform": "numeric_state", "entity_id": "sensor.b", "above": 10},
    ],
    "action": [
        {"service": "light.turn_on", "data": {"brightness_pct": 60, "transition": 2}},
        {"delay": {"seconds": 5}},
    ],
}


def _reverse_key_order(obj: Any) -> Any:
    """Structurally identical, but every dict's keys are reinserted in reverse."""
    if isinstance(obj, dict):
        return {k: _reverse_key_order(obj[k]) for k in reversed(list(obj.keys()))}
    if isinstance(obj, list):
        return [_reverse_key_order(v) for v in obj]
    return obj


def test_key_order_does_not_change_hash() -> None:
    shuffled = _reverse_key_order(BASE)
    # Prove the reordering is real at the naive-serialization level...
    assert json.dumps(shuffled) != json.dumps(BASE)
    # ...yet canonicalization erases it.
    assert canonical_json(shuffled) == canonical_json(BASE)
    assert sha256_hash(shuffled) == sha256_hash(BASE)


def test_hash_has_sha256_prefix() -> None:
    digest = sha256_hash(BASE)
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_semantic_value_change_changes_hash() -> None:
    changed = copy.deepcopy(BASE)
    changed["action"][0]["data"]["brightness_pct"] = 61
    assert sha256_hash(changed) != sha256_hash(BASE)


def test_list_reorder_changes_hash() -> None:
    reordered = copy.deepcopy(BASE)
    reordered["trigger"].reverse()
    # List order is semantically significant, so the hash must differ.
    assert sha256_hash(reordered) != sha256_hash(BASE)
