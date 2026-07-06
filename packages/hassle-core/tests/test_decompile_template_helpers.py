"""MILESTONES M10 test 3 — decompile/adopt of template-helper objects into
`helpers/`, with I3 round-trip byte-stability applied to the config-entry
options body.

`TemplateHelperConfig` decompiles to the matching builder call
(`hassle.decompiler.codegen._template_helper_source`): the stored
``unique_id`` field maps back to the builder's ``id=`` kwarg (the one
deliberate name difference from the stored body, since ``id=`` is the DSL's
declared-identity kwarg everywhere else too). Placement follows the same
category/misc rule as the nine storage-collection helpers
(`test_bundle_ops_placement.py::test_default_source_path_places_template_helpers_under_helpers_misc`).
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
    assert "id='active_hvac_zones'" in source
    assert "unique_id=" not in source  # unique_id -> id= rename, never leaked
    assert "min=0" in source and "max=8" in source and "step=1" in source


def test_decompile_every_template_domain_uses_matching_builder_name() -> None:
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
        assert source.split(" = ", 1)[1].startswith(f"{builder}(")


def test_decompile_recompile_round_trip_is_byte_stable_for_options_body(
    tmp_path: Path,
) -> None:
    """I3 applied to a config-entry options body: compile(decompile(x)) == x."""
    result = compile_bundle(FIXTURE)
    original_ir = {key: obj.to_ha() for key, obj in result.objects.items()}

    lines = [
        "from hassle import (",
        "    template_binary_sensor,",
        "    template_number,",
        "    template_select,",
        "    template_sensor,",
        ")",
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
