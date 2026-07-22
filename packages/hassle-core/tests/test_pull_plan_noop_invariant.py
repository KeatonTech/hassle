"""Pull -> plan-noop invariant (docs/internals/ha-api-notes.md §23): a fresh pull
followed immediately by a plan, with zero edits on either side, must never
show a `conflict` or a plain (non-modernization) `update` for an untouched
object -- only `noop`, or an `update` that is schema-only modernization
(DESIGN §8.2).

This module covers the two facts diagnosed at the IR/backend layer:

- FACT 1 (verification, not a bug): the decompiler/IR never materializes a
  default for an absent decorator kwarg (`mode`, `description`, ...) --
  `test_mode_less_automation_hash_stable` / `test_mode_less_script_hash_stable`.
- FACT 2 (real bug, fixed): `FakeBackend` used to leak a caller-supplied
  script `id` into the stored body, even though real HA's script config
  read-back never has `id` in the body (docs/ha-api-captures/rest-ws-core.json
  `script_read_normalized`) -- `test_fake_backend_script_id_not_leaked_into_body`
  et al.

The end-to-end CLI-level invariant (whole corpus, real `hassle pull`/`hassle
plan`) lives in `packages/hassle-cli/tests/test_pull_plan_noop_invariant_cli.py`.
"""

from __future__ import annotations

from hassle.backend.fake import FakeBackend
from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.canonical import sha256_hash
from hassle.ir.models import parse

# ---------------------------------------------------------------------------
# FACT 1: decompile -> recompile of a mode-less stored object is
# canonical-hash-identical to the original (no materialized defaults).
# ---------------------------------------------------------------------------


def _roundtrip_hash(object_key: str, kind: str, body: dict[str, object]) -> tuple[str, str]:
    """Return (stored_hash, roundtripped_hash) for `body` parsed as `kind`,
    decompiled, recompiled, and hashed again.

    `body` must already be in HA's modern plural-schema stored form (`triggers`/
    `conditions`/`actions`, `action:` not `service:`) -- this helper isolates
    FACT 1 (decompiler default-materialization) from the unrelated, already
    separately-tested legacy-schema modernization case (DESIGN §8.2;
    `test_modernization_labeling.py`), so a schema-only
    difference here would be a false positive for a bug this test isn't
    about.
    """
    identity = object_key.partition(":")[2]
    obj = parse(body, kind=kind, key_hint=identity)
    stored_hash = sha256_hash(obj.to_ha())

    source = decompile_bundle({object_key: obj})

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "bundle.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp_root)
        recompiled = result.objects[object_key]
        roundtripped_hash = sha256_hash(recompiled.to_ha())

    return stored_hash, roundtripped_hash


def test_mode_less_automation_hash_stable() -> None:
    """A stored automation with NO `mode` key at all must round-trip
    (decompile -> recompile) to a canonical-hash-identical body -- `mode`
    must never be materialized as `"single"` (or any other default)."""
    body = {
        "id": "mode_less_auto",
        "alias": "Mode Less Automation",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.y"}}],
    }
    stored_hash, roundtripped_hash = _roundtrip_hash(
        "automation:mode_less_auto", "automation", body
    )
    assert roundtripped_hash == stored_hash


def test_mode_less_script_hash_stable() -> None:
    """Same invariant for a mode-less stored script."""
    body = {
        "alias": "Mode Less Script",
        "sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.y"}}],
    }
    stored_hash, roundtripped_hash = _roundtrip_hash("script:mode_less_script", "script", body)
    assert roundtripped_hash == stored_hash


def test_mode_less_automation_to_ha_omits_mode() -> None:
    """Narrower unit check backing FACT 1: `to_ha()` on a parsed mode-less
    automation must not contain a `mode` key at all (not even `None`) --
    `exclude_unset=True` means an unset field is omitted, not null-valued."""
    body = {
        "id": "a1",
        "alias": "A",
        "trigger": [],
        "condition": [],
        "action": [],
    }
    obj = parse(body, kind="automation", key_hint="a1")
    assert "mode" not in obj.to_ha()


def test_mode_less_script_to_ha_omits_mode() -> None:
    body = {"alias": "S", "sequence": []}
    obj = parse(body, kind="script", key_hint="s1")
    assert "mode" not in obj.to_ha()


# ---------------------------------------------------------------------------
# FACT 2: FakeBackend must never leak a script's extrinsic id into its
# stored body -- real HA's script config read-back never has `id` (ground
# truth: docs/ha-api-captures/rest-ws-core.json `script_read_normalized`).
# ---------------------------------------------------------------------------


def test_fake_backend_script_id_not_leaked_into_body_on_create() -> None:
    backend = FakeBackend()
    identity = backend.create("script", {"id": "my_script", "alias": "My Script", "sequence": []})
    stored = backend.list_remote("script")[identity]
    assert "id" not in stored


def test_fake_backend_script_id_not_leaked_into_body_on_update() -> None:
    backend = FakeBackend()
    identity = backend.create("script", {"alias": "My Script", "sequence": []})
    backend.update(
        "script", identity, {"id": identity, "alias": "My Script Updated", "sequence": []}
    )
    stored = backend.list_remote("script")[identity]
    assert "id" not in stored


def test_fake_backend_script_local_remote_hash_match_when_untouched() -> None:
    """The actual plan-noop invariant, isolated to the backend layer: a
    script seeded (with a caller-supplied `id`, the natural mistake) and
    never edited must hash-match between a freshly compiled local object
    (no `id`, `ScriptConfig` has no such field) and the remote body
    `FakeBackend` returns."""
    backend = FakeBackend()
    identity = backend.create(
        "script",
        {
            "id": "hall_notify",
            "alias": "Hall Notify",
            "sequence": [{"service": "notify.notify", "data": {"message": "hi"}}],
        },
    )
    remote_body = backend.list_remote("script")[identity]

    # Simulate "freshly compiled local" == parse the remote body (as pull
    # would decompile then recompile it) and take its to_ha().
    local_obj = parse(remote_body, kind="script", key_hint=identity)
    assert sha256_hash(local_obj.to_ha()) == sha256_hash(remote_body)


def test_fake_backend_helper_id_still_injected() -> None:
    """Guard against an overcorrection: helpers legitimately DO carry `id`
    in the stored body (intrinsic `HelperConfig.id`), unlike scripts -- the
    fix must not strip it there too."""
    backend = FakeBackend()
    identity = backend.create("input_boolean", {"name": "Guest Mode"})
    stored = backend.list_remote("input_boolean")[identity]
    assert stored.get("id") == identity


def test_fake_backend_automation_id_still_present() -> None:
    """And automations legitimately carry `id` in the body too (intrinsic
    `AutomationConfig.id`) -- passed through verbatim, never stripped."""
    backend = FakeBackend()
    identity = backend.create(
        "automation", {"id": "a1", "alias": "A", "trigger": [], "condition": [], "action": []}
    )
    stored = backend.list_remote("automation")[identity]
    assert stored.get("id") == identity
