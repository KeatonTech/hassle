"""Sanity check: turning `hassle/registry.py` into a package must not disturb the
`hassle.registry.entities` runtime shape frozen in the top-level DSL surface
(docs/dsl-extensions.md).

This is deliberately the simplest possible check -- if the registry-module ->
registry-package refactor breaks this, nothing else in the registry test suite
matters.
"""

from __future__ import annotations

from hassle.compiler.helpers import EntityRef


def test_entities_attribute_form_still_works() -> None:
    from hassle.registry import entities as e

    ref = e.sensor.hall_motion
    assert isinstance(ref, EntityRef)
    assert ref == "sensor.hall_motion"
    assert ref.domain == "sensor"
    assert ref.object_id == "hall_motion"


def test_entities_index_form_still_works() -> None:
    from hassle.registry import entities as e

    assert e.sensor["hall_motion"] == e.sensor.hall_motion


def test_entities_digit_leading_still_works() -> None:
    from hassle.registry import entities as e

    assert e.sensor._3d_printer == "sensor.3d_printer"
    assert e.sensor["3d_printer"] == e.sensor._3d_printer
