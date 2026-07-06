"""MILESTONES M10 test 1 (integration half) — the config-entry template-helper
flow verified end-to-end against real Home Assistant (M6 pattern: this suite
is the AUTHORITATIVE verification of the flow shapes documented in
docs/ha-api-notes.md §26; any mismatch found here supersedes the doc, updated
in the same PR as the fix).

**This suite is exactly what caught real bugs, across several CI rounds:**

- Round 1 (§26.0): config-entry flow create/step-submission, options-flow,
  and entry removal were originally modeled as WebSocket commands; every
  test here failed identically on both HA `stable` and `dev` with
  `HaApiError: WS command failed: Unknown command.`. Root cause: those three
  operations are REST views (`homeassistant/components/config/
  config_entries.py`), not WS commands (only entry *listing*,
  `config_entries/get`, is genuinely WS).
- Round 2 (§26.6): with the transport fixed, step submission itself 400'd:
  `{"errors": {"base": ["extra keys not allowed @ data['_template_type']",
  "extra keys not allowed @ data['unique_id']"], "set_value": "required key
  not provided"}}`. Three findings: (1) the form step must be EXACTLY the
  domain's own fields, no bookkeeping keys; (2) `template_number`/
  `template_select` require a write-target action sequence (`set_value`/
  `select_option`); (3) `unique_id` is rejected outright -- there is no
  settable unique id, so identity is now derived from `name` (slugified),
  re-freezing MILESTONES M10's identity section.
- Round 3 (§26.7): CREATE worked, but READ-BACK and UPDATE were still wrong
  -- `config_entries/get` never carries an entry's options at all; fixed by
  reading them back via an options-flow's suggested values instead.
- Round 4 (§26.10): the plan-noop test still failed with an int-vs-float
  hash mismatch -- HA's `NumberSelector` always stores `template_number`'s
  `min`/`max`/`step` as floats, so the compiler now coerces to match.
- Round 5 (this file): the round-4 fix landed in the COMPILER
  (`hassle.compiler.template_helpers`), but this suite's local configs were
  hand-written raw dicts with `int` `min`/`max`/`step` that never went
  through the compiler -- so the plan-noop test kept failing with the
  identical diff even after the compiler was fixed. **Every `local`/plan
  config in this file is now produced by actually calling the DSL builders
  (`hassle.compiler.template_helpers.template_number` et al.) and reading
  back `.to_ha()`**, exactly the way the real product's `push`/`plan`
  pipeline compiles a bundle and hands the compiler's output to
  `compute_plan`/`apply_plan` -- never a hand-authored dict. This is also
  more faithful to I5's spirit (tests exercise compiled IR, not hand-typed
  approximations of it); `create`/`update`'s own tests happened to pass
  with raw ints throughout rounds 1-4 only because HA coerces server-side
  regardless of what's submitted, which masked this file never actually
  exercising the compiler at all.

Fixed in `hassle/backend/direct.py` (rounds 1-3) and
`hassle/compiler/template_helpers.py` (round 4); see docs/ha-api-notes.md
§26.0-§26.10 for the full correction history.

Covers:
- create/read/update/delete a `template_number` through `DirectBackend` (REST
  `/api/config/config_entries/flow[/{flow_id}]` for create, REST
  `/api/config/config_entries/options/flow[/{flow_id}]` for update, REST
  `DELETE /api/config/config_entries/entry/{entry_id}` for delete —
  docs/ha-api-notes.md §26.1-26.3).
- the same cycle for the other three template domains (sensor/binary_sensor/
  select), proving the plugin generalizes across the domain (MILESTONES M10
  "scoped to the template domain first ... at minimum" number/sensor/
  binary_sensor/select).
- plan/apply integration: compute_plan + apply_plan drive a real create,
  and a second push is a no-op (round-trip byte-stable, I3 applied to
  options bodies).
- CREATE-collision + rollback against the real config-entry apply path
  (MILESTONES M10 test 4).
"""

