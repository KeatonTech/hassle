"""MILESTONES M10 test 4 (round-4 CI regression) — `template_number`'s
`min`/`max`/`step` must compile to `float`, matching what real HA's
`NumberSelector` form field always stores (docs/ha-api-notes.md §26.10).

**The CI failure, verbatim** (both HA `stable` and `dev`, run 28811559165,
`test_template_helper_plan_apply_create_then_noop_on_repush`):

```
local  = {..., 'min': 0,   'max': 8,   'step': 1}
remote = {..., 'min': 0.0, 'max': 8.0, 'step': 1.0}
-> hashes differ -> plan says UPDATE instead of NOOP.
```

Root cause (confirmed by reading `homeassistant/helpers/selector.py`):
`NumberSelector.__call__` unconditionally runs the submitted value through
`vol.Coerce(float)` and stores the result -- `template_number`'s `min`/
`max`/`step` fields are `NumberSelector`-typed
(`homeassistant/components/template/config_flow.py`'s `generate_schema`),
so real HA always stores these three as floats, regardless of what was
submitted. Nothing else across the four template domains has a numeric
field HA coerces this way (verified by reading every domain's schema:
sensor/binary_sensor/select have no `NumberSelector` fields at all).

Fixed at compile time (`hassle.compiler.template_helpers.template_number`
coerces `min`/`max`/`step` to `float` via `_coerce_number_field`) so the
compiled local IR is byte-identical to the remote config either way --
plan comparison stays a plain hash equality with no comparison-time special
case (DESIGN §8.2). `FakeBackend` models the same coercion on create/update
so a unit-level plan/apply test catches this class of bug without a live HA.

The I3 round-trip side (a pulled `template_number` has floats; recompiling
decompiled source reproduces them) is covered by the existing
`test_decompile_template_helpers.py::
test_decompile_recompile_round_trip_is_byte_stable_for_options_body`, which
exercises the fixture bundle (now float-valued after this fix) through a
real decompile -> write -> recompile cycle.
"""

from __future__ import annotations

from pathlib import Path

from hassle.backend.fake import FakeBackend
from hassle.compiler.bundle import compile_bundle
from hassle.compiler.template_helpers import (
    declared_template_helpers,
    reset_declared_template_helpers,
    template_number,
)
from hassle.ir.canonical import sha256_hash
from hassle.sync import Manifest, PlanAction
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_helper_declarations"
    / "bundle"
)

_SET_VALUE = {"action": "input_number.set_value", "data": {"value": "{{ value }}"}}


def setup_function() -> None:
    reset_declared_template_helpers()


def test_template_number_compiles_min_max_step_as_float() -> None:
    # Direct builder-level check: an author writing the natural int literals
    # gets floats in the compiled IR, matching what HA's NumberSelector
    # always stores.
    template_number(name="Zones", state="{{ 1 }}", set_value=_SET_VALUE, min=0, max=8, step=1)
    (helper,) = declared_template_helpers()
    body = helper.to_ha()
    assert body["min"] == 0.0 and isinstance(body["min"], float)
    assert body["max"] == 8.0 and isinstance(body["max"], float)
    assert body["step"] == 1.0 and isinstance(body["step"], float)


def test_template_number_omitted_min_max_step_stay_omitted() -> None:
    template_number(name="Zones", state="{{ 1 }}", set_value=_SET_VALUE)
    (helper,) = declared_template_helpers()
    body = helper.to_ha()
    assert "min" not in body
    assert "max" not in body
    assert "step" not in body


def test_template_number_already_float_input_stays_float() -> None:
    # An author who already wrote floats must not see any different
    # behavior -- the coercion is idempotent.
    template_number(name="Zones", state="{{ 1 }}", set_value=_SET_VALUE, min=0.5, max=8.5, step=0.1)
    (helper,) = declared_template_helpers()
    body = helper.to_ha()
    assert body["min"] == 0.5
    assert body["max"] == 8.5
    assert body["step"] == 0.1


def test_fixture_bundle_compiles_min_max_step_as_float() -> None:
    result = compile_bundle(FIXTURE)
    body = result.objects["template_number:active_hvac_zones"].to_ha()
    assert body["min"] == 0.0 and isinstance(body["min"], float)
    assert body["max"] == 8.0 and isinstance(body["max"], float)
    assert body["step"] == 1.0 and isinstance(body["step"], float)


