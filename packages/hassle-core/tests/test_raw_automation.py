"""raw_automation / @raw_automation / @blueprint_automation (DESIGN §5.8).

These builders produce correct ``AutomationConfig`` IR objects
(JSON-serializability checked, legacy singular keys normalized, the blueprint
DSL->JSON key mapping applied). The registration path
(``Registry.add_object`` + ``compile_registered``'s prebuilt stream) wires them
into ``compile_bundle(...).objects``; see
``packages/hassle-core/tests/test_prebuilt_registration.py`` for the
end-to-end golden coverage. These tests exercise the builder layer directly.
"""

from __future__ import annotations

import pytest

from hassle.compiler.raw_automation import (
    RawAutomationNotJSONSerializableError,
    blueprint_automation,
    build_raw_automation,
    declared_raw_automations,
    raw_automation,
    reset_declared_raw_automations,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_declared_raw_automations()
    yield
    reset_declared_raw_automations()


def test_raw_automation_dict_assignment_form() -> None:
    obj = build_raw_automation(
        id="1687201958261",
        alias="Weird device trigger thing",
        trigger=[{"platform": "device", "device_id": "abc123", "type": "turned_on"}],
        action=[{"service": "light.turn_on", "entity_id": "light.hallway"}],
    )
    ha = obj.to_ha()
    # Legacy singular keys normalized to plural, service: -> action:, exactly
    # as HA's own storage normalization (docs/ha-api-notes.md §10.1).
    assert ha["triggers"] == [{"platform": "device", "device_id": "abc123", "type": "turned_on"}]
    assert ha["actions"] == [{"action": "light.turn_on", "entity_id": "light.hallway"}]
    assert "trigger" not in ha and "action" not in ha
    assert obj.object_key() == "automation:1687201958261"
    assert declared_raw_automations() == [obj]


def test_raw_automation_decorator_form() -> None:
    @raw_automation(id="dec_form")
    def legacy():
        return {"alias": "x", "trigger": [], "condition": [], "action": []}

    [obj] = declared_raw_automations()
    assert obj.object_key() == "automation:dec_form"
    assert obj.to_ha()["alias"] == "x"
    # the decorator returns the function unchanged (same convention as @automation).
    assert legacy() == {"alias": "x", "trigger": [], "condition": [], "action": []}


def test_raw_automation_non_json_serializable_raises() -> None:
    class Weird:
        pass

    with pytest.raises(RawAutomationNotJSONSerializableError) as excinfo:
        build_raw_automation(id="bad", alias="x", data=Weird())
    message = str(excinfo.value)
    assert "bad" in message
    assert "JSON" in message


def test_blueprint_automation_maps_inputs_to_singular_input_key() -> None:
    obj = blueprint_automation(
        id="hassle_bp_demo",
        use_blueprint="hassle/motion_light.yaml",
        inputs={"motion_entity": "binary_sensor.hall_motion", "no_motion_wait": 90},
    )
    ha = obj.to_ha()
    # docs/ha-api-notes.md §10.5: stored key is singular "input", path is
    # author-qualified, and a blueprint automation stores ONLY use_blueprint.
    assert ha["use_blueprint"] == {
        "path": "hassle/motion_light.yaml",
        "input": {"motion_entity": "binary_sensor.hall_motion", "no_motion_wait": 90},
    }
    assert "triggers" not in ha
    assert "actions" not in ha
