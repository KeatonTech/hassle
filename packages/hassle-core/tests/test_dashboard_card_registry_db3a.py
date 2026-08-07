"""CardSpec registration completeness for DB3a's layout/display batch.

Test contract (docs/internals/dashboards-design.md §6.1.1, F5): every builder
DB3a adds registers exactly one `CardSpec` row in `CARD_REGISTRY`, keyed by its
stored HA `type` string, and the row's shape (container/context_manager/
entity_params) matches what the builder actually does.
"""

from __future__ import annotations

import pytest

# Every HA type string DB3a's layout+display batch owns, and the DSL name that
# builds it -- importing `hassle.cards` (transitively, via the modules
# themselves) is what populates `CARD_REGISTRY` at import time.
import hassle.cards as _c  # noqa: F401  (import triggers registration)
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY, CardSpec, register_card

_DB3A_TYPES = {
    "vertical-stack": "c.vertical_stack",
    "horizontal-stack": "c.horizontal_stack",
    "grid": "c.grid",
    "conditional": "c.conditional",
    "entity-filter": "c.entity_filter",
    "entities": "c.entities",
    "glance": "c.glance",
    "tile": "c.tile",
    "entity": "c.entity",
    "button": "c.button",
    "heading": "c.heading",
}


def test_every_db3a_type_is_registered_exactly_once() -> None:
    for card_type in _DB3A_TYPES:
        assert card_type in CARD_REGISTRY, f"{card_type!r} missing from CARD_REGISTRY"


def test_registered_builder_names_match() -> None:
    for card_type, builder in _DB3A_TYPES.items():
        assert CARD_REGISTRY[card_type].builder == builder


def test_container_cards_are_context_managers_with_a_child_shape() -> None:
    containers = {"vertical-stack", "horizontal-stack", "grid"}
    for card_type in containers:
        spec = CARD_REGISTRY[card_type]
        assert spec.context_manager is True
        assert spec.container == "cards"

    for card_type in ("conditional", "entity-filter"):
        spec = CARD_REGISTRY[card_type]
        assert spec.context_manager is True
        assert spec.container == "card"


def test_leaf_cards_are_not_context_managers() -> None:
    leaves = {"entities", "glance", "tile", "entity", "button", "heading"}
    for card_type in leaves:
        spec = CARD_REGISTRY[card_type]
        assert spec.context_manager is False
        assert spec.container == "leaf"


def test_entity_params_match_the_entity_taking_options() -> None:
    assert CARD_REGISTRY["tile"].entity_params == ("entity",)
    assert CARD_REGISTRY["entity"].entity_params == ("entity",)
    assert CARD_REGISTRY["button"].entity_params == ("entity",)
    assert CARD_REGISTRY["entities"].entity_params == ("entities",)
    assert CARD_REGISTRY["glance"].entity_params == ("entities",)
    assert CARD_REGISTRY["entity-filter"].entity_params == ("entities",)
    assert CARD_REGISTRY["heading"].entity_params == ()


def test_registering_a_db3a_type_twice_raises() -> None:
    # SF-5 (review round): the previous version of this test could not fail
    # for what its name claimed (it asserted `"grid" in CARD_REGISTRY`, true
    # whether or not double-registration is actually rejected). This one
    # exercises the real guarantee directly, against one of DB3a's OWN
    # already-registered types: re-registering "grid" must raise, not
    # silently replace the row DB4/DB7 already read.
    with pytest.raises(ValueError, match="already registered"):
        register_card(CardSpec(type="grid", builder="c.grid", declared=frozenset({"type"})))
