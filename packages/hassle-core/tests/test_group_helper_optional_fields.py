"""The §38.3 optional sensor-group fields, and the explicit-null regression:
`_declare_group_helper`
dropped every None-valued field from the compiled options body
(``**{k: v for k, v in fields.items() if v is not None}``), so a wire options
body carrying an EXPLICIT null would decompile to ``field=None`` and then
silently lose that field on recompile -- a compile(decompile(x)) == x break.
Unreachable while no modeled group field could be None; reachable the
moment the optional sensor-group fields of docs/ha-api-notes.md §38.3
(``ignore_non_numeric``/``unit_of_measurement``/``device_class``/
``state_class``) exist.

Schema authority: the CI integration matrix (§0/§38.3) -- these unit tests
pin Hassle's OWN compile/decompile behavior (kwargs accepted, body shape,
round-trip byte-stability), never HA's acceptance of any particular field;
`tests/integration/test_live_group_flow.py` is where the live schema is
asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.group_helpers import (
    declared_group_helpers,
    group_sensor,
    reset_declared_group_helpers,
)
from hassle.decompiler.codegen import decompile_object
from hassle.ir import parse, sha256_hash


def _compiled_group_sensor(**kwargs: Any) -> dict[str, Any]:
    """Build one `group_sensor` through the real DSL builder and return its
    compiled options body (in the spirit of the simulator executing compiled
    IR, not DSL Python: exercise the compiled IR, not a hand-typed
    approximation)."""
    reset_declared_group_helpers()
    group_sensor(**kwargs)
    (helper,) = declared_group_helpers()
    return helper.to_ha()


def _recompiled_body(tmp_path: Path, key: str, wire_body: dict[str, Any]) -> dict[str, Any]:
    """Wire body -> parse -> decompile -> recompile (a fresh bundle dir), and
    return the recompiled options body -- the exact pull -> adopt -> push
    round trip compile(decompile(x)) == x governs."""
    kind, _, _ = key.partition(":")
    obj = parse(wire_body, kind=kind)
    source = decompile_object(key, obj)
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text(
        f"from hassle import {kind}\n\n{source}", encoding="utf-8"
    )
    recompiled = compile_bundle(bundle_dir)
    return recompiled.objects[key].to_ha()


# -- §38.3 optional sensor-group kwargs --------------------------------------


def test_group_sensor_optional_fields_compile_into_body() -> None:
    body = _compiled_group_sensor(
        name="Average Temp",
        entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
        type="mean",
        ignore_non_numeric=True,
        unit_of_measurement="°C",
        device_class="temperature",
        state_class="measurement",
    )
    assert body["ignore_non_numeric"] is True
    assert body["unit_of_measurement"] == "°C"
    assert body["device_class"] == "temperature"
    assert body["state_class"] == "measurement"
    # The base shape is unchanged around them.
    assert body["name"] == "Average Temp"
    assert body["hide_members"] is False
    assert body["type"] == "mean"


def test_group_sensor_omitted_optional_fields_stay_out_of_body() -> None:
    """An OMITTED optional field is genuinely absent from the compiled body
    (one canonical form: the §38.3 fields are optional in HA's own schema and
    version-dependent, so omission -- not an explicit default -- is the
    canonical compiled shape, unlike the always-materialized
    `hide_members`/`all`)."""
    body = _compiled_group_sensor(name="Average Temp", entities=["sensor.a"], type="mean")
    for field in ("ignore_non_numeric", "unit_of_measurement", "device_class", "state_class"):
        assert field not in body


def test_group_sensor_explicit_none_optional_field_is_materialized() -> None:
    """Regression: an EXPLICIT ``field=None`` at the
    call site must land in the compiled body as an explicit null -- it is what
    the decompiler emits for a wire body that stores one, so dropping it
    silently would make recompile lossy."""
    body = _compiled_group_sensor(
        name="Average Temp",
        entities=["sensor.a"],
        type="mean",
        unit_of_measurement=None,
    )
    assert "unit_of_measurement" in body
    assert body["unit_of_measurement"] is None


# -- a wire body with an explicit null survives decompile -> compile --------


def test_wire_body_with_explicit_null_survives_decompile_compile(tmp_path: Path) -> None:
    """Regression: the exact break described --
    a `group_sensor` options body as a newer HA could store it, with the
    §38.3 optional fields present and some explicitly null, must round-trip
    decompile -> compile byte-stable (for ANY config, never drop data)."""
    wire_body: dict[str, Any] = {
        "name": "Average Temp",
        "entities": ["sensor.living_room_temperature", "sensor.bedroom_temperature"],
        "hide_members": False,
        "type": "mean",
        "ignore_non_numeric": False,
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": "measurement",
    }
    recompiled = _recompiled_body(tmp_path, "group_sensor:average_temp", wire_body)
    assert recompiled == wire_body
    assert sha256_hash(recompiled) == sha256_hash(wire_body)


def test_wire_body_with_explicit_null_on_unmodeled_field_survives(tmp_path: Path) -> None:
    """The same never-drop-data rule through the ``**fields`` catch-all: an explicit null
    on a field Hassle does not model at all (a future HA schema addition on
    any flavor) must survive the round trip verbatim too -- the fix is in
    `_declare_group_helper`'s shared body assembly, not per-kwarg."""
    wire_body: dict[str, Any] = {
        "name": "Entryway Top",
        "entities": ["cover.bay_window_top", "cover.garage_door"],
        "hide_members": False,
        "some_future_option": None,
    }
    recompiled = _recompiled_body(tmp_path, "group_cover:entryway_top", wire_body)
    assert recompiled == wire_body
    assert sha256_hash(recompiled) == sha256_hash(wire_body)
