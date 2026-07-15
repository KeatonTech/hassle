"""MILESTONES M21 test 6 -- the config-entry group-helper flow verified
end-to-end against real Home Assistant (M6 pattern, mirrors
`test_m10_template_flow.py`): this suite is the AUTHORITATIVE verification of
the flow shapes documented in docs/ha-api-notes.md §38; any mismatch found
here supersedes the doc, updated in the same PR as the fix.

Does NOT run in unit CI (see `tests/integration/conftest.py`'s ``ha`` fixture
-- skips whole-suite without ``HASSLE_TEST_HA_URL``/``HASSLE_TEST_HA_TOKEN``).
The CI integration job (HA stable + dev) is the authority per §0.

Covers:
- create/read/update/delete a `group_cover` through `DirectBackend` (REST
  `/api/config/config_entries/flow[/{flow_id}]` for create, REST
  `/api/config/config_entries/options/flow[/{flow_id}]` for update, REST
  `DELETE /api/config/config_entries/entry/{entry_id}` for delete).
- the twelve-option menu and the three schema shapes of §38.1 (asserts the
  menu itself, plus one live create per schema shape: base/+all/+type) --
  resolves the sensor-flavor version caveat (§38.3) by asserting against
  whatever the CI HA image's schema actually returns.
- plan/apply integration: compute_plan + apply_plan drive a real create, and
  a second push is a no-op (round-trip byte-stable, I3 applied to options
  bodies).
- CREATE-collision + rollback against the real config-entry apply path.
"""

from __future__ import annotations

from typing import Any

from hassle.backend import DirectBackend
from hassle.compiler.group_helpers import (
    declared_group_helpers,
    group_binary_sensor,
    group_cover,
    group_sensor,
    reset_declared_group_helpers,
)
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan

_BUILDERS = {
    "group_cover": group_cover,
    "group_binary_sensor": group_binary_sensor,
    "group_sensor": group_sensor,
}


def _compiled(domain: str, **kwargs: Any) -> dict[str, Any]:
    """Produce a group-helper config through the real DSL builder (I5's
    spirit: tests exercise compiled IR, not a hand-typed approximation)."""
    reset_declared_group_helpers()
    _BUILDERS[domain](**kwargs)
    (helper,) = declared_group_helpers()
    return helper.to_ha()


def test_group_menu_offers_twelve_flavors_live(ha: DirectBackend) -> None:
    result = ha._run(  # type: ignore[attr-defined]
        ha._client.rest_post("/api/config/config_entries/flow", json={"handler": "group"})
    )
    assert result["type"] == "menu"
    assert result["step_id"] == "user"
    menu_options = set(result["menu_options"])
    expected = {
        "binary_sensor",
        "button",
        "cover",
        "event",
        "fan",
        "light",
        "lock",
        "media_player",
        "notify",
        "sensor",
        "switch",
        "valve",
    }
    assert expected <= menu_options
    # Cancel by not submitting a step -- the flow simply expires server-side
    # (same "opened read-only, never create_entry'd" pattern §38's capture
    # notes describe); nothing further to clean up here.


def test_group_cover_create_read_update_delete_cycle(ha: DirectBackend) -> None:
    identity = ha.create(
        "group_cover",
        _compiled(
            "group_cover",
            name="Entryway Top Probe",
            entities=["cover.entryway_top_probe_member"],
            hide_members=False,
        ),
    )
    assert identity == "entryway_top_probe"

    stored = ha.list_remote("group_cover")[identity]
    assert stored["name"] == "Entryway Top Probe"
    assert stored["entities"] == ["cover.entryway_top_probe_member"]
    assert stored["hide_members"] is False

    entry_id_before = ha.entry_id_for("group_cover", identity)
    assert entry_id_before is not None

    ha.update(
        "group_cover",
        identity,
        _compiled(
            "group_cover",
            name="Entryway Top Probe",
            entities=["cover.entryway_top_probe_member", "cover.another_member"],
            hide_members=True,
        ),
    )
    updated = ha.list_remote("group_cover")[identity]
    assert updated["entities"] == ["cover.entryway_top_probe_member", "cover.another_member"]
    assert updated["hide_members"] is True
    # I2 analog: entry_id unchanged across an options-flow update.
    assert ha.entry_id_for("group_cover", identity) == entry_id_before

    ha.delete("group_cover", identity)
    assert identity not in ha.list_remote("group_cover")


