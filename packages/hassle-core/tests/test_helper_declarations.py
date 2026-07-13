"""Helper declarations (DESIGN §5.7) -- the model/builder layer.

These constructor functions build correct ``HelperConfig`` IR objects and a
usable :class:`EntityRef`. The §12 registration path (M1 integration pass,
``Registry.add_object`` + ``compile_registered``'s prebuilt stream) wires them
into ``compile_bundle(...).objects``; see
``packages/hassle-core/tests/test_prebuilt_registration.py`` for the
end-to-end golden coverage. These tests exercise the builder layer directly
(:func:`declared_helpers`), not through ``compile_bundle``.
"""

from __future__ import annotations

import pytest

from hassle.compiler.helpers import (
    EntityRef,
    counter,
    declared_helpers,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    reset_declared_helpers,
    schedule,
    timer,
)


@pytest.fixture(autouse=True)
def _clean_helpers():
    reset_declared_helpers()
    yield
    reset_declared_helpers()


def test_input_boolean_declares_a_helper_config() -> None:
    ref = input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account-group")
    assert isinstance(ref, EntityRef)
    assert ref == "input_boolean.guest_mode"
    assert ref.domain == "input_boolean"
    assert ref.object_id == "guest_mode"

    [helper] = declared_helpers()
    assert helper.kind() == "input_boolean"
    assert helper.object_key() == "input_boolean:guest_mode"
    assert helper.to_ha() == {
        "id": "guest_mode",
        "name": "Guest Mode",
        "icon": "mdi:account-group",
    }


def test_input_number_all_fields() -> None:
    input_number(
        id="target_temp",
        name="Target Temperature",
        min=15,
        max=25,
        step=0.5,
        unit_of_measurement="°C",
    )
    [helper] = declared_helpers()
    assert helper.to_ha() == {
        "id": "target_temp",
        "name": "Target Temperature",
        "min": 15,
        "max": 25,
        "step": 0.5,
        "unit_of_measurement": "°C",
    }


def test_entity_ref_usable_as_entity_id_string() -> None:
    # DESIGN §5.7: "referenced by import elsewhere" -- the returned ref is a
    # plain string wherever the DSL expects an entity id.
    from hassle.compiler.builders import state

    guest_mode = input_boolean(id="guest_mode", name="Guest Mode")
    trig = state(guest_mode).to("on")
    assert trig.to_trigger()["entity_id"] == "input_boolean.guest_mode"


def test_all_nine_helper_domains_declare() -> None:
    input_boolean(id="a", name="A")
    input_number(id="b", name="B")
    input_select(id="c", name="C", options=["x", "y"])
    input_text(id="d", name="D")
    input_datetime(id="e", name="E", has_date=True)
    input_button(id="f", name="F")
    counter(id="g", name="G")
    timer(id="h", name="H", duration="00:10:00")
    schedule(id="i", name="I")

    domains = {h.kind() for h in declared_helpers()}
    assert domains == {
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    }


def test_declared_helpers_reset_between_compiles() -> None:
    input_boolean(id="a", name="A")
    assert len(declared_helpers()) == 1
    reset_declared_helpers()
    assert declared_helpers() == []


def test_storage_helper_configs_normalize_to_what_ha_stores() -> None:
    """Owner field report (29 perpetually-spurious plan updates): HA's
    storage collections coerce input_number numerics to float, fill
    mode='slider' (input_number) / mode='text' (input_text) /
    restore=False (timer) when unset, and reformat timer durations to
    H:MM:SS without hour zero-padding. The compiled local IR must be
    byte-identical with what HA stores, or every helper diffs forever."""
    input_number(id="lux", name="Lux", min=50, max=1000, step=10)
    input_text(id="memo", name="Memo", min=0, max=30)
    timer(id="grace", name="Grace", duration="00:30:00")
    number, text, tmr = declared_helpers()

    body = number.to_ha()
    assert body["min"] == 50.0 and isinstance(body["min"], float)
    assert body["max"] == 1000.0 and isinstance(body["max"], float)
    assert body["step"] == 10.0 and isinstance(body["step"], float)
    assert body["mode"] == "slider"
    assert text.to_ha()["mode"] == "text"
    t = tmr.to_ha()
    assert t["duration"] == "0:30:00"
    assert t["restore"] is False


def test_explicit_helper_values_are_preserved_through_normalization() -> None:
    input_number(id="n", name="N", min=0, max=1, step=0.5, mode="box")
    timer(id="t", name="T", duration="1:05:00", restore=True)
    number, tmr = declared_helpers()
    assert number.to_ha()["mode"] == "box"
    t = tmr.to_ha()
    assert t["duration"] == "1:05:00" and t["restore"] is True
