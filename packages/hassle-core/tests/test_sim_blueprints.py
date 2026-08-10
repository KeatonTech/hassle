"""The simulator runs blueprint-based automations (DESIGN §5.8 + §10.1).

A `@blueprint_automation` compiles to only ``{"use_blueprint": {path, input}}``,
so before this the simulator saw an automation with no triggers and no actions:
inert, and every behavior a bundle routed through a blueprint was untestable.
The simulator now expands a `use_blueprint` instance against the bundle-local
blueprint source at ``<bundle>/blueprints/automation/<path>`` and simulates the
resulting concrete config.

Two things this must not disturb, both pinned below:

- **push/plan payloads never change** -- expansion is a simulator-side read of
  the same IR; ``to_ha()`` still emits exactly ``use_blueprint``.
- **an absent blueprint file behaves exactly as before** -- opaque and inert,
  today's behavior, so a bundle that references a blueprint HA holds (an
  imported community blueprint) is unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _dsl_cases import dsl_dir
from _sim_helpers import build_sim, compile_source

from hassle.blueprints import MissingBlueprintInputError
from hassle.testing import Simulator, simulate
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"
FIXTURE_BUNDLE = dsl_dir() / "blueprint_local_expansion" / "bundle"

ROOM_SWITCH = """
    blueprint:
      name: Room switch controls
      domain: automation
      input:
        switch_entity:
          name: Switch
        room_light:
          name: Room light
        dim_step_pct:
          name: Dim step
          default: 10
    mode: restart
    triggers:
      - trigger: state
        entity_id: !input switch_entity
        to: "up"
        id: up
      - trigger: state
        entity_id: !input switch_entity
        to: "down"
        id: down
    actions:
      - choose:
          - conditions:
              - condition: trigger
                id: up
            sequence:
              - action: light.turn_on
                target:
                  entity_id: !input room_light
                data:
                  brightness_step_pct: !input dim_step_pct
          - conditions:
              - condition: trigger
                id: down
            sequence:
              - action: light.turn_off
                target:
                  entity_id: !input room_light
    """

INSTANCE = """
    from hassle import blueprint_automation

    blueprint_automation(
        id="office_switch",
        alias="Office switch",
        use_blueprint="local/room-switch-controls.yaml",
        inputs={
            "switch_entity": "sensor.office_paddle",
            "room_light": "light.office",
        },
    )
    """


def _room_switch_sim(tmp_path: Path) -> Simulator:
    return build_sim(
        tmp_path,
        INSTANCE,
        blueprints={"local/room-switch-controls.yaml": ROOM_SWITCH},
    )


# ---------------------------------------------------------------------------
# (a) a blueprint instance triggers and runs its expanded actions
# ---------------------------------------------------------------------------


def test_blueprint_instance_triggers_and_runs_expanded_actions(tmp_path: Path) -> None:
    sim = _room_switch_sim(tmp_path)
    sim.state_change("sensor.office_paddle", "idle", "up")
    sim.assert_called("light.turn_on", entity_id="light.office", brightness_step_pct=10)


def test_blueprint_instance_is_reachable_by_object_key(tmp_path: Path) -> None:
    sim = _room_switch_sim(tmp_path)
    assert sim.automation_keys() == ["automation:office_switch"]


def test_expanded_instance_honors_the_blueprints_own_options(tmp_path: Path) -> None:
    # `mode: restart` comes from the blueprint body, not the instance.
    sim = build_sim(
        tmp_path,
        INSTANCE,
        blueprints={
            "local/room-switch-controls.yaml": """
            blueprint:
              name: Slow
              domain: automation
              input:
                switch_entity:
                room_light:
                dim_step_pct:
                  default: 10
            mode: restart
            triggers:
              - trigger: state
                entity_id: !input switch_entity
                to: "up"
            actions:
              - delay:
                  minutes: 5
              - action: light.turn_on
                target:
                  entity_id: !input room_light
            """
        },
    )
    sim.state_change("sensor.office_paddle", "idle", "up")
    sim.advance(minutes=4)
    # A second trigger restarts the run: the first delay never completes.
    sim.state_change("sensor.office_paddle", "idle", "up")
    sim.advance(minutes=4)
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=1)
    sim.assert_called("light.turn_on", entity_id="light.office", times=1)


# ---------------------------------------------------------------------------
# (b) `choose` branching on `trigger.id`
# ---------------------------------------------------------------------------


def test_choose_branches_on_trigger_id(tmp_path: Path) -> None:
    sim = _room_switch_sim(tmp_path)
    sim.state_change("sensor.office_paddle", "idle", "down")
    sim.assert_called("light.turn_off", entity_id="light.office")
    sim.assert_not_called("light.turn_on")


def test_choose_picks_the_other_branch_for_the_other_trigger(tmp_path: Path) -> None:
    sim = _room_switch_sim(tmp_path)
    sim.state_change("sensor.office_paddle", "idle", "up")
    sim.assert_called("light.turn_on", entity_id="light.office")
    sim.assert_not_called("light.turn_off")


# ---------------------------------------------------------------------------
# (c) a template reading `trigger.to_state.attributes.<attr>`
# ---------------------------------------------------------------------------


def test_template_reads_trigger_to_state_attributes(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        INSTANCE,
        blueprints={
            "local/room-switch-controls.yaml": """
            blueprint:
              name: Attribute reader
              domain: automation
              input:
                switch_entity:
                room_light:
                dim_step_pct:
                  default: 10
            triggers:
              - trigger: state
                entity_id: !input switch_entity
                to: "up"
                id: up
            actions:
              - action: notify.persistent_notification
                data:
                  message: >-
                    {{ trigger.id }}/{{ trigger.platform }}/{{ trigger.entity_id }}/{{
                    trigger.from_state.state }}->{{ trigger.to_state.state }}/{{
                    trigger.to_state.attributes.event_type }}
            """
        },
    )
    sim.state_change("sensor.office_paddle", "idle", "up", {"event_type": "single_press"})
    sim.assert_called(
        "notify.persistent_notification",
        message="up/state/sensor.office_paddle/idle->up/single_press",
    )


# ---------------------------------------------------------------------------
# (d) a missing required input fails with a what / where / fix error
# ---------------------------------------------------------------------------


def test_missing_required_input_error_message(tmp_path: Path) -> None:
    with pytest.raises(MissingBlueprintInputError) as excinfo:
        build_sim(
            tmp_path,
            """
            from hassle import blueprint_automation

            blueprint_automation(
                id="office_switch",
                use_blueprint="local/room-switch-controls.yaml",
                inputs={"switch_entity": "sensor.office_paddle"},
            )
            """,
            blueprints={"local/room-switch-controls.yaml": ROOM_SWITCH},
        )
    check_snapshot(
        SNAP_DIR,
        "blueprint_missing_required_input",
        normalize_error(str(excinfo.value)),
    )


# ---------------------------------------------------------------------------
# (e) an absent blueprint file leaves the automation inert (today's behavior)
# ---------------------------------------------------------------------------


def test_absent_blueprint_file_leaves_the_automation_inert(tmp_path: Path) -> None:
    # No `blueprints/` directory at all: exactly the pre-expansion behavior.
    sim = build_sim(tmp_path, INSTANCE)
    sim.state_change("sensor.office_paddle", "idle", "up")
    sim.state_change("sensor.office_paddle", "idle", "down")
    assert sim.all_calls() == []
    assert sim.automation_keys() == ["automation:office_switch"]


def test_blueprint_file_for_a_different_path_leaves_it_inert(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        INSTANCE,
        blueprints={"local/some-other-blueprint.yaml": ROOM_SWITCH},
    )
    sim.state_change("sensor.office_paddle", "idle", "up")
    assert sim.all_calls() == []


# ---------------------------------------------------------------------------
# push/plan payloads must not change
# ---------------------------------------------------------------------------


def test_compiled_ir_is_identical_with_and_without_a_blueprint_file(tmp_path: Path) -> None:
    with_file = compile_source(
        tmp_path / "a",
        INSTANCE,
        blueprints={"local/room-switch-controls.yaml": ROOM_SWITCH},
    )
    without_file = compile_source(tmp_path / "b", INSTANCE)
    assert {k: o.to_ha() for k, o in with_file.objects.items()} == {
        k: o.to_ha() for k, o in without_file.objects.items()
    }
    body = with_file.objects["automation:office_switch"].to_ha()
    assert set(body) == {"id", "alias", "use_blueprint"}


# ---------------------------------------------------------------------------
# the fixture bundle, end to end through the public `simulate()` entry point
# ---------------------------------------------------------------------------


def test_fixture_bundle_simulates_through_simulate() -> None:
    sim = simulate(FIXTURE_BUNDLE)
    sim.state_change("sensor.office_paddle", "idle", "up", {"event_type": "single"})
    sim.assert_called(
        "light.turn_on",
        entity_id="light.office",
        brightness_step_pct=10,
        event_note="single",
    )
    sim.state_change("sensor.office_paddle", "idle", "down", {"event_type": "hold"})
    sim.assert_called(
        "light.turn_on",
        entity_id="light.office",
        brightness_step_pct=-10,
        event_note="hold",
    )