from __future__ import annotations

from typing import Any

from hassle.backend import DirectBackend
from hassle.compiler.template_helpers import (
    declared_template_helpers,
    reset_declared_template_helpers,
    template_binary_sensor,
    template_number,
    template_select,
    template_sensor,
)
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan

_SET_VALUE = {"action": "input_number.set_value", "data": {"value": "{{ value }}"}}
_SELECT_OPTION = {"action": "input_select.select_option", "data": {"option": "{{ option }}"}}

_BUILDERS = {
    "template_number": template_number,
    "template_sensor": template_sensor,
    "template_binary_sensor": template_binary_sensor,
    "template_select": template_select,
}


def _compiled(domain: str, **kwargs: Any) -> dict[str, Any]:
    """Produce a template-helper config the way the real product does: through
    the DSL builder, not a hand-authored dict (round 5, docs/ha-api-notes.md
    §26.10 -- a raw `int` `min`/`max`/`step` never exercises the compiler's
    float coercion, and I5's spirit is that tests exercise compiled IR)."""
    reset_declared_template_helpers()
    _BUILDERS[domain](**kwargs)
    (helper,) = declared_template_helpers()
    return helper.to_ha()


def test_template_number_create_read_update_delete_cycle(ha: DirectBackend) -> None:
    identity = ha.create(
        "template_number",
        _compiled(
            "template_number",
            name="Active HVAC Zones",
            state="{{ 3 }}",
            set_value=_SET_VALUE,
            min=0,
            max=8,
            step=1,
        ),
    )
    assert identity == "active_hvac_zones"

    stored = ha.list_remote("template_number")[identity]
    assert stored["name"] == "Active HVAC Zones"
    assert stored["state"] == "{{ 3 }}"
    assert stored["min"] == 0
    assert stored["max"] == 8

    entry_id_before = ha.entry_id_for("template_number", identity)
    assert entry_id_before is not None

    ha.update(
        "template_number",
        identity,
        _compiled(
            "template_number",
            name="Active HVAC Zones",
            state="{{ 5 }}",
            set_value=_SET_VALUE,
            min=0,
            max=8,
            step=1,
        ),
    )
    updated = ha.list_remote("template_number")[identity]
    assert updated["state"] == "{{ 5 }}"
    # I2 analog: entry_id unchanged across an options-flow update.
    assert ha.entry_id_for("template_number", identity) == entry_id_before

    ha.delete("template_number", identity)
    assert identity not in ha.list_remote("template_number")


def _sample_config(domain: str, name: str) -> dict[str, object]:
    if domain == "template_number":
        return _compiled(
            domain, name=name, state="{{ 1 }}", min=0, max=10, step=1, set_value=_SET_VALUE
        )
    if domain == "template_select":
        return _compiled(
            domain,
            name=name,
            state="{{ 1 }}",
            options="{{ ['a', 'b'] }}",
            select_option=_SELECT_OPTION,
        )
    return _compiled(domain, name=name, state="{{ 1 }}")


def test_every_template_domain_supports_full_cycle_live(ha: DirectBackend) -> None:
    for domain in (
        "template_number",
        "template_sensor",
        "template_binary_sensor",
        "template_select",
    ):
        name = f"Probe {domain}"
        identity = f"probe_{domain}"
        created = ha.create(domain, _sample_config(domain, name))
        assert created == identity
        assert identity in ha.list_remote(domain)

        ha.update(domain, identity, _sample_config(domain, name))
        assert identity in ha.list_remote(domain)

        ha.delete(domain, identity)
        assert identity not in ha.list_remote(domain)


