"""Seed HA → pull → compile/validate/round-trip.

Seed a variety of automations/scripts/helpers through HA's own API, then pull
them back through `DirectBackend.list_remote`, decompile to DSL Python, recompile,
and assert the recompiled config is byte-canonically identical to what real HA
stores — compile(decompile(x)) == x proven against a real instance (not a
fixture). The pulled bundle also compiles cleanly and the fetched registry
snapshot drives validation without error.

(This is realized here as round-trip stability against real-HA output: the
decompiled source recompiles to exactly the normalized config HA returned.
Matching the offline *fixture* goldens byte-for-byte is a separate, offline
concern; here the input is whatever this live HA normalizes to, which is the
thing pull must handle.)
"""

from __future__ import annotations

from pathlib import Path

from hassle.backend import DirectBackend
from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, serialize
from hassle.ir.canonical import sha256_hash
from hassle.ir.keys import HELPER_DOMAINS


def _seed(ha: DirectBackend) -> None:
    # Author in the modern plural / `trigger:`/`action:` schema — what the 2026.7
    # UI writes and what the compiler emits — so `compile(decompile(remote))` is
    # byte-exact. (A legacy `platform:`-form remote round-trips only up to the
    # decompiler's documented one-time modernization, docs/ha-api-notes.md §16;
    # that is a separate, offline concern, exercised there.)
    ha.create("input_boolean", {"id": "guest_mode", "name": "Guest Mode"})
    ha.create(
        "automation",
        {
            "id": "hall_light",
            "alias": "Hallway light on motion",
            "mode": "restart",
            "triggers": [{"trigger": "state", "entity_id": "input_boolean.guest_mode", "to": "on"}],
            "conditions": [],
            "actions": [
                {
                    "action": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.guest_mode"},
                },
                {"delay": {"minutes": 5}},
            ],
        },
    )
    ha.create(
        "script",
        {
            "id": "movie_time",
            "alias": "Movie time",
            "sequence": [
                {
                    "action": "input_boolean.toggle",
                    "target": {"entity_id": "input_boolean.guest_mode"},
                }
            ],
        },
    )


def _pull_ir(ha: DirectBackend) -> dict[str, object]:
    objects: dict[str, object] = {}
    for kind in ("automation", "script", *sorted(HELPER_DOMAINS)):
        for identity, config in ha.list_remote(kind).items():
            obj = parse(config, kind=kind, key_hint=identity)
            objects[obj.object_key()] = obj
    return objects


def test_pull_decompiles_compiles_and_roundtrips(ha: DirectBackend, tmp_path: Path) -> None:
    _seed(ha)
    remote_ir = _pull_ir(ha)
    assert {"automation:hall_light", "script:movie_time", "input_boolean:guest_mode"} <= set(
        remote_ir
    )

    # Decompile the whole pulled set to a single Python source file, place it in
    # a bundle, and recompile — exactly what `hassle pull` + `hassle validate` do.
    source = decompile_bundle(remote_ir)  # type: ignore[arg-type]
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "pulled.py").write_text(source, encoding="utf-8")

    result = compile_bundle(bundle)
    compiled = {key: serialize(obj) for key, obj in result.objects.items()}

    # Every pulled object recompiles to the exact config HA stored
    # (compile(decompile(x)) == x, live).
    for key, obj in remote_ir.items():
        assert key in compiled, f"{key} did not recompile"
        assert sha256_hash(compiled[key]) == sha256_hash(serialize(obj)), (
            f"{key} did not round-trip byte-canonically against real HA"
        )


def test_registry_snapshot_fetch_is_usable(ha: DirectBackend) -> None:
    _seed(ha)
    snapshot = ha.fetch_registry_snapshot()
    # The snapshot the CLI commits (DESIGN §9.2): entities + services at minimum.
    assert snapshot.entity_ids(), "expected a non-empty entity registry from live HA"
    assert snapshot.services, "expected get_services schemas from live HA"
    # The helper we created is a real entity now.
    assert any(eid.startswith("input_boolean.") for eid in snapshot.entity_ids())
