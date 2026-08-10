"""Blueprint expansion: `use_blueprint` -> a concrete automation config.

A `@blueprint_automation` compiles to only ``{"use_blueprint": {path, input}}``
-- no triggers, no actions -- so without expansion it is invisible to the
simulator and nothing routed through a blueprint can be tested. Expansion is
LOCAL and OFFLINE (R2: no network in unit tests, and bundle tests must stay
deterministic): the blueprint source is a bundle-local file at
``<bundle>/blueprints/automation/<use_blueprint path>``, mirroring HA's own
``config/blueprints/automation/`` layout.

Semantics mirror `homeassistant/components/blueprint`: parse the YAML
(including the ``!input`` custom tag), validate the instance's inputs against
``blueprint.input`` (missing required = error, absent optional takes its
declared ``default``), substitute every ``!input`` node by a straight
tree-walk, and emit the blueprint's own triggers/conditions/actions/mode with
the instance's top-level fields (id/alias/description) carried over.

The golden pair for this lives at ``fixtures/dsl/blueprint_local_expansion/``:
its ``expected_ir.json`` pins that the compiled IR is *unchanged* by the
blueprint file's existence (push/plan payloads must not move), while the
expansion asserted here is what the simulator layers on top.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _dsl_cases import dsl_dir
from _sim_helpers import write_blueprints

from hassle.blueprints import (
    BLUEPRINT_SUBDIR,
    InvalidBlueprintError,
    MissingBlueprintInputError,
    blueprint_file,
    expand_blueprint,
)
from hassle.compiler import compile_bundle
from hassle.ir.models import AutomationConfig

FIXTURE_BUNDLE = dsl_dir() / "blueprint_local_expansion" / "bundle"


def _fixture_body() -> dict[str, Any]:
    result = compile_bundle(FIXTURE_BUNDLE)
    obj = result.objects["automation:office_switch_controls"]
    assert isinstance(obj, AutomationConfig)
    return obj.to_ha()


def test_blueprint_file_mirrors_ha_layout() -> None:
    # `use_blueprint="local/room-switch-controls.yaml"` resolves to
    # <bundle>/blueprints/automation/local/room-switch-controls.yaml.
    assert BLUEPRINT_SUBDIR == ("blueprints", "automation")
    path = blueprint_file(FIXTURE_BUNDLE, "local/room-switch-controls.yaml")
    assert path == FIXTURE_BUNDLE / "blueprints/automation/local/room-switch-controls.yaml"
    assert path.is_file()


def test_expansion_produces_the_concrete_automation() -> None:
    expanded = expand_blueprint(_fixture_body(), bundle_root=FIXTURE_BUNDLE)
    assert expanded == {
        # The instance's own top-level fields ride over the blueprint's body.
        "id": "office_switch_controls",
        "alias": "Office switch controls",
        "mode": "restart",
        "triggers": [
            {"trigger": "state", "entity_id": "sensor.office_paddle", "to": "up", "id": "up"},
            {"trigger": "state", "entity_id": "sensor.office_paddle", "to": "down", "id": "down"},
        ],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "trigger", "id": "up"}],
                        "sequence": [
                            {
                                "action": "light.turn_on",
                                "target": {"entity_id": "light.office"},
                                "data": {
                                    # absent optional input -> its declared default
                                    "brightness_step_pct": 10,
                                    "event_note": "{{ trigger.to_state.attributes.event_type }}",
                                },
                            }
                        ],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "down"}],
                        "sequence": [
                            {
                                "action": "light.turn_on",
                                "target": {"entity_id": "light.office"},
                                "data": {
                                    "brightness_step_pct": -10,
                                    "event_note": "{{ trigger.to_state.attributes.event_type }}",
                                },
                            }
                        ],
                    },
                ]
            }
        ],
    }
    # The `blueprint:` metadata block itself never survives into the config.
    assert "blueprint" not in expanded
    assert "use_blueprint" not in expanded


def test_expansion_leaves_the_compiled_ir_untouched() -> None:
    # Expansion is a simulator-side read; it must never mutate the IR the
    # push/plan payload is built from.
    body = _fixture_body()
    before = dict(body)
    expand_blueprint(body, bundle_root=FIXTURE_BUNDLE)
    assert body == before
    assert body["use_blueprint"]["input"] == {
        "switch_entity": "sensor.office_paddle",
        "room_light": "light.office",
    }


def test_absent_blueprint_file_expands_to_none() -> None:
    body = _fixture_body()
    body["use_blueprint"] = {"path": "nobody/nothing.yaml", "input": {}}
    assert expand_blueprint(body, bundle_root=FIXTURE_BUNDLE) is None


def test_no_bundle_root_expands_to_none() -> None:
    assert expand_blueprint(_fixture_body(), bundle_root=None) is None


def test_non_blueprint_automation_expands_to_none() -> None:
    body = {"id": "plain", "triggers": [], "actions": []}
    assert expand_blueprint(body, bundle_root=FIXTURE_BUNDLE) is None


def test_missing_required_input_is_an_error(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_blueprints(
        bundle,
        {
            "local/needs.yaml": """
            blueprint:
              name: Needs a switch
              domain: automation
              input:
                switch_entity:
                  name: Switch
            triggers:
              - trigger: state
                entity_id: !input switch_entity
            actions: []
            """
        },
    )
    body = {"id": "x", "use_blueprint": {"path": "local/needs.yaml", "input": {}}}
    with pytest.raises(MissingBlueprintInputError) as excinfo:
        expand_blueprint(body, bundle_root=bundle)
    assert excinfo.value.input_name == "switch_entity"


def test_input_entry_without_metadata_is_required(tmp_path: Path) -> None:
    # HA allows `input: {name: }` (a null entry, no metadata at all); with no
    # `default:` it is still a required input.
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_blueprints(
        bundle,
        {
            "local/bare.yaml": """
            blueprint:
              name: Bare input
              domain: automation
              input:
                who:
            actions:
              - action: light.turn_on
                target:
                  entity_id: !input who
            """
        },
    )
    body = {"id": "x", "use_blueprint": {"path": "local/bare.yaml", "input": {}}}
    with pytest.raises(MissingBlueprintInputError):
        expand_blueprint(body, bundle_root=bundle)
    supplied = {
        "id": "x",
        "use_blueprint": {"path": "local/bare.yaml", "input": {"who": "light.a"}},
    }
    expanded = expand_blueprint(supplied, bundle_root=bundle)
    assert expanded is not None
    assert expanded["actions"][0]["target"]["entity_id"] == "light.a"


def test_legacy_singular_blueprint_body_is_normalized(tmp_path: Path) -> None:
    # A blueprint authored in HA's legacy singular shape (`trigger:`/`action:`
    # blocks, `service:` verbs) expands to the canonical plural schema the
    # simulator engine reads -- same `normalize_ha` every other path uses.
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_blueprints(
        bundle,
        {
            "local/legacy.yaml": """
            blueprint:
              name: Legacy shape
              domain: automation
              input:
                sensor:
            trigger:
              - platform: state
                entity_id: !input sensor
            action:
              - service: light.turn_on
                entity_id: light.a
            """
        },
    )
    body = {
        "id": "x",
        "use_blueprint": {"path": "local/legacy.yaml", "input": {"sensor": "binary_sensor.b"}},
    }
    expanded = expand_blueprint(body, bundle_root=bundle)
    assert expanded is not None
    assert expanded["triggers"] == [{"platform": "state", "entity_id": "binary_sensor.b"}]
    assert expanded["actions"] == [{"action": "light.turn_on", "entity_id": "light.a"}]


def test_blueprint_without_metadata_block_is_an_error(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_blueprints(bundle, {"local/broken.yaml": "triggers: []\nactions: []\n"})
    body = {"id": "x", "use_blueprint": {"path": "local/broken.yaml", "input": {}}}
    with pytest.raises(InvalidBlueprintError):
        expand_blueprint(body, bundle_root=bundle)


def test_unparseable_blueprint_yaml_is_an_error(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_blueprints(bundle, {"local/bad.yaml": "blueprint: [unclosed\n"})
    body = {"id": "x", "use_blueprint": {"path": "local/bad.yaml", "input": {}}}
    with pytest.raises(InvalidBlueprintError):
        expand_blueprint(body, bundle_root=bundle)


def test_blueprint_path_cannot_escape_the_bundle(tmp_path: Path) -> None:
    # `use_blueprint` is a path string from the bundle's own source, but the
    # loader still refuses to read outside the bundle (the compiler's own
    # sandbox rule, DESIGN §14) rather than following `../..` upward.
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (tmp_path / "outside.yaml").write_text("blueprint: {}\n", encoding="utf-8")
    body = {"id": "x", "use_blueprint": {"path": "../../../outside.yaml", "input": {}}}
    assert expand_blueprint(body, bundle_root=bundle) is None