def test_template_helper_plan_apply_create_then_noop_on_repush(ha: DirectBackend) -> None:
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    local_config = _compiled(
        "template_number",
        name="Zones Plan Probe",
        state="{{ 2 }}",
        set_value=_SET_VALUE,
        min=0,
        max=8,
        step=1,
    )
    local = {"template_number:zones_plan_probe": ("template_number", local_config)}
    plan = compute_plan(manifest=manifest, local_objects=local, remote_objects={})
    entry = plan.entry_for("template_number:zones_plan_probe")
    assert entry is not None and entry.action is PlanAction.CREATE

    result = apply_plan(plan, ha, manifest, synced_at="after")
    assert result.succeeded is True
    assert result.manifest is not None
    manifest_entry = result.manifest.objects["template_number:zones_plan_probe"]
    assert manifest_entry.entry_id is not None

    # Re-push with the same local config: byte-stable round trip -> noop.
    remote_after = {
        f"template_number:{identity}": ("template_number", cfg)
        for identity, cfg in ha.list_remote("template_number").items()
    }
    plan2 = compute_plan(manifest=result.manifest, local_objects=local, remote_objects=remote_after)
    entry2 = plan2.entry_for("template_number:zones_plan_probe")
    assert entry2 is not None and entry2.action is PlanAction.NOOP


def test_template_helper_create_collision_aborts_live(ha: DirectBackend) -> None:
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="template_number:collide_probe",
                kind="template_number",
                action=PlanAction.CREATE,
                local=_compiled(
                    "template_number",
                    name="Collide Probe",
                    state="{{ 1 }}",
                    set_value=_SET_VALUE,
                    min=0,
                    max=8,
                    step=1,
                ),
            )
        ]
    )
    # Between plan and apply, the identity is taken (simulates a UI create) --
    # same NAME (so the same slugified identity), different state, so the
    # collision is unambiguous.
    ha.create(
        "template_number",
        _compiled(
            "template_number",
            name="Collide Probe",
            state="{{ 9 }}",
            set_value=_SET_VALUE,
            min=0,
            max=8,
            step=1,
        ),
    )

    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["template_number:collide_probe"] is ApplyOutcome.ABORTED
    assert ha.list_remote("template_number")["collide_probe"]["state"] == "{{ 9 }}"


def test_template_helper_rollback_restores_prior_options_live(ha: DirectBackend) -> None:
    identity = ha.create(
        "template_number",
        _compiled(
            "template_number",
            name="Rollback Probe",
            state="{{ 1 }}",
            set_value=_SET_VALUE,
            min=0,
            max=8,
            step=1,
        ),
    )
    entry_id_before = ha.entry_id_for("template_number", identity)
    before_hash = sha256_hash(ha.list_remote("template_number")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="template_number:rollback_probe",
                kind="template_number",
                action=PlanAction.UPDATE,
                local=_compiled(
                    "template_number",
                    name="Rollback Probe",
                    state="{{ 2 }}",
                    set_value=_SET_VALUE,
                    min=0,
                    max=8,
                    step=1,
                ),
                remote_hash_at_plan=before_hash,
            ),
            # A second entry in the same batch that HA will reject (missing
            # the required `set_value` write-target field, §26.6) forces a
            # failure so the first entry's rollback path is exercised. This
            # one is DELIBERATELY a raw, incomplete dict, never compiled --
            # no real DSL author could produce it (`template_number` requires
            # `set_value`); that's exactly why it's used here to force HA's
            # rejection.
            PlanEntry(
                object_key="template_number:this_will_fail",
                kind="template_number",
                action=PlanAction.CREATE,
                local={"name": "This Will Fail", "state": "{{ 1 }}"},
            ),
        ]
    )
    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["template_number:rollback_probe"] is ApplyOutcome.ROLLED_BACK

    restored = ha.list_remote("template_number")[identity]
    assert sha256_hash(restored) == before_hash
    # Rollback-by-recreate is a real recreate at the HA level: document the
    # entry_id-changes caveat (docs/ha-api-notes.md §26.3) rather than assert
    # it is preserved -- the object key and stored options are identical
    # either way, which is what the plan/apply engine actually depends on.
    assert ha.entry_id_for("template_number", identity) is not None
    _ = entry_id_before  # documented, not asserted equal (see caveat above)
