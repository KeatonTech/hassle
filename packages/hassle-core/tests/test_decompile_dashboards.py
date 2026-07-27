"""``DashboardConfig`` decompiler test contract (docs/internals/dashboards-design.md
§6.2/§6.3, the F5 appendix §6.1.1, the raw ladder §5.5).

The corpus-driven round-trip/stability/coverage tests
(``test_roundtrip_corpus.py``, ``test_ir_roundtrip_corpus.py``,
``test_decompile_stable.py``, ``test_decompile_coverage.py``) already exercise
every one of the 12 ``fixtures/configs/dashboard_*.json`` fixtures generically
via ``tests/_corpus.py``'s new ``dashboard`` prefix. This module tests the
things the corpus can't pin on its own: the raw ladder table-tested at every
level (never rawing a parent merely because a child rawed), naming, the
generic CARD_REGISTRY-driven emitter's container-recursion tolerance (using a
locally-registered fake ``CardSpec`` -- no real card family has merged on this
base), the ``cond`` vocabulary, and import-line hygiene.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import pytest

import hassle
from hassle import cards as cards_module
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY, CardSpec
from hassle.decompiler import decompile_bundle
from hassle.decompiler.codegen import dashboard_function_name, decompile_object
from hassle.decompiler.dashboards import dashboard_source
from hassle.ir.models import DashboardConfig, parse


def _dashboard_obj(meta: Any, config: Any) -> DashboardConfig:
    obj = parse({"meta": meta, "config": config}, kind="dashboard")
    assert isinstance(obj, DashboardConfig)
    return obj


def _source(meta: Any, config: Any, ident: str = "dash") -> str:
    return dashboard_source(_dashboard_obj(meta, config), ident)


_BASE_META: dict[str, Any] = {"url_path": "test-dash", "title": "Test Dash"}


# ---------------------------------------------------------------------------
# Naming: slugify(title) -> slugify(url_path) -> dashboard_<n>
# ---------------------------------------------------------------------------


def test_name_prefers_title() -> None:
    obj = _dashboard_obj({"url_path": "climate-control", "title": "Climate Control"}, {"views": []})
    assert dashboard_function_name(obj, {}) == "climate_control"


def test_name_falls_back_to_url_path_when_no_title() -> None:
    obj = _dashboard_obj({"url_path": "guest-mode-panel"}, {"views": []})
    assert dashboard_function_name(obj, {}) == "guest_mode_panel"


def test_name_falls_back_to_blank_title() -> None:
    obj = _dashboard_obj({"url_path": "guest-mode-panel", "title": "   "}, {"views": []})
    assert dashboard_function_name(obj, {}) == "guest_mode_panel"


def test_name_falls_back_to_dashboard_n_for_default() -> None:
    obj = _dashboard_obj(None, {"views": []})
    assert dashboard_function_name(obj, {}) == "dashboard_default"


def test_name_dedupes_across_collisions() -> None:
    used: dict[str, int] = {}
    obj1 = _dashboard_obj({"url_path": "climate-control", "title": "Home"}, {"views": []})
    obj2 = _dashboard_obj({"url_path": "climate-control-2", "title": "Home"}, {"views": []})
    assert dashboard_function_name(obj1, used) == "home"
    assert dashboard_function_name(obj2, used) == "home_2"


def test_decompile_object_dispatches_dashboard_config() -> None:
    obj = _dashboard_obj({"url_path": "climate-control", "title": "Climate"}, {"views": []})
    src = decompile_object("dashboard:climate-control", obj)
    assert "@dashboard(" in src
    assert "def climate(" in src


# ---------------------------------------------------------------------------
# The whole-dashboard raw ladder
# ---------------------------------------------------------------------------


def test_unmodeled_top_level_falls_to_raw_dashboard() -> None:
    src = _source(_BASE_META, {"strategy": {"type": "original-states"}})
    assert "@raw_dashboard(url_path='test-dash')" in src
    assert "'strategy':" in src


def test_meta_with_unknown_key_falls_to_raw_dashboard() -> None:
    meta = {**_BASE_META, "invented_meta_key": "kept"}
    src = _source(meta, {"views": []})
    assert "@raw_dashboard(" in src
    assert "invented_meta_key" in src


def test_meta_without_url_path_falls_to_raw_dashboard() -> None:
    src = _source({"title": "No identity"}, {"views": []})
    assert "@raw_dashboard(default=True)" in src  # identity sentinel, no _key_id given


def test_config_with_extra_top_level_key_falls_to_raw_dashboard() -> None:
    src = _source(_BASE_META, {"views": [], "invented_config_key": "kept"})
    assert "@raw_dashboard(" in src
    assert "invented_config_key" in src


def test_default_dashboard_decompiles_typed() -> None:
    src = _source(None, {"views": []})
    assert "@dashboard(default=True)" in src
    assert "raw_dashboard" not in src


def test_well_formed_dashboard_never_goes_raw() -> None:
    src = _source(_BASE_META, {"views": []})
    assert "@dashboard(" in src
    assert "raw_dashboard" not in src


# ---------------------------------------------------------------------------
# Views: the F5 appendix's two coordination points + panel arity + extra=
# ---------------------------------------------------------------------------


def test_view_with_both_sections_and_cards_falls_to_raw_view() -> None:
    view = {"type": "sections", "sections": [], "cards": []}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src
    assert "with view(" not in src


def test_view_with_neither_sections_nor_cards_falls_to_raw_view() -> None:
    view = {"type": "sections", "title": "Empty"}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src


def test_masonry_view_with_neither_key_falls_to_raw_view() -> None:
    view = {"title": "Legacy", "path": "legacy"}  # no `type`, no `cards` either
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src


def test_panel_view_wrong_arity_falls_to_raw_view() -> None:
    view = {"type": "panel", "cards": [{"type": "unknown-a"}, {"type": "unknown-b"}]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src


def test_panel_view_exact_arity_decompiles_typed() -> None:
    view = {"type": "panel", "cards": [{"type": "unknown-a"}]}
    src = _source(_BASE_META, {"views": [view]})
    assert "with view(type='panel'):" in src
    assert "raw_view" not in src
    assert "raw_card({'type': 'unknown-a'})" in src


def test_view_unknown_key_uses_extra_not_raw() -> None:
    view = {"type": "sections", "sections": [], "invented_view_key": {"deep": "kept"}}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view" not in src
    assert "with view(" in src
    assert "extra={'invented_view_key': {'deep': 'kept'}}" in src


def test_view_type_none_emits_legacy_masonry() -> None:
    view = {"title": "Main", "cards": []}  # no `type` key at all
    src = _source(_BASE_META, {"views": [view]})
    assert "with view(type=None, title='Main'):" in src


def test_sections_type_omits_redundant_type_kwarg() -> None:
    view = {"type": "sections", "sections": []}
    src = _source(_BASE_META, {"views": [view]})
    assert "with view():" in src


def test_view_legacy_bare_string_badge_falls_to_raw_view() -> None:
    view = {
        "type": "sections",
        "sections": [],
        "badges": ["light.hallway"],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src
    assert "badge(" not in src


def test_view_empty_badges_list_falls_to_raw_view() -> None:
    # `view()` only ever sets `badges` when >= 1 was recorded -- an explicit
    # empty list is not a shape `view()` can reproduce.
    view = {"type": "sections", "sections": [], "badges": []}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src


def test_view_modern_object_badge_decompiles_typed() -> None:
    view = {
        "type": "sections",
        "sections": [],
        "badges": [{"type": "entity", "entity": "binary_sensor.motion"}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view" not in src
    assert "badge(e.binary_sensor.motion)" in src


def test_view_dict_badge_with_extra_keys_passes_through_verbatim() -> None:
    badge_dict = {"type": "entity", "entity": "light.hallway", "name": "Hallway"}
    view = {"type": "sections", "sections": [], "badges": [badge_dict]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view" not in src
    assert "badge({'type': 'entity', 'entity': 'light.hallway', 'name': 'Hallway'})" in src


# ---------------------------------------------------------------------------
# Sections: stricter than view -- ANY unmodeled own key forces raw_section
# ---------------------------------------------------------------------------


def test_section_wrong_type_falls_to_raw_section() -> None:
    view = {"type": "sections", "sections": [{"type": "not-grid", "cards": []}]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section(" in src


def test_section_missing_cards_key_falls_to_raw_section() -> None:
    view = {"type": "sections", "sections": [{"type": "grid"}]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section(" in src


def test_section_unknown_key_falls_to_raw_section_not_extra() -> None:
    section = {"type": "grid", "cards": [], "invented_section_key": ["kept"]}
    view = {"type": "sections", "sections": [section]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section(" in src
    assert "extra=" not in src  # section has no extra= escape in this ladder


def test_section_column_span_decompiles_typed() -> None:
    section = {"type": "grid", "column_span": 2, "cards": []}
    view = {"type": "sections", "sections": [section]}
    src = _source(_BASE_META, {"views": [view]})
    assert "with section(column_span=2):" in src
    assert "raw_section" not in src


def test_section_with_raw_card_child_stays_typed_around_it() -> None:
    """Container-recursion tolerance at the section level: an unknown card
    inside an otherwise well-formed section never forces the section (or the
    enclosing view) raw."""
    section = {"type": "grid", "cards": [{"type": "custom:bubble-card", "x": 1}]}
    view = {"type": "sections", "sections": [section]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section" not in src
    assert "raw_view" not in src
    assert "with section():" in src
    assert "raw_card({'type': 'custom:bubble-card', 'x': 1})" in src


# ---------------------------------------------------------------------------
# Cards: unknown type -> raw_card (a type string absent from CARD_REGISTRY)
# ---------------------------------------------------------------------------


def test_unknown_card_type_falls_to_raw_card() -> None:
    # "someday-new-card" stands in for a built-in type from a future HA
    # release Hassle doesn't know yet -- absent from CARD_REGISTRY, so it
    # must round-trip via raw_card, never error (DESIGN §2.3).
    view = {
        "type": "sections",
        "sections": [
            {"type": "grid", "cards": [{"type": "someday-new-card", "entity": "light.x"}]}
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'someday-new-card', 'entity': " in src


def test_registered_card_type_emits_the_typed_builder_not_raw() -> None:
    # The registry-driven inverse of the test above: with DB3's families
    # merged, a stored tile emits `c.tile(...)` (this test replaced the
    # empty-registry-era expectation that tile fell to raw_card).
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "tile", "entity": "light.x"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "c.tile(entity=e.light.x)" in src
    assert "raw_card" not in src


def test_custom_card_fixture_asserts_raw_fallback_exactly() -> None:
    """Backstop proof (task item 6): the corpus's custom-card fixture is
    EXPECTED to decompile with `raw_card` for every card -- a coverage
    exception on purpose, not a bug."""
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parents[3] / "fixtures" / "configs" / "dashboard_custom_card.json"
    )
    config = json.loads(fixture_path.read_text(encoding="utf-8"))
    obj = parse(config, kind="dashboard")
    assert isinstance(obj, DashboardConfig)
    src = dashboard_source(obj, "custom_cards")
    # The two custom: cards raw-fall; the plain tile beside them now emits
    # its typed builder (DB3's families are merged), proving the ladder
    # never raws a sibling merely because a custom card sits next to it.
    assert src.count("raw_card(") == 2  # mushroom-entity-card and bubble-card
    assert "custom:mushroom-entity-card" in src
    assert "custom:bubble-card" in src
    assert "c.tile(" in src
    assert "raw_view" not in src and "raw_section" not in src and "raw_dashboard" not in src


def test_strategy_fixture_asserts_raw_fallback_exactly() -> None:
    """Backstop proof (task item 6): the strategy-dashboard fixture has no
    `views` key at all -- the whole object MUST be `@raw_dashboard`."""
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parents[3] / "fixtures" / "configs" / "dashboard_strategy.json"
    )
    config = json.loads(fixture_path.read_text(encoding="utf-8"))
    obj = parse(config, kind="dashboard")
    assert isinstance(obj, DashboardConfig)
    src = dashboard_source(obj, "strategy_dashboard")
    assert src.startswith("@raw_dashboard(url_path='auto-generated')")
    assert "'strategy': {'type': 'original-states'}" in src


# ---------------------------------------------------------------------------
# The generic CARD_REGISTRY-driven emitter -- exercised via a locally
# registered fake CardSpec (no real card family has merged on this base).
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _fake_stack(
    *, title: Any = None, visibility: Any = None, extra: dict[str, Any] | None = None
) -> Generator[None]:  # pragma: no cover -- never actually called, only introspected
    yield


def _fake_tile(
    entity: str, *, color: Any = None, visibility: Any = None, extra: dict[str, Any] | None = None
) -> None:  # pragma: no cover -- never actually called, only introspected
    pass


def _fake_entities_varargs(*rows: Any, title: Any = None) -> None:  # pragma: no cover
    pass


def _fake_entities_required_list(
    entities: list[Any], *, title: Any = None
) -> None:  # pragma: no cover
    # Stand-in for the real `entities`/`glance`/`history-graph`/.../`entity-
    # filter` family (DB3 coordination note): the stored `entities` key is
    # ALWAYS materialized (even `[]`) by the real compiler, never omitted --
    # modeled here as a REQUIRED (no-default) list parameter, so a stored
    # card lacking the key entirely is correctly unrepresentable.
    pass


@contextlib.contextmanager
def _fake_conditional(
    conditions: list[Any], *, extra: dict[str, Any] | None = None
) -> Generator[None]:  # pragma: no cover
    # Stand-in for the real `conditional` card (DB3 coordination note): a
    # REQUIRED `conditions` list plus exactly one child card stored under a
    # single-dict `card:` key (container="card") -- the CardSpec's own
    # `child_key`, never a signature parameter of the builder itself.
    yield


@dataclass(frozen=True)
class _CardSpecWithDeclared:
    """Duck-typed stand-in for a FUTURE ``CardSpec`` carrying the optional
    ``declared`` field (a parallel fix round is adding it) -- this base's own
    ``CardSpec`` has no such field at all, so the generic emitter's
    ``getattr(spec, "declared", frozenset())`` fallback is what's under test
    here, not the real dataclass."""

    type: str
    builder: str
    entity_params: tuple[str, ...]
    container: str
    context_manager: bool
    declared: frozenset[str]


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cards_module, "fake_stack", _fake_stack, raising=False)
    monkeypatch.setattr(cards_module, "fake_tile", _fake_tile, raising=False)
    monkeypatch.setattr(cards_module, "fake_entities", _fake_entities_varargs, raising=False)
    monkeypatch.setattr(hassle, "fake_top_level_leaf", _fake_tile, raising=False)
    monkeypatch.setattr(
        cards_module, "fake_entities_required", _fake_entities_required_list, raising=False
    )
    monkeypatch.setattr(cards_module, "fake_conditional", _fake_conditional, raising=False)
    monkeypatch.setitem(
        CARD_REGISTRY,
        "fake-stack",
        CardSpec(
            type="fake-stack",
            builder="c.fake_stack",
            container="cards",
            context_manager=True,
        ),
    )
    monkeypatch.setitem(
        CARD_REGISTRY,
        "fake-tile",
        CardSpec(type="fake-tile", builder="c.fake_tile", entity_params=("entity",)),
    )
    monkeypatch.setitem(
        CARD_REGISTRY,
        "fake-entities",
        CardSpec(type="fake-entities", builder="c.fake_entities"),
    )
    monkeypatch.setitem(
        CARD_REGISTRY,
        "fake-tile-declared",
        _CardSpecWithDeclared(
            type="fake-tile-declared",
            builder="c.fake_tile",
            entity_params=("entity",),
            container="leaf",
            context_manager=False,
            declared=frozenset({"entity", "color"}),
        ),
    )
    monkeypatch.setitem(
        CARD_REGISTRY,
        "fake-entities-required",
        CardSpec(type="fake-entities-required", builder="c.fake_entities_required"),
    )
    monkeypatch.setitem(
        CARD_REGISTRY,
        "fake-conditional",
        CardSpec(
            type="fake-conditional",
            builder="c.fake_conditional",
            container="card",
            context_manager=True,
        ),
    )


def test_known_leaf_card_decompiles_with_entity_resolver(fake_registry: None) -> None:
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "fake-tile", "entity": "light.kitchen"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.fake_tile(entity=e.light.kitchen)" in src


def test_known_leaf_card_leftover_key_uses_extra_when_no_declared_field(
    fake_registry: None,
) -> None:
    # `fake-tile`'s CardSpec has no `declared` field (this base's shape) --
    # its REQUIRED param (`entity`, no default) is still resolved by name
    # (a call can't omit it), but the OPTIONAL `color` routes through
    # `extra=` wholesale, matching the documented fallback behavior.
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [{"type": "fake-tile", "entity": "light.kitchen", "color": "red"}],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.fake_tile(entity=e.light.kitchen, extra={'color': 'red'})" in src


def test_known_leaf_card_with_declared_field_splits_known_from_extra(fake_registry: None) -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "fake-tile-declared",
                        "entity": "light.kitchen",
                        "color": "red",
                        "unknown_option": 1,
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.fake_tile(entity=e.light.kitchen, color='red', extra={'unknown_option': 1})" in src


def test_known_container_card_wraps_unknown_child_as_raw_card(fake_registry: None) -> None:
    """Container-recursion tolerance at the CARD_REGISTRY level: a known
    container whose child is an unknown type stays typed, wrapping raw_card
    -- never forces the container (or its enclosing section/view) raw."""
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "fake-stack",
                        "title": "Stack",
                        "cards": [{"type": "still-unknown", "x": 1}],
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section" not in src and "raw_view" not in src
    # `fake_stack` has no required params at all, so `title` (not `entity`)
    # falls through to `extra=` wholesale (no `declared` field on this
    # base's CardSpec) -- the container itself still stays typed.
    assert "with c.fake_stack(extra={'title': 'Stack'}):" in src
    assert "raw_card({'type': 'still-unknown', 'x': 1})" in src


def test_container_card_missing_own_child_key_falls_to_raw_card(fake_registry: None) -> None:
    view = {
        "type": "sections",
        "sections": [
            {"type": "grid", "cards": [{"type": "fake-stack", "title": "No children key"}]}
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'fake-stack', 'title': 'No children key'})" in src


def test_varargs_builder_degrades_to_raw_card(fake_registry: None) -> None:
    """A builder shaped with `*args` (the entities-card row convention, §5.3)
    can't be driven generically off a fixed key->kwarg mapping -- degrades
    to raw_card rather than guessing at a card-specific calling convention."""
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "fake-entities", "title": "x"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'fake-entities', 'title': 'x'})" in src


def test_missing_required_positional_param_degrades_to_raw_card(fake_registry: None) -> None:
    # `fake-tile`'s builder requires `entity` (no default); a stored card
    # missing it can't safely be called.
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "fake-tile"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'fake-tile'})" in src


# ---------------------------------------------------------------------------
# DB3 coordination points (review round, forward-compatibility): several
# real card families ALWAYS materialize a particular list key (`entities`
# for the entities/glance/history-graph/statistics-graph/calendar/logbook/
# map/picture-glance/entity-filter family, `conditions` for `conditional`) --
# a stored card of one of those types LACKING the key is unrepresentable
# through the typed builder (recompiling would materialize the key where the
# original had none, breaking I3). These are already handled by the SAME
# "a required (no-default) parameter with no source value -> raw_card"
# mechanism proven above -- no code change needed, just modeled here with
# fake builders whose required param stands in for the real always-
# materialized key, since no real family has landed on this base yet.
# ---------------------------------------------------------------------------


def test_entities_shaped_card_missing_its_list_key_falls_to_raw_card(fake_registry: None) -> None:
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "fake-entities-required", "title": "x"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'fake-entities-required', 'title': 'x'})" in src


def test_entities_shaped_card_with_its_list_key_present_decompiles_typed(
    fake_registry: None,
) -> None:
    # The always-materialized key is PRESENT (even empty) -- fully
    # representable through the typed builder.
    view = {
        "type": "sections",
        "sections": [
            {"type": "grid", "cards": [{"type": "fake-entities-required", "entities": []}]}
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.fake_entities_required(entities=[])" in src


def test_conditional_shaped_card_missing_conditions_key_falls_to_raw_card(
    fake_registry: None,
) -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [{"type": "fake-conditional", "card": {"type": "unknown-child"}}],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card(" in src
    assert "c.fake_conditional" not in src


def test_conditional_shaped_card_reads_the_single_dict_child_shape(fake_registry: None) -> None:
    """The conditional card's child is stored under a single-dict `card:`
    key (container="card", DB3 coordination note) -- not a list -- and the
    child card, even an unknown type, stays container-recursion tolerant."""
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "fake-conditional",
                        "conditions": [{"condition": "state", "entity": "x", "state": "on"}],
                        "card": {"type": "unknown-child"},
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "with c.fake_conditional(" in src
    assert "raw_card({'type': 'unknown-child'})" in src


def test_conditional_shaped_card_with_legacy_list_child_falls_back_defensively(
    fake_registry: None,
) -> None:
    """Defensive handling for a legacy/malformed shape: if a `container="card"`
    row's own child were ever stored as a LIST rather than a single dict, the
    whole card degrades to `raw_card` (never crashes, never guesses)."""
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "fake-conditional",
                        "conditions": [{"condition": "state", "entity": "x", "state": "on"}],
                        "card": [{"type": "unknown-child"}],  # legacy/malformed: a list, not a dict
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "c.fake_conditional" not in src
    assert "raw_card(" in src


# ---------------------------------------------------------------------------
# The `cond` vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"condition": "state", "entity": "light.x", "state": "on"}, "cond.state(e.light.x, 'on')"),
        (
            {"condition": "state", "entity": "light.x", "state_not": "off"},
            "cond.state(e.light.x, not_='off')",
        ),
        (
            {"condition": "state", "entity": "light.x", "state": "on", "state_not": "off"},
            "cond.state(e.light.x, 'on', not_='off')",
        ),
        ({"condition": "state", "entity": "light.x"}, "cond.state(e.light.x)"),
        (
            {"condition": "numeric_state", "entity": "sensor.t", "above": 20, "below": 30},
            "cond.numeric(e.sensor.t, above=20, below=30)",
        ),
        (
            {"condition": "screen", "media_query": "(min-width: 1000px)"},
            "cond.screen('(min-width: 1000px)')",
        ),
        ({"condition": "user", "users": ["u1", "u2"]}, "cond.user('u1', 'u2')"),
    ],
)
def test_cond_shapes_decompile_typed(condition: dict[str, Any], expected: str) -> None:
    # View-level `visibility=` is processed generically regardless of
    # CARD_REGISTRY (unlike card-level visibility, only handled for a KNOWN
    # card), so it's the simplest vehicle for testing the `cond` vocabulary
    # in isolation.
    view = {"type": "sections", "sections": [], "visibility": [condition]}
    src = _source(_BASE_META, {"views": [view]})
    assert "cond." in src
    assert expected in src


def test_cond_and_or_not_combine_recursively() -> None:
    condition = {
        "condition": "and",
        "conditions": [
            {"condition": "state", "entity": "light.x", "state": "on"},
            {
                "condition": "or",
                "conditions": [{"condition": "screen", "media_query": "(min-width: 1px)"}],
            },
        ],
    }
    view = {"type": "sections", "sections": [], "visibility": [condition]}
    src = _source(_BASE_META, {"views": [view]})
    assert "cond.all(cond.state(e.light.x, 'on'), cond.any(cond.screen('(min-width: 1px)')))" in src


def test_unknown_condition_kind_round_trips_as_verbatim_dict() -> None:
    condition = {"condition": "future_kind", "some_field": 1}
    view = {"type": "sections", "sections": [], "visibility": [condition]}
    src = _source(_BASE_META, {"views": [view]})
    assert "cond." not in src
    assert "visibility=[{'condition': 'future_kind', 'some_field': 1}]" in src


def test_and_or_not_with_unmodeled_sub_condition_stays_verbatim() -> None:
    # A sub-condition that isn't itself decompilable forces the WHOLE
    # combining condition to stay a literal dict too (never a partial
    # `cond.all(cond.state(...), {...})` mix -- `cond.all` takes only
    # `cond.*`/dict conditions, so this is just choosing the dict form).
    condition = {
        "condition": "and",
        "conditions": [
            {"condition": "state", "entity": "light.x", "state": "on"},
            {"condition": "future_kind"},
        ],
    }
    view = {"type": "sections", "sections": [], "visibility": [condition]}
    src = _source(_BASE_META, {"views": [view]})
    assert "cond.all(" not in src


# ---------------------------------------------------------------------------
# Import hygiene: `from hassle import cards as c` / `from hassle.cards import
# cond` only when used.
# ---------------------------------------------------------------------------


def test_no_cards_or_cond_import_when_unused() -> None:
    obj = _dashboard_obj(_BASE_META, {"views": []})
    src = decompile_bundle({obj.object_key(): obj})
    assert "from hassle import cards as c" not in src
    assert "from hassle.cards import cond" not in src


def test_cond_import_emitted_when_a_condition_is_used() -> None:
    view = {
        "type": "sections",
        "sections": [],
        "visibility": [{"condition": "screen", "media_query": "(min-width: 1px)"}],
    }
    obj = _dashboard_obj(_BASE_META, {"views": [view]})
    src = decompile_bundle({obj.object_key(): obj})
    assert "from hassle.cards import cond" in src
    assert "from hassle import cards as c" not in src  # no known card builder used here


def test_cards_import_emitted_when_a_known_card_builder_is_used(fake_registry: None) -> None:
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "fake-tile", "entity": "light.kitchen"}]}],
    }
    obj = _dashboard_obj(_BASE_META, {"views": [view]})
    src = decompile_bundle({obj.object_key(): obj})
    assert "from hassle import cards as c" in src