def test_fakebackend_create_stores_min_max_step_as_float_like_real_ha() -> None:
    # Regression for the round-4 CI finding at the FakeBackend level: create
    # via the simulated flow must store floats, exactly like real HA's
    # NumberSelector coercion, so this class of bug is unit-testable without
    # a live HA.
    backend = FakeBackend()
    identity = backend.create(
        "template_number",
        {
            "name": "Zones",
            "state": "{{ 1 }}",
            "set_value": _SET_VALUE,
            "min": 0,
            "max": 8,
            "step": 1,
        },
    )
    stored = backend.list_remote("template_number")[identity]
    assert stored["min"] == 0.0 and isinstance(stored["min"], float)
    assert stored["max"] == 8.0 and isinstance(stored["max"], float)
    assert stored["step"] == 1.0 and isinstance(stored["step"], float)


def test_fakebackend_update_stores_min_max_step_as_float_like_real_ha() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number",
        {
            "name": "Zones",
            "state": "{{ 1 }}",
            "set_value": _SET_VALUE,
            "min": 0,
            "max": 8,
            "step": 1,
        },
    )
    backend.update(
        "template_number",
        identity,
        {"state": "{{ 2 }}", "set_value": _SET_VALUE, "min": 1, "max": 9, "step": 2},
    )
    stored = backend.list_remote("template_number")[identity]
    assert stored["min"] == 1.0 and isinstance(stored["min"], float)
    assert stored["max"] == 9.0 and isinstance(stored["max"], float)
    assert stored["step"] == 2.0 and isinstance(stored["step"], float)


def test_plan_apply_create_then_noop_on_repush_with_fakebackend() -> None:
    # Regression for the exact CI failure: a DSL author writing the natural
    # int literals (`min=0, max=8, step=1`) must plan NOOP against the
    # FakeBackend remote after a create + repush, exactly mirroring
    # test_m10_template_flow.py::test_template_helper_plan_apply_create_then_noop_on_repush.
    # `local_config` is the COMPILED IR (via the real builder, not a
    # hand-written dict) -- otherwise this test wouldn't exercise the
    # compile-time coercion fix at all.
    template_number(
        name="Zones Plan Probe", state="{{ 2 }}", set_value=_SET_VALUE, min=0, max=8, step=1
    )
    (helper,) = declared_template_helpers()
    local_config = helper.to_ha()
    assert isinstance(local_config["min"], float)  # sanity: the fix is in effect

    backend = FakeBackend()
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    local = {"template_number:zones_plan_probe": ("template_number", local_config)}
    plan = compute_plan(manifest=manifest, local_objects=local, remote_objects={})
    entry = plan.entry_for("template_number:zones_plan_probe")
    assert entry is not None and entry.action is PlanAction.CREATE

    result = apply_plan(plan, backend, manifest, synced_at="after")
    assert result.succeeded is True
    assert result.manifest is not None

    remote_after = {
        f"template_number:{identity}": ("template_number", cfg)
        for identity, cfg in backend.list_remote("template_number").items()
    }
    plan2 = compute_plan(manifest=result.manifest, local_objects=local, remote_objects=remote_after)
    entry2 = plan2.entry_for("template_number:zones_plan_probe")
    assert entry2 is not None and entry2.action is PlanAction.NOOP


def test_canonical_hash_is_insensitive_to_key_order_int_vs_float_is_the_real_bug() -> None:
    # Coordinator's key-order concern: canonical hashing already sorts keys
    # (hassle.ir.canonical.canonical_json, sort_keys=True) -- confirm that
    # holds, and confirm the ACTUAL discriminator is int vs float, not order.
    a = {"name": "Zones", "state": "{{ 2 }}", "min": 0, "max": 8, "step": 1}
    b = {"state": "{{ 2 }}", "min": 0, "max": 8, "step": 1, "name": "Zones"}
    assert sha256_hash(a) == sha256_hash(b)  # key order: never the issue

    c = {"name": "Zones", "state": "{{ 2 }}", "min": 0.0, "max": 8.0, "step": 1.0}
    assert sha256_hash(a) != sha256_hash(c)  # int vs float: the real issue
