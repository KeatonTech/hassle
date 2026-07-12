"""M3 core validator tests (milestone items 1, 2, 2b, 3, 4) — DESIGN §9 tiers 1-3.

`validate_bundle(compile_result, snapshot)` returns `list[Finding]`, all offline
against `fixtures/registry/home.json`. No network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automation.py").write_text(code, encoding="utf-8")
    return bundle


# --- milestone test 1: unknown entity flagged / known entity ok -------------


def test_unknown_entity_flagged(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.does_not_exist").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    codes = {f.code for f in findings}
    assert "unknown-entity" in codes
    bad = next(f for f in findings if f.code == "unknown-entity")
    assert "binary_sensor.does_not_exist" in bad.message
    assert bad.file is not None and bad.line is not None


def test_known_entity_ok(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(f.code == "unknown-entity" for f in findings)


def test_unknown_entity_inside_template(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, template, when

@automation(id="a", alias="A")
def a():
    when(template("{{ states('binary_sensor.does_not_exist') == 'on' }}"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = [f for f in findings if f.code == "unknown-entity"]
    assert any("binary_sensor.does_not_exist" in f.message for f in bad)


def test_unknown_entity_inside_raw_block(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, raw_action

@automation(id="a", alias="A")
def a():
    raw_action({"service": "light.turn_on", "entity_id": "light.does_not_exist"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-entity" and "light.does_not_exist" in f.message for f in findings)


def test_unknown_entity_in_list_form(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, raw_action

@automation(id="a", alias="A")
def a():
    raw_action({
        "action": "light.turn_on",
        "target": {"entity_id": ["light.hallway", "light.bogus"]},
    })
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-entity" and "light.bogus" in f.message for f in findings)
    assert not any("light.hallway" in f.message for f in findings if f.code == "unknown-entity")


# --- reviewer B1: unknown entities inside nested control-flow containers ---
# extraction reaching nested positions is necessary but validation must also
# actually surface a Finding for an unknown entity buried inside if/choose/
# repeat/parallel/wait_for_trigger -- a three-position probe (if_then body,
# repeat_count body, parallel body) that the reviewer found silently missed.


def test_unknown_entity_inside_if_then_body(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, if_then, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with if_then(state("sensor.temperature").is_("hot")):
        service("light.turn_on", target={"entity_id": "light.does_not_exist_if_body"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_if_body" in f.message for f in findings
    )


def test_unknown_entity_inside_else_body(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, else_then, if_then, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with if_then(state("sensor.temperature").is_("hot")):
        service("light.turn_on", target={"entity_id": "light.hallway"})
    with else_then():
        service("light.turn_on", target={"entity_id": "light.does_not_exist_else_body"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_else_body" in f.message
        for f in findings
    )


def test_unknown_entity_inside_choose_branch(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, choose, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with choose() as c:
        with c.when_(state("input_select.house_mode").is_("night")):
            service("light.turn_on", target={"entity_id": "light.does_not_exist_choose_branch"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_choose_branch" in f.message
        for f in findings
    )


def test_unknown_entity_inside_choose_default(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, choose, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with choose() as c:
        with c.when_(state("input_select.house_mode").is_("night")):
            service("light.turn_on", target={"entity_id": "light.hallway"})
        with c.default():
            service("light.turn_on", target={"entity_id": "light.does_not_exist_choose_default"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_choose_default" in f.message
        for f in findings
    )


def test_unknown_entity_inside_repeat_body(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, repeat_count, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with repeat_count(2):
        service("light.turn_on", target={"entity_id": "light.does_not_exist_repeat_body"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_repeat_body" in f.message
        for f in findings
    )


def test_unknown_entity_inside_parallel_body(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, parallel, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with parallel():
        service("light.turn_on", target={"entity_id": "light.does_not_exist_parallel_body"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_parallel_body" in f.message
        for f in findings
    )


def test_unknown_entity_inside_nested_repeat_inside_choose(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, choose, repeat_count, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with choose() as c:
        with c.when_(state("input_boolean.armed").is_("on")):
            with repeat_count(2):
                service(
                    "light.turn_on",
                    target={"entity_id": "light.does_not_exist_nested_nested"},
                )
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "light.does_not_exist_nested_nested" in f.message
        for f in findings
    )


def test_unknown_entity_inside_wait_for_trigger(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, wait_for, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    wait_for(state("binary_sensor.does_not_exist_wait_for").to("off"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "binary_sensor.does_not_exist_wait_for" in f.message
        for f in findings
    )


# --- coordinator fix-forward: template-valued target strings must still be
# scanned for embedded Jinja entity refs, not just exempted from literal-id
# validation. `_is_template_string` correctly stops a placeholder like
# `{{ repeat.item }}` from being treated as a literal id, but a template
# string that actually calls `states(...)` (e.g. inside a `target:` block)
# must still reach `_extract_entity_ids_from_jinja` -- the same scan `data`/
# `service_data` values already get.


def test_unknown_entity_inside_template_valued_target_nested_in_if_then(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, if_then, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with if_then(state("sensor.temperature").is_("hot")):
        service(
            "light.turn_on",
            target={"entity_id": "{{ states('sensor.definitely_missing') }}"},
        )
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "sensor.definitely_missing" in f.message for f in findings
    )


def test_repeat_for_each_placeholder_still_yields_zero_findings(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """No regression on the placeholder case that motivated `_is_template_string`
    in the first place: `{{ repeat.item }}` must never be treated as a literal
    entity_id, and it has no embedded `states(...)`-style call to scan either,
    so it must still yield zero findings.
    """
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, repeat_for_each, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    with repeat_for_each(["light.hallway", "light.kitchen"]):
        service("light.turn_on", target={"entity_id": "{{ repeat.item }}"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert findings == [], f"unexpected findings on repeat_for_each placeholder: {findings}"


# --- milestone test 2: did-you-mean -----------------------------------------


def test_did_you_mean(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.halway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = next(f for f in findings if f.code == "unknown-entity")
    assert "light.hallway" in bad.fix


# --- milestone test 2b: purpose vocabulary validation -----------------------


def test_unknown_purpose_trigger_type(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("nonsense.made_up_type"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-purpose-type" for f in findings)


def test_unknown_purpose_condition_type_not_checked_against_triggers(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    # "motion.detected" is a valid TRIGGER type but not a valid CONDITION type;
    # using it as a condition must still be flagged (cross-vocabulary check
    # must not happen the wrong way and accidentally validate it).
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, met, only_if, service, when, state

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(met("motion.detected"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-purpose-type" for f in findings)


def test_renamed_purpose_key_finding_names_new_key(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = REPO_ROOT / "fixtures" / "dsl" / "purpose_trigger_renamed_key" / "bundle"
    result = compile_bundle(bundle)
    # sensor.wireless_device_battery must exist in the registry fixture for
    # this test to isolate the rename finding (not an unrelated unknown-entity).
    findings = validate_bundle(result, snapshot)
    renamed = [f for f in findings if f.code == "renamed-purpose-type"]
    assert renamed, f"expected a renamed-purpose-type finding, got: {findings}"
    assert "battery.became_low" in renamed[0].fix
    assert "battery.low" in renamed[0].message


def test_target_area_id_validated(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, area, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=area("not_a_real_area")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-area" for f in findings)


def test_target_floor_id_validated(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, floor, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=floor("not_a_real_floor")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-floor" for f in findings)


def test_target_label_id_validated(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, label, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=label("not_a_real_label")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-label" for f in findings)


# --- milestone test 3: bundle-declared helpers count as existing -----------


def test_bundle_declared_helper_counts(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, input_boolean, service, state, when

MY_HELPER = input_boolean(id="my_undeclared_elsewhere_helper", name="My Helper")

@automation(id="a", alias="A")
def a():
    when(state(MY_HELPER).to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert not any(
        f.code == "unknown-entity" and "my_undeclared_elsewhere_helper" in f.message
        for f in findings
    )


def test_undeclared_helper_reference_fails(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("input_boolean.totally_undeclared").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(
        f.code == "unknown-entity" and "input_boolean.totally_undeclared" in f.message
        for f in findings
    )


# --- milestone test 4: service-call parameter validation -------------------


def test_service_param_unknown(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"}, not_a_real_param=1)
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "unknown-service-param" for f in findings)


def test_service_param_wrong_type(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service(
        "light.turn_on",
        target={"entity_id": "light.hallway"},
        brightness_pct="not_a_number",
    )
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "service-param-wrong-type" for f in findings)


def test_service_param_missing_required(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("notify.notify", target={"entity_id": "light.hallway"}, title="hi")
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert any(f.code == "service-param-missing-required" for f in findings)


def test_service_param_findings_have_correct_span(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"}, bogus_param=1)
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    bad = next(f for f in findings if f.code == "unknown-service-param")
    assert bad.file is not None and bad.file.endswith("automation.py")
    assert bad.line == 6


# --- false-positive audit against the existing M0/M1/M2 golden corpus ------

# `purpose_trigger_renamed_key` is deliberately NOT clean: it exists to exercise
# the renamed-purpose-type Finding (M1's own docstring says as much, and
# `test_renamed_purpose_key_finding_names_new_key` above asserts the Finding
# appears) — excluding it here is a test-scope fix, not a validation weakening.
_DELIBERATELY_NOT_CLEAN = {"purpose_trigger_renamed_key"}


@pytest.mark.parametrize(
    "case_dir",
    sorted(
        p
        for p in (REPO_ROOT / "fixtures" / "dsl").iterdir()
        if (p / "bundle").is_dir()
        and (p / "expected_ir.json").is_file()
        and p.name not in _DELIBERATELY_NOT_CLEAN
    ),
    ids=lambda p: p.name,
)
def test_no_false_positives_on_golden_corpus(case_dir: Path, snapshot: RegistrySnapshot) -> None:
    result = compile_bundle(case_dir / "bundle")
    findings = validate_bundle(result, snapshot)
    assert findings == [], f"{case_dir.name}: unexpected findings: {findings}"


def test_core_non_registry_entities_are_never_unknown(tmp_path: Path) -> None:
    """`sun.sun` exists in every HA instance but never appears in the entity
    REGISTRY (it predates the registry), so the registry snapshot can't
    contain it -- referencing it must not be an unknown-entity finding
    (owner field report: a template reading state_attr('sun.sun',
    'elevation') failed validate on a real bundle)."""
    from hassle.registry.validate import _check_entity

    finding = _check_entity(
        "sun.sun",
        snapshot=RegistrySnapshot(),
        declared_helpers=set(),
        file="desk_lighting.py",
        line=1,
    )
    assert finding is None


def test_sun_template_validates_end_to_end(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """The exact field shape that failed: a condition template reading
    state_attr('sun.sun', 'elevation'), through the full compile -> template
    extraction -> validate path (reviewer hardening on PR #28)."""
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, if_then, service, state, template, when

@automation(id="a", alias="A")
def a():
    when(state("light.hallway").to("on"))
    with if_then(template("{{ (state_attr('sun.sun', 'elevation') | float(45)) > 10 }}")):
        service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert [f for f in findings if f.code == "unknown-entity"] == []


def test_template_helper_entities_count_as_declared(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    """A template helper declared in THIS bundle produces a real entity
    (template_binary_sensor:x -> binary_sensor.x) that other templates --
    including self-referential hysteresis templates -- may reference before
    the first push ever creates it (owner field case: presence-fusion
    binary referencing itself for hysteresis)."""
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service, state, template_binary_sensor, when, only_if

@template_binary_sensor(name="Living Room Occupied Fused")
def occupied_fused():
    return "{{ 1 == 1 }}"

@automation(id="a", alias="A")
def a():
    when(state("light.hallway").to("on"))
    with only_if(state("binary_sensor.living_room_occupied_fused").is_("on")):
        service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    assert [f for f in findings if f.code == "unknown-entity"] == []


def test_template_entity_domain_map_covers_every_template_domain() -> None:
    """Drift guard (PR #32 review): a new template domain added to
    TEMPLATE_DOMAINS without a _TEMPLATE_ENTITY_DOMAIN entry silently
    reintroduces the unknown-entity-before-first-push bug for that domain."""
    from hassle.ir.keys import TEMPLATE_DOMAINS
    from hassle.registry.validate import _TEMPLATE_ENTITY_DOMAIN

    assert set(_TEMPLATE_ENTITY_DOMAIN) == set(TEMPLATE_DOMAINS)
