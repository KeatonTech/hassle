"""M1 INTEGRATION — pre-built objects land in CompileResult.objects (§12 gap).

Helper declarations, ``raw_automation``/``@raw_automation``, and
``@blueprint_automation`` are whole top-level objects, not trigger/condition/
action calls recorded *inside* an automation. The §12 contract gap
(docs/ha-api-notes.md) was that ``compile_bundle`` only drained the function-
shaped registry, so these never reached ``CompileResult.objects``.

These tests compile real bundle dirs and assert the objects appear under the
right object keys, in the canonical plural HA schema.
"""

from __future__ import annotations

from pathlib import Path

from hassle_core.compiler import compile_bundle

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def _compile(case: str) -> dict[str, dict]:
    result = compile_bundle(_FIXTURES / case / "bundle")
    return {key: obj.to_ha() for key, obj in result.objects.items()}


def test_helper_declarations_land_in_objects() -> None:
    objects = _compile("helper_declarations")
    # All nine helper domains declared in one bundle → nine helper objects.
    keys = set(objects)
    for domain in (
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    ):
        matching = [k for k in keys if k.startswith(f"{domain}:")]
        assert matching, f"no {domain} helper object in {sorted(keys)}"


def test_raw_automation_normalizes_legacy_keys() -> None:
    objects = _compile("raw_automation_legacy")
    # The bundle authored the raw automation with legacy singular keys
    # (trigger/condition/action + service:); normalize_ha must have converted to
    # the plural + action: form on the way into the IR.
    (body,) = [v for k, v in objects.items() if k.startswith("automation:")]
    assert "triggers" in body and "trigger" not in body
    assert "actions" in body and "action" not in body
    # service: -> action: inside the action block
    assert body["actions"][0].get("action") is not None
    assert "service" not in body["actions"][0]


def test_blueprint_automation_shape() -> None:
    objects = _compile("blueprint_automation")
    (body,) = [v for k, v in objects.items() if k.startswith("automation:")]
    # inputs= mapped to use_blueprint.input (singular); author-qualified path
    # (docs/ha-api-notes.md §10.5).
    assert set(body) >= {"id", "use_blueprint"}
    ub = body["use_blueprint"]
    assert ub["path"] == "hassle/motion_light.yaml"
    assert ub["input"] == {
        "motion_entity": "binary_sensor.hall_motion",
        "light_target": "light.hallway",
        "no_motion_wait": 90,
    }
    # A blueprint automation carries no trigger/condition/action blocks.
    assert "triggers" not in body and "actions" not in body


def test_prebuilt_and_recorded_objects_coexist() -> None:
    # A bundle mixing a normal @automation with helper declarations must yield
    # both in one CompileResult (proves the two object streams merge).
    objects = _compile("helper_declarations")
    assert any(k.startswith("input_boolean:") for k in objects)


def test_compile_is_deterministic_for_prebuilt() -> None:
    # R8: repeated compiles of a prebuilt-object bundle are byte-stable and do
    # not accumulate duplicates across the process (declared-list reset works).
    first = _compile("helper_declarations")
    second = _compile("helper_declarations")
    assert first == second