def test_group_binary_sensor_schema_shape_with_all_live(ha: DirectBackend) -> None:
    identity = ha.create(
        "group_binary_sensor",
        _compiled(
            "group_binary_sensor",
            name="Any Door Probe",
            entities=["binary_sensor.any_door_probe_member"],
            hide_members=False,
            all=True,
        ),
    )
    stored = ha.list_remote("group_binary_sensor")[identity]
    assert stored["all"] is True
    ha.delete("group_binary_sensor", identity)


def test_group_sensor_schema_shape_with_type_live(ha: DirectBackend) -> None:
    identity = ha.create(
        "group_sensor",
        _compiled(
            "group_sensor",
            name="Average Temp Probe",
            entities=["sensor.average_temp_probe_member"],
            hide_members=False,
            type="mean",
        ),
    )
    stored = ha.list_remote("group_sensor")[identity]
    assert stored["type"] == "mean"
    ha.delete("group_sensor", identity)


def test_group_helper_plan_apply_create_then_noop_on_repush(ha: DirectBackend) -> None:
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    local_config = _compiled(
        "group_cover",
        name="Zones Plan Probe",
        entities=["cover.zones_plan_probe_member"],
        hide_members=False,
    )
    local = {"group_cover:zones_plan_probe": ("group_cover", local_config)}
    plan = compute_plan(manifest=manifest, local_objects=local, remote_objects={})
    entry = plan.entry_for("group_cover:zones_plan_probe")
    assert entry is not None and entry.action is PlanAction.CREATE

    result = apply_plan(plan, ha, manifest, synced_at="after")
    assert result.succeeded is True
    assert result.manifest is not None
    manifest_entry = result.manifest.objects["group_cover:zones_plan_probe"]
    assert manifest_entry.entry_id is not None

    remote_after = {
        f"group_cover:{identity}": ("group_cover", cfg)
        for identity, cfg in ha.list_remote("group_cover").items()
    }
    plan2 = compute_plan(manifest=result.manifest, local_objects=local, remote_objects=remote_after)
    entry2 = plan2.entry_for("group_cover:zones_plan_probe")
    assert entry2 is not None and entry2.action is PlanAction.NOOP


def test_group_helper_create_collision_aborts_live(ha: DirectBackend) -> None:
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="group_cover:collide_probe",
                kind="group_cover",
                action=PlanAction.CREATE,
                local=_compiled(
                    "group_cover",
                    name="Collide Probe",
                    entities=["cover.collide_probe_member"],
                    hide_members=False,
                ),
            )
        ]
    )
    ha.create(
        "group_cover",
        _compiled(
            "group_cover",
            name="Collide Probe",
            entities=["cover.collide_probe_other_member"],
            hide_members=True,
        ),
    )

    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["group_cover:collide_probe"] is ApplyOutcome.ABORTED
    assert ha.list_remote("group_cover")["collide_probe"]["hide_members"] is True


def test_group_helper_rollback_restores_prior_options_live(ha: DirectBackend) -> None:
    identity = ha.create(
        "group_cover",
        _compiled(
            "group_cover",
            name="Rollback Probe",
            entities=["cover.rollback_probe_member"],
            hide_members=False,
        ),
    )
    before_hash = sha256_hash(ha.list_remote("group_cover")[identity])

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="group_cover:rollback_probe",
                kind="group_cover",
                action=PlanAction.UPDATE,
                local=_compiled(
                    "group_cover",
                    name="Rollback Probe",
                    entities=["cover.rollback_probe_member", "cover.extra_member"],
                    hide_members=True,
                ),
                remote_hash_at_plan=before_hash,
            ),
            # A second entry HA will reject (missing required `type` on
            # group_sensor, §38.1) forces a failure so the first entry's
            # rollback path is exercised. DELIBERATELY a raw, incomplete
            # dict -- no real DSL author could produce it (`group_sensor`
            # requires `type`).
            PlanEntry(
                object_key="group_sensor:this_will_fail",
                kind="group_sensor",
                action=PlanAction.CREATE,
                local={
                    "name": "This Will Fail",
                    "entities": ["sensor.this_will_fail_member"],
                    "hide_members": False,
                },
            ),
        ]
    )
    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["group_cover:rollback_probe"] is ApplyOutcome.ROLLED_BACK

    restored = ha.list_remote("group_cover")[identity]
    assert sha256_hash(restored) == before_hash
