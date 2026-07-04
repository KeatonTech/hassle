"""M1 test 8 — entity indexing form (DESIGN §5.2/§5.3).

`e.sensor["3d_printer"]` and `e.sensor._3d_printer` (attribute form, via the
digit-leading underscore-prefix rule) must compile to the same entity
reference. `hassle.registry.entities` is the runtime object `from hassle.registry
import entities as e` binds to; M3 layers *typed* stub classes on top of this
same runtime shape (this module is not itself generated/registry-driven — it
works for any domain/object_id, per DESIGN §5.2's "universal escape hatch").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import compile_bundle
from hassle.compiler.helpers import EntityRef
from hassle.registry import entities

_DSL = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_attribute_access_builds_entity_ref() -> None:
    ref = entities.sensor.hall_motion
    assert isinstance(ref, EntityRef)
    assert ref == "sensor.hall_motion"
    assert ref.domain == "sensor"
    assert ref.object_id == "hall_motion"


def test_index_access_builds_entity_ref() -> None:
    ref = entities.sensor["hall_motion"]
    assert isinstance(ref, EntityRef)
    assert ref == "sensor.hall_motion"


def test_attribute_and_index_are_equivalent() -> None:
    assert entities.light.hallway == entities.light["hallway"]
    assert entities.light.hallway.domain == entities.light["hallway"].domain
    assert entities.light.hallway.object_id == entities.light["hallway"].object_id


def test_digit_leading_object_id_underscore_prefix() -> None:
    # DESIGN §5.2: object_ids may start with a digit; the stub/accessor
    # convention prefixes with `_` (`e.sensor._3d_printer`) since `3d_printer`
    # is not a valid Python identifier. The underscore is stripped only when it
    # immediately precedes a digit.
    via_attr = entities.sensor._3d_printer
    via_index = entities.sensor["3d_printer"]
    assert via_attr == via_index == "sensor.3d_printer"
    assert via_attr.object_id == "3d_printer"


def test_leading_underscore_not_stripped_when_not_before_digit() -> None:
    # A real HA object_id can never start with `_` (DESIGN §5.2's
    # `(?!_)[\da-z_]+(?<!_)`), so this is unreachable in practice, but the
    # accessor's stripping rule must still be narrow: only underscore-then-digit
    # is special-cased, never a bare leading underscore.
    ref = entities.sensor._private
    assert ref == "sensor._private"


def test_domain_accessor_is_stable_and_reusable() -> None:
    # entities.sensor returns an equivalent accessor each time (not a singleton
    # requirement, just consistent behavior).
    assert entities.sensor.x == entities.sensor.x == "sensor.x"


@pytest.mark.parametrize("case", ["entity_attr_form", "entity_index_form"])
def test_attr_and_index_forms_compile_to_identical_ir(case: str) -> None:
    # End-to-end: two bundles, one using e.sensor.hall_motion (attr form), one
    # using e.sensor["hall_motion"] (index form), must compile to byte-identical
    # IR (M1 test 8's "compile to the same entity reference").
    result = compile_bundle(_DSL / case / "bundle")
    (obj,) = result.objects.values()
    body = obj.to_ha()
    assert body["triggers"] == [{"trigger": "state", "entity_id": "sensor.hall_motion", "to": "on"}]


def test_attr_and_index_forms_produce_byte_identical_ir() -> None:
    attr_result = compile_bundle(_DSL / "entity_attr_form" / "bundle")
    index_result = compile_bundle(_DSL / "entity_index_form" / "bundle")
    (attr_obj,) = attr_result.objects.values()
    (index_obj,) = index_result.objects.values()
    assert attr_obj.to_ha()["triggers"] == index_obj.to_ha()["triggers"]
