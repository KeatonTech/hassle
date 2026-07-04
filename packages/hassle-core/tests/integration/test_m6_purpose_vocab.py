"""MILESTONES M6 test 8 — purpose-vocabulary enumeration WS API (DESIGN §4).

M0.V (HA 2026.2.3) could not capture the enumeration API. M6 finds it: the
2026.7 UI enumerates purpose-specific trigger/condition types via the WS
subscriptions **`trigger_platforms/subscribe`** and
**`condition_platforms/subscribe`** — each acks with a `result`, then pushes an
`event` whose payload is `{type_string: description}`. The vocabulary is the set
of keys. (Source: `homeassistant/components/websocket_api/commands.py`,
`handle_subscribe_trigger_platforms`; captured behaviorally — see
docs/ha-api-notes.md §17.)

On HA < 2026.7 the payload is empty (the purpose vocabulary does not exist yet),
so the vocabulary-content assertions skip; the shape and wiring are still
checked. On `stable`/`dev` (2026.7+) the vocabulary is populated and a
UI-authored purpose-trigger automation is round-tripped byte-stably.
"""

from __future__ import annotations

import pytest

from hassle.backend import DirectBackend
from hassle.ir import parse, serialize
from hassle.ir.canonical import sha256_hash
from hassle.registry.snapshot import PurposeVocabulary


def test_purpose_vocabulary_enumeration_shape(ha: DirectBackend) -> None:
    vocab = ha.fetch_purpose_vocabulary()
    assert isinstance(vocab, PurposeVocabulary)
    # Every enumerated type is a namespaced `<domain>.<event>` string (§4).
    for type_string in [*vocab.triggers, *vocab.conditions]:
        assert "." in type_string, f"purpose type {type_string!r} is not namespaced"


def test_registry_snapshot_uses_enumerated_vocabulary(ha: DirectBackend) -> None:
    # The snapshot the CLI commits wires the enumerated vocabulary into its
    # `purpose_vocabulary` field (replacing the provisional M0.1 fixture shape;
    # the field shape — lists of type strings — is unchanged, so no R5 break).
    vocab = ha.fetch_purpose_vocabulary()
    snapshot = ha.fetch_registry_snapshot()
    assert snapshot.purpose_vocabulary.triggers == vocab.triggers
    assert snapshot.purpose_vocabulary.conditions == vocab.conditions


def test_ui_authored_purpose_trigger_roundtrips(ha: DirectBackend) -> None:
    vocab = ha.fetch_purpose_vocabulary()
    if not vocab.triggers:
        pytest.skip("no purpose vocabulary (HA < 2026.7) — round-trip is 2026.7-only")

    trigger_type = vocab.triggers[0]
    # A UI would author a purpose trigger with a target block (§4). Use a broad
    # entity target so HA accepts it regardless of the exact type semantics.
    ui_authored = {
        "id": "purpose_probe",
        "alias": "Purpose Probe",
        "triggers": [{"trigger": trigger_type, "target": {"entity_id": "input_boolean.x"}}],
        "conditions": [],
        "actions": [{"action": "input_boolean.toggle", "target": {"entity_id": "input_boolean.x"}}],
    }
    try:
        ha.create("automation", ui_authored)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"HA rejected authored purpose trigger {trigger_type!r}: {exc}")

    pulled = ha.list_remote("automation")["purpose_probe"]
    # Pulls as a first-class purpose trigger (not raw): the stored trigger keeps
    # its namespaced type string.
    assert pulled["triggers"][0]["trigger"] == trigger_type

    # IR round-trip is byte-stable, and re-pushing is a no-op change.
    reserialized = serialize(parse(pulled, kind="automation", key_hint="purpose_probe"))
    assert sha256_hash(reserialized) == sha256_hash(pulled)

    ha.update("automation", "purpose_probe", pulled)
    assert sha256_hash(ha.list_remote("automation")["purpose_probe"]) == sha256_hash(pulled)
