"""MILESTONES M10 test 3 — decompile/adopt of template-helper objects into
`helpers/`, with I3 round-trip byte-stability applied to the config-entry
options body.

`TemplateHelperConfig` decompiles to the matching builder call
(`hassle.decompiler.codegen._template_helper_source`): there is no identity
kwarg to rename -- `TemplateHelperConfig` has no `id`/`unique_id` field at
all (docs/ha-api-notes.md §26.6: real HA's config-flow form schema rejects
an unrecognized `unique_id` key outright). Identity is derived from `name`
(slugified) at both compile and decompile time. Placement follows the same
category/misc rule as the nine storage-collection helpers
(`test_bundle_ops_placement.py::test_default_source_path_places_template_helpers_under_helpers_misc`).

**M13 update:** `_template_helper_source` now tries the bounded Jinja
inverter first (`hassle.decompiler.template_invert`) and only falls back to
the call form asserted here when a `state=` Jinja string is outside the
inverter's bounded grammar. Of this fixture's four objects, exactly
`template_sensor:average_temp`'s state (`(states('sensor.a') | float +
states('sensor.b') | float) / 2`) is inside that grammar -- the other three
use `is_state(...)`/a bare `states(...)` read (no `| float`)/a `selectattr`
filter chain, none of which this parser models, so they still decompile to
the call form asserted below unchanged. See
`test_template_helper_decorator_form.py` for the decorator-form-specific
contract (M13 tests 1-5).
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_object

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_helper_declarations"
    / "bundle"
)


def test_decompile_template_number_produces_matching_builder_call() -> None:
    result = compile_bundle(FIXTURE)
    key = "template_number:active_hvac_zones"
    obj = result.objects[key]
    source = decompile_object(key, obj)

    assert source.startswith("active_hvac_zones = template_number(")
    assert "name='Active HVAC Zones'" in source
    assert "id=" not in source  # no identity kwarg at all (§26.6)
    assert "unique_id=" not in source
    assert "set_value=" in source
    # min/max/step decompile as floats (CI round 4, docs/ha-api-notes.md
    # §26.10): HA's NumberSelector always stores these as floats, and the
    # compiler now coerces to match -- `render_literal`'s `repr()` renders
    # them accordingly.
    assert "min=0.0" in source and "max=8.0" in source and "step=1.0" in source


def test_decompile_every_template_domain_uses_matching_builder_name() -> None:
    """Each object's source names its matching builder -- as the call form's
    `ident = builder(...)` for the three objects whose `state=` is outside
    the M13 bounded inverter's grammar, or as the decorator form's
    `@builder(...)` for `average_temp` (the one object whose state IS inside
    it -- module docstring)."""
    result = compile_bundle(FIXTURE)
    expected_builder = {
        "template_number:active_hvac_zones": "template_number",
        "template_sensor:average_temp": "template_sensor",
        "template_binary_sensor:any_door_open": "template_binary_sensor",
        "template_select:house_scene": "template_select",
    }
    call_form_keys = {
        "template_number:active_hvac_zones",
        "template_binary_sensor:any_door_open",
        "template_select:house_scene",
    }
    for key, builder in expected_builder.items():
        obj = result.objects[key]
        source = decompile_object(key, obj)
        if key in call_form_keys:
            assert source.split(" = ", 1)[1].startswith(f"{builder}(")
        else:
            assert source.startswith(f"@{builder}(")


def test_decompile_recompile_round_trip_is_byte_stable_for_options_body(
    tmp_path: Path,
) -> None:
    """I3 applied to a config-entry options body: compile(decompile(x)) == x."""
    result = compile_bundle(FIXTURE)
    original_ir = {key: obj.to_ha() for key, obj in result.objects.items()}

    lines = [
        "from hassle import (",
        "    expr,",  # M13: average_temp now decompiles to the decorator form
        "    template_binary_sensor,",
        "    template_number,",
        "    template_select,",
        "    template_sensor,",
        ")",
        # The fixture's set_value/select_option action dicts contain entity-id
        # -shaped strings, which the decompiler's `render_literal` (DESIGN
        # §7.3's entity-reference cosmetic rewrite) emits as `e.<domain>.<id>`
        # -- needs this import, exactly like any generated bundle would carry.
        # M13: the inverted `average_temp` decorator body also references `e.`
        # entities directly (`expr(e.sensor.a)`).
        "from hassle.registry import entities as e",
        "",
    ]
    for key, obj in sorted(result.objects.items()):
        lines.append(decompile_object(key, obj))
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text("\n".join(lines), encoding="utf-8")

    recompiled = compile_bundle(bundle_dir)
    recompiled_ir = {key: obj.to_ha() for key, obj in recompiled.objects.items()}

    assert recompiled_ir == original_ir


def test_decompiled_write_target_helpers_recompile_without_error(tmp_path: Path) -> None:
    """Defensive I3 test (reviewer follow-up, `MissingTemplateHelperWriteTargetError`):
    the DECOMPILER must never produce a `template_number`/`template_select` call that
    then fails the new compile-time required-write-target check. Golden-fixture pulled
    template helpers always carry their `set_value`/`select_option` keys (M10
    CI-verified) -- this test recompiles the decompiled source for exactly those two
    write-target-bearing objects and asserts it raises nothing, and that the emitted
    source textually carries the required kwarg (so a future decompiler change that
    silently dropped it would fail loudly here, not just via a values-differ diff).
    """
    from hassle.compiler.errors import CompileError

    result = compile_bundle(FIXTURE)
    for key, required_kwarg in (
        ("template_number:active_hvac_zones", "set_value="),
        ("template_select:house_scene", "select_option="),
    ):
        obj = result.objects[key]
        source = decompile_object(key, obj)
        assert required_kwarg in source

        bundle_dir = tmp_path / key.replace(":", "_")
        bundle_dir.mkdir()
        (bundle_dir / "helpers.py").write_text(
            "from hassle import template_number, template_select\n"
            "from hassle.registry import entities as e\n\n" + source + "\n",
            encoding="utf-8",
        )
        # Must not raise MissingTemplateHelperWriteTargetError (or anything else).
        try:
            compile_bundle(bundle_dir)
        except CompileError as exc:  # pragma: no cover - failure path, not the happy path
            raise AssertionError(
                f"decompiled {key} failed to recompile ({type(exc).__name__}: {exc})"
            ) from exc
