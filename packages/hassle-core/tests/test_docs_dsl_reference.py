"""`docs/DSL.md` is generated from the golden cases under ``fixtures/dsl/``
and can never drift from reality -- the build fails if any name in
``hassle.__all__`` lacks a documented DSL<->compiled-YAML pair (or an
explicit, documented exemption).

See ``hassle.docs.dsl_reference`` for the generator and
``hassle.docs.construct_map`` for the case->construct mapping + exemption list.
"""

from __future__ import annotations

from pathlib import Path

import hassle
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY, ensure_builtin_families_loaded
from hassle.docs.construct_map import (
    CARD_TYPE_TO_CASES,
    EXEMPT_NAMES,
    NAME_TO_CASES,
    missing_card_types,
    missing_names,
)
from hassle.docs.dsl_reference import generate_dsl_reference

REPO_ROOT = Path(__file__).resolve().parents[3]
DSL_FIXTURES = REPO_ROOT / "fixtures" / "dsl"


def test_every_all_name_is_covered_or_exempt() -> None:
    """The docs coverage gate: every name in
    ``hassle.__all__`` either has >= 1 backing golden case, or is on the
    explicit, documented exemption list (error/trap classes -- see
    ``hassle.docs.construct_map`` for why each one is exempt)."""
    missing = missing_names(hassle.__all__)
    assert not missing, (
        f"hassle.__all__ names with no golden pair and no exemption: {sorted(missing)}"
    )


def test_exempt_names_are_still_all_actually_error_classes() -> None:
    # Guards against someone widening the exemption list to dodge the gate
    # instead of adding a fixture -- every currently exempt name really is a
    # compile-time trap/error class, not an ordinary construct.
    for name in EXEMPT_NAMES:
        assert name.endswith("Error"), (
            f"{name!r} is exempted from docs/DSL.md coverage but is not an "
            "Error class -- add a golden pair instead of exempting it."
        )


def test_name_to_cases_only_references_real_fixture_dirs() -> None:
    for name, cases in NAME_TO_CASES.items():
        for case in cases:
            bundle_dir = DSL_FIXTURES / case / "bundle"
            assert bundle_dir.is_dir(), f"{name!r} maps to non-existent case {case!r}"


def test_generate_dsl_reference_contains_every_construct_section() -> None:
    text = generate_dsl_reference(DSL_FIXTURES)
    for name in hassle.__all__:
        if name in EXEMPT_NAMES:
            continue
        assert f"`{name}`" in text, f"docs/DSL.md is missing a section for `{name}`"


def test_generate_dsl_reference_shows_dsl_and_yaml_pair() -> None:
    """Spot check: the `state` builder's section actually contains both a
    Python snippet and the compiled YAML/JSON it produces (agents and humans
    pattern-match on the pair, DESIGN §12)."""
    text = generate_dsl_reference(DSL_FIXTURES)
    idx = text.index("### `state`")
    section = text[idx : idx + 2000]
    assert "```python" in section
    assert "trigger" in section  # compiled shape appears somewhere in the pair


def test_generate_dsl_reference_documents_error_traps_separately() -> None:
    """Exempt names (error/trap classes) still appear in the doc -- just in a
    dedicated "Trap / error surface" section instead of a golden-pair section
    (DESIGN §12: error messages are part of the docs surface)."""
    text = generate_dsl_reference(DSL_FIXTURES)
    assert "Trap / error surface" in text or "error surface" in text.lower()
    for name in EXEMPT_NAMES:
        assert f"`{name}`" in text, f"exempt name {name!r} should still be documented"


def test_generate_dsl_reference_is_deterministic() -> None:
    a = generate_dsl_reference(DSL_FIXTURES)
    b = generate_dsl_reference(DSL_FIXTURES)
    assert a == b


# -- card reference section (dashboards-design.md §10) -----------------------


def test_every_card_registry_type_is_covered_or_gate_fails() -> None:
    """The card-reference docs coverage gate: every built-in card type DB3's
    builders registered has a `CARD_TYPE_TO_CASES` entry (mirrors
    `test_every_all_name_is_covered_or_exempt` for `hassle.__all__`)."""
    ensure_builtin_families_loaded()
    missing = missing_card_types(list(CARD_REGISTRY))
    assert not missing, f"card types with no golden pair in docs/DSL.md: {sorted(missing)}"


def test_card_type_to_cases_only_references_real_fixture_dirs() -> None:
    for card_type, cases in CARD_TYPE_TO_CASES.items():
        for case in cases:
            bundle_dir = DSL_FIXTURES / case / "bundle"
            assert bundle_dir.is_dir(), f"{card_type!r} maps to non-existent case {case!r}"


def test_generate_dsl_reference_contains_a_section_for_every_card_builder() -> None:
    ensure_builtin_families_loaded()
    text = generate_dsl_reference(DSL_FIXTURES)
    assert "## Card reference" in text
    for card_type in CARD_REGISTRY:
        builder_name = CARD_REGISTRY[card_type].builder
        assert f"### `{builder_name}`" in text, (
            f"docs/DSL.md is missing a card-reference section for {builder_name!r}"
        )


def test_generate_dsl_reference_shows_card_dsl_and_yaml_pair() -> None:
    """Spot check: `c.tile`'s card-reference section shows both the Python
    call and the compiled card body (same pattern-matchable pair as every
    other construct)."""
    text = generate_dsl_reference(DSL_FIXTURES)
    idx = text.index("### `c.tile`")
    section = text[idx : idx + 2000]
    assert "```python" in section
    assert '"type": "tile"' in section
