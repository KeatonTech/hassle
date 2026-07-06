"""MILESTONES M10 test 1 (integration half) — the config-entry template-helper
flow verified end-to-end against real Home Assistant (M6 pattern: this suite
is the AUTHORITATIVE verification of the flow shapes documented, source-
informed, in docs/ha-api-notes.md §26; any mismatch found here supersedes
that doc, updated in the same PR as the fix).

Covers:
- create/read/update/delete a `template_number` through `DirectBackend`
  (the real `config_entries/flow` / `config_entries/options/flow` /
  `config_entries/remove` commands, docs/ha-api-notes.md §26.1-26.3).
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

from hassle.backend import DirectBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan


def test_template_number_create_read_update_delete_cycle(ha: DirectBackend) -> None:
    identity = ha.create(
        "template_number",
        {
            "unique_id": "active_hvac_zones",
            "name": "Active HVAC Zones",
            "state": "{{ 3 }}",
            "min": 0,
            "max": 8,
            "step": 1,
        },
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
        {
            "unique_id": "active_hvac_zones",
            "name": "Active HVAC Zones",
            "state": "{{ 5 }}",
            "min": 0,
            "max": 8,
            "step": 1,
        },
    )
    updated = ha.list_remote("template_number")[identity]
    assert updated["state"] == "{{ 5 }}"
    # I2 analog: entry_id unchanged across an options-flow update.
    assert ha.entry_id_for("template_number", identity) == entry_id_before

    ha.delete("template_number", identity)
    assert identity not in ha.list_remote("template_number")


def _sample_config(domain: str, identity: str) -> dict[str, object]:
    base = {"unique_id": identity, "name": identity, "state": "{{ 1 }}"}
    if domain == "template_number":
        base.update({"min": 0, "max": 10, "step": 1})
    elif domain == "template_select":
        base["options"] = "{{ ['a', 'b'] }}"
    return base


def test_every_template_domain_supports_full_cycle_live(ha: DirectBackend) -> None:
    for domain in (
        "template_number",
        "template_sensor",
        "template_binary_sensor",
        "template_select",
    ):
        identity = f"probe_{domain}"
        created = ha.create(domain, _sample_config(domain, identity))
        assert created == identity
        assert identity in ha.list_remote(domain)

        ha.update(domain, identity, _sample_config(domain, identity))
        assert identity in ha.list_remote(domain)

        ha.delete(domain, identity)
        assert identity not in ha.list_remote(domain)


def test_template_helper_plan_apply_create_then_noop_on_repush(ha: DirectBackend) -> None:
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    local_config = {
        "unique_id": "zones_plan_probe",
        "name": "Zones Plan Probe",
        "state": "{{ 2 }}",
        "min": 0,
        "max": 8,
        "step": 1,
    }
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
                local={
                    "unique_id": "collide_probe",
                    "name": "Mine",
                    "state": "{{ 1 }}",
                    "min": 0,
                    "max": 8,
                    "step": 1,
                },
            )
        ]
    )
    # Between plan and apply, the identity is taken (simulates a UI create).
    ha.create(
        "template_number",
        {
            "unique_id": "collide_probe",
            "name": "Created in UI",
            "state": "{{ 9 }}",
            "min": 0,
            "max": 8,
            "step": 1,
        },
    )

    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["template_number:collide_probe"] is ApplyOutcome.ABORTED
    assert ha.list_remote("template_number")["collide_probe"]["name"] == "Created in UI"


def test_template_helper_rollback_restores_prior_options_live(ha: DirectBackend) -> None:
    identity = ha.create(
        "template_number",
        {
            "unique_id": "rollback_probe",
            "name": "Original",
            "state": "{{ 1 }}",
            "min": 0,
            "max": 8,
            "step": 1,
        },
    )
    entry_id_before = ha.entry_id_for("template_number", identity)
    before_hash = sha256_hash(ha.list_remote("template_number")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="template_number:rollback_probe",
                kind="template_number",
                action=PlanAction.UPDATE,
                local={
                    "unique_id": "rollback_probe",
                    "name": "Updated",
                    "state": "{{ 2 }}",
                    "min": 0,
                    "max": 8,
                    "step": 1,
                },
                remote_hash_at_plan=before_hash,
            ),
            # A second, deliberately invalid entry in the same batch forces a
            # failure so the first entry's rollback path is exercised.
            PlanEntry(
                object_key="template_number:this_will_fail___",
                kind="template_number",
                action=PlanAction.CREATE,
                local={"unique_id": "", "name": "", "state": "{{ this is not valid jinja"},
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
