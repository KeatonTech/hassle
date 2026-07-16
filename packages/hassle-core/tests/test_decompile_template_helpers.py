"""Decompile/adopt of template-helper objects into `helpers/`, with
compile(decompile(x)) == x round-trip byte-stability applied to the
config-entry options body.

`TemplateHelperConfig` decompiles to the matching builder call
(`hassle.decompiler.codegen._template_helper_source`): there is no identity
kwarg to rename -- `TemplateHelperConfig` has no `id`/`unique_id` field at
all (docs/ha-api-notes.md §26.6: real HA's config-flow form schema rejects
an unrecognized `unique_id` key outright). Identity is derived from `name`
(slugified) at both compile and decompile time. Placement follows the same
category/misc rule as the nine storage-collection helpers
(`test_bundle_ops_placement.py::test_default_source_path_places_template_helpers_under_helpers_misc`).

`_template_helper_source` tries the bounded Jinja inverter first
(`hassle.decompiler.template_invert`) and falls back to a decorator form
(`@builder(...)` / `def <ident>(): return "<verbatim Jinja>"`) when a
`state=` Jinja string is outside the inverter's bounded grammar. Of this
fixture's four objects: `template_sensor:average_temp`'s state
(`(states('sensor.a') | float + states('sensor.b') | float) / 2`) and
`template_select:house_scene`'s state (`states('input_select.house_mode')`,
a bare read with no `| float`) both invert cleanly via `expr(...)` /
`state_of(...)` (DESIGN §5.4 extension); only
`template_binary_sensor:any_door_open`'s `is_state(...)` call form falls back
to the verbatim decorator body (documented one-time-canonicalization
behavior, docs/dsl-extensions.md). See `test_template_helper_decorator_form.py`
for the decorator-form-specific contract and
`test_template_helper_decorator_fallback.py` for the fallback-form-specific
contract.
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


def test_decompile_template_number_produces_matching_builder_decorator() -> None:
    """The fallback branch is ALSO the decorator form -- `state=` moves
    into the `return` body instead of staying a decorator kwarg; every other
    kwarg is unaffected and still rendered in the decorator's argument list."""
    result = compile_bundle(FIXTURE)
    key = "template_number:active_hvac_zones"
    obj = result.objects[key]
    source = decompile_object(key, obj)

    assert source.startswith("@template_number(")
    assert "def active_hvac_zones():" in source
    assert "name='Active HVAC Zones'" in source
    assert "id=" not in source  # no identity kwarg at all (§26.6)
    assert "unique_id=" not in source
    assert "set_value=" in source
    # `state=` is never a decorator kwarg -- it's the `return`ed string body
    # instead.
    decorator_line = source.split("\n", 1)[0]
    assert "state=" not in decorator_line
    # min/max/step decompile as floats (docs/ha-api-notes.md
    # §26.10): HA's NumberSelector always stores these as floats, and the
    # compiler now coerces to match -- `render_literal`'s `repr()` renders
    # them accordingly.
    assert "min=0.0" in source and "max=8.0" in source and "step=1.0" in source


def test_decompile_every_template_domain_uses_matching_builder_name() -> None:
    """Each object's source names its matching builder as the decorator form's
    `@builder(...)` -- both the invertible branch, `average_temp`, and the
    fallback branch, the other three objects (see module docstring)."""
    result = compile_bundle(FIXTURE)
    expected_builder = {
        "template_number:active_hvac_zones": "template_number",
        "template_sensor:average_temp": "template_sensor",
        "template_binary_sensor:any_door_open": "template_binary_sensor",
        "template_select:house_scene": "template_select",
    }
    for key, builder in expected_builder.items():
        obj = result.objects[key]
        source = decompile_object(key, obj)
        assert source.startswith(f"@{builder}(")


def test_decompile_recompile_round_trip_is_byte_stable_for_options_body(
    tmp_path: Path,
) -> None:
    """Applied to a config-entry options body: compile(decompile(x)) == x."""
    result = compile_bundle(FIXTURE)
    original_ir = {key: obj.to_ha() for key, obj in result.objects.items()}

    lines = [
        "from hassle import (",
        "    expr,",  # average_temp decompiles to the decorator form
        "    state_of,",  # house_scene decompiles to the decorator form too
        "    template_binary_sensor,",
        "    template_number,",
        "    template_select,",
        "    template_sensor,",
        ")",
        # The fixture's set_value/select_option action dicts contain entity-id
        # -shaped strings, which the decompiler's `render_literal` (DESIGN
        # §7.3's entity-reference cosmetic rewrite) emits as `e.<domain>.<id>`
        # -- needs this import, exactly like any generated bundle would carry.
        # The inverted `average_temp` decorator body also references `e.`
        # entities directly (`expr(e.sensor.a)`); `house_scene`'s inverted
        # body does too (`state_of(e.input_select.house_mode)`). The
        # remaining fallback decorator body is `return "<raw string>"` -- no
        # `expr`/`e.` reference needed for that one, but the import stays
        # harmless (unused-import isn't checked by this test).
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
    """Defensive round-trip test for `MissingTemplateHelperWriteTargetError`:
    the DECOMPILER must never produce a `template_number`/`template_select` call that
    then fails the compile-time required-write-target check. Golden-fixture pulled
    template helpers always carry their `set_value`/`select_option` keys -- this
    test recompiles the decompiled source for exactly those two
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
            # house_scene's inverted body references state_of(e....).
            "from hassle import state_of, template_number, template_select\n"
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
