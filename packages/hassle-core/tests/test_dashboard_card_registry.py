"""The F5 card-type registry contract (design doc §6.1.1).

`CARD_REGISTRY` is the single table DB3 (registration), DB4 (emitter selection)
and DB7 (entity extraction) all read, so its *shape* contract needs pinning
before the three DB3 batches fan out — a family that merges with a row missing
`declared` silently costs DB4 its typed-kwarg/`extra=` split, and a family that
merges with `entity_params` holding Python parameter names rather than STORED
config keys silently costs DB7 its entity lint.

These tests are the mechanical enforcement of that contract. They are written
to keep passing as DB3 appends rows: every assertion iterates the registry
rather than naming a fixed set.
"""

from __future__ import annotations

import inspect
from typing import Any, get_args

from hassle.compiler.dashboards.card_registry import (
    CARD_REGISTRY,
    STRUCTURE_REGISTRY,
    CardSpec,
    ContainerShape,
    register_card,
)
from hassle.compiler.dashboards.structure import (
    _SECTION_DECLARED,  # pyright: ignore[reportPrivateUsage]
    _VIEW_DECLARED,  # pyright: ignore[reportPrivateUsage]
    section,
    view,
)

_ALL_ROWS: dict[str, CardSpec] = {**CARD_REGISTRY, **STRUCTURE_REGISTRY}


def test_card_spec_carries_a_declared_key_set() -> None:
    # The stored-key set a generic decompiler emitter needs to split typed
    # kwargs from `extra=`. Optional on the dataclass (so a row can be added in
    # one line) but REQUIRED of every real registration -- see below.
    assert "declared" in inspect.signature(CardSpec).parameters
    bare = CardSpec(type="x", builder="c.x")
    assert bare.declared == frozenset()


def test_every_registered_row_populates_declared() -> None:
    for key, spec in _ALL_ROWS.items():
        assert spec.declared, (
            f"registry row {key!r} ({spec.builder}) has an empty `declared` set. Every "
            "registration must list the stored keys its builder writes -- DB4's emitter "
            "needs it to split typed kwargs from `extra=` (design §6.1.1)."
        )


def test_every_registered_row_has_a_known_container_shape() -> None:
    shapes = set(get_args(ContainerShape))
    for key, spec in _ALL_ROWS.items():
        assert spec.container in shapes, key
        # A non-leaf container is always a `with` block in the DSL.
        if spec.container != "leaf":
            assert spec.context_manager, key


def test_entity_params_are_stored_keys_present_in_declared() -> None:
    # `entity_params` names STORED CONFIG KEYS, not Python parameter names --
    # the distinction DB7's extraction depends on. Every one of them must
    # therefore also appear in `declared`.
    for key, spec in _ALL_ROWS.items():
        for param in spec.entity_params:
            assert param in spec.declared, (
                f"{key!r}: entity_param {param!r} is not in `declared`. `entity_params` "
                "holds stored config keys, so each one is by definition a declared key."
            )


def test_structure_rows_are_kept_out_of_card_registry() -> None:
    # A decompiler looking up a stored card's `type` must never match a
    # structural pseudo-row.
    assert set(STRUCTURE_REGISTRY) & set(CARD_REGISTRY) == set()
    assert "structure:section" in STRUCTURE_REGISTRY
    # DB3a's `c.grid` card legitimately owns the bare "grid" type string; the
    # section pseudo-row stays namespaced so the two can never collide.
    assert "grid" in CARD_REGISTRY


def test_register_card_rejects_a_duplicate_type() -> None:
    import pytest

    spec = CardSpec(type="test-only-card", builder="c.test", declared=frozenset({"type"}))
    register_card(spec)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_card(CardSpec(type="test-only-card", builder="c.other"))
    finally:
        del CARD_REGISTRY["test-only-card"]


# ---------------------------------------------------------------------------
# The `extra=` shadow-protection invariant: a builder's DECLARED set must cover
# every keyword its own signature accepts. Reviewer note: the emission-order
# list and the DECLARED set drifting apart silently removes shadow protection,
# so the relationship is asserted rather than maintained by hand.
# ---------------------------------------------------------------------------
_NON_OPTION_KWARGS = frozenset({"extra"})


def _keyword_names(builder: Any) -> frozenset[str]:
    params = inspect.signature(builder).parameters
    return frozenset(params) - _NON_OPTION_KWARGS


def test_view_declared_covers_every_view_keyword() -> None:
    assert _keyword_names(view) <= _VIEW_DECLARED


def test_section_declared_covers_every_section_keyword() -> None:
    assert _keyword_names(section) <= _SECTION_DECLARED


def test_view_declared_covers_the_structural_keys_view_writes_itself() -> None:
    # BLOCK-2: `extra={"cards": ...}`/`{"sections": ...}`/`{"badges": ...}`
    # would be accepted and then silently overwritten by the view's own
    # assembly -- so they are declared keys too, even though they are not
    # keyword arguments.
    assert {"cards", "sections", "badges"} <= _VIEW_DECLARED
