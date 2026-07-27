"""``DashboardConfig`` decompiler test contract (docs/internals/dashboards-design.md
§6.2/§6.3, the F5 appendix §6.1.1, the raw ladder §5.5).

The corpus-driven round-trip/stability/coverage tests
(``test_roundtrip_corpus.py``, ``test_ir_roundtrip_corpus.py``,
``test_decompile_stable.py``, ``test_decompile_coverage.py``) already exercise
every one of the 12 ``fixtures/configs/dashboard_*.json`` fixtures generically
via ``tests/_corpus.py``'s new ``dashboard`` prefix. This module tests the
things the corpus can't pin on its own: the raw ladder table-tested at every
level (never rawing a parent merely because a child rawed), naming, the
generic CARD_REGISTRY-driven emitter's container-recursion tolerance, the
varargs-rows and single-dict-child container conventions (exercised against
both the REAL DB3 card builders now merged and, for edge cases no real
builder happens to exercise, a locally-registered fake ``CardSpec``), the
``cond`` vocabulary, and import-line hygiene.
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
# BLOCK-1 (reviewer finding): a modeled key PRESENT with JSON null is a
# different stored shape than the key being ABSENT, but every builder's own
# `put()`/skip-on-None convention means passing `key=None` explicitly is
# IDENTICAL, at compile time, to omitting the kwarg entirely -- there is no
# typed-builder call shape that reproduces an explicit null for a modeled
# key. Silently treating "present as null" the same as "absent" (a bare
# `.pop(key, None)` + `is not None` check) is therefore an I3 violation: the
# key would recompile as absent, not null. The only correct handling is the
# raw ladder, exactly like the empty-badges/always-materialized-key
# precedents in the same module -- escalate the whole node.
# ---------------------------------------------------------------------------


def test_meta_icon_explicit_null_falls_to_raw_dashboard() -> None:
    meta = {**_BASE_META, "icon": None}
    src = _source(meta, {"views": []})
    assert "@raw_dashboard(" in src
    assert "'icon': None" in src


def test_meta_show_in_sidebar_explicit_null_falls_to_raw_dashboard() -> None:
    meta = {**_BASE_META, "show_in_sidebar": None}
    src = _source(meta, {"views": []})
    assert "@raw_dashboard(" in src


def test_meta_field_absent_still_decompiles_typed() -> None:
    # Sanity check for the fix's OTHER half: a genuinely ABSENT optional meta
    # field (never present at all) is unaffected -- only PRESENT-with-null
    # forces raw.
    src = _source(_BASE_META, {"views": []})  # no icon/show_in_sidebar/require_admin at all
    assert "@dashboard(" in src
    assert "raw_dashboard" not in src


def test_full_round_trip_for_envelope_with_meta_icon_null() -> None:
    """The reviewer's concrete reproduction: `DirectBackend.
    _dashboard_registry_payload` sends `icon: None` on every update; if HA
    persists it verbatim, a pulled dashboard's `meta.icon` is `None` --
    `compile(decompile(x)) == x` must still hold for that envelope."""
    import tempfile
    from pathlib import Path

    from hassle.compiler.bundle import compile_bundle
    from hassle.decompiler import decompile_bundle
    from hassle.ir.canonical import sha256_hash

    config = {
        "meta": {**_BASE_META, "icon": None},
        "config": {"views": []},
    }
    obj = _dashboard_obj(config["meta"], config["config"])
    src = decompile_bundle({obj.object_key(): obj})
    assert "@raw_dashboard(" in src

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(src, encoding="utf-8")
        result = compile_bundle(Path(tmp))
    assert len(result.objects) == 1
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(config)


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


# --- BLOCK-1: present-but-null modeled keys (see the module note above) ---


def test_view_title_explicit_null_falls_to_raw_view() -> None:
    view = {"type": "sections", "sections": [], "title": None}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src
    assert "'title': None" in src


def test_view_title_absent_still_decompiles_typed() -> None:
    view = {"type": "sections", "sections": []}  # no `title` key at all
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view" not in src
    assert "with view():" in src


def test_view_visibility_explicit_null_falls_to_raw_view() -> None:
    view = {"type": "sections", "sections": [], "visibility": None}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src


def test_view_type_explicit_null_falls_to_raw_view() -> None:
    # Extra site found during the same audit (not in the reviewer's
    # explicit list, same bug class): `view()`'s `type=None` sentinel means
    # "the `type` key is entirely ABSENT" (the legacy masonry shape) -- it
    # has no shape that reproduces a `type` key PRESENT with an explicit
    # null, which is a different stored dict than one missing the key.
    view = {"type": None, "cards": []}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src
    assert "'type': None" in src


def test_view_badges_explicit_null_falls_to_raw_view() -> None:
    # Extra site found during the same audit: `view()` only ever OMITS
    # `badges` (zero recorded) or sets it to a real non-empty list -- never
    # an explicit null.
    view = {"type": "sections", "sections": [], "badges": None}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_view(" in src


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


# --- BLOCK-1: present-but-null modeled keys (see the module note above) ---


def test_section_column_span_explicit_null_falls_to_raw_section() -> None:
    section = {"type": "grid", "column_span": None, "cards": []}
    view = {"type": "sections", "sections": [section]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section(" in src
    assert "'column_span': None" in src


def test_section_column_span_absent_still_decompiles_typed() -> None:
    section = {"type": "grid", "cards": []}  # no `column_span` key at all
    view = {"type": "sections", "sections": [section]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section" not in src
    assert "with section():" in src


def test_section_visibility_explicit_null_falls_to_raw_section() -> None:
    section = {"type": "grid", "visibility": None, "cards": []}
    view = {"type": "sections", "sections": [section]}
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_section(" in src


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


# --- BLOCK-1: present-but-null modeled keys (see the module note above) ---


def test_card_visibility_explicit_null_falls_to_raw_card() -> None:
    view = {
        "type": "sections",
        "sections": [
            {"type": "grid", "cards": [{"type": "tile", "entity": "light.x", "visibility": None}]}
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card(" in src
    assert "'visibility': None" in src
    assert "c.tile" not in src


def test_card_visibility_absent_still_decompiles_typed() -> None:
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "tile", "entity": "light.x"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.tile(entity=e.light.x)" in src


# ---------------------------------------------------------------------------
# Varargs-rows cards (entities/glance/history_graph/statistics_graph/
# calendar/logbook/map/picture_glance) -- the stored `entities:` list maps
# onto the builder's `*rows`/`*entities` VAR_POSITIONAL parameter. The
# builder's OWN parameter name and the stored key sometimes coincide
# (history_graph's `*entities` <-> stored `entities`) and sometimes don't
# (entities/glance's `*rows` <-> stored `entities`) -- both are exercised
# against the REAL DB3 builders now merged into CARD_REGISTRY.
# ---------------------------------------------------------------------------


def test_entities_card_rows_decompile_as_positional_args() -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "entities",
                        "title": "Switches",
                        "entities": [
                            "switch.kitchen",
                            {"type": "divider"},
                            "switch.bedroom",
                        ],
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert (
        "c.entities(e.switch.kitchen, {'type': 'divider'}, e.switch.bedroom, title='Switches')"
        in src
    )


def test_glance_card_rows_decompile_as_positional_args() -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {"type": "glance", "entities": ["sensor.temperature", "sensor.humidity"]}
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.glance(e.sensor.temperature, e.sensor.humidity)" in src


def test_history_graph_rows_param_name_matches_stored_key() -> None:
    # Unlike entities/glance's `*rows`, `history_graph`'s VAR_POSITIONAL
    # parameter is itself named `entities` (matching the stored key
    # directly) -- both spellings must resolve to the same rows mechanism.
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "history-graph",
                        "entities": ["sensor.temperature", "sensor.humidity"],
                        "hours_to_show": 24,
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.history_graph(e.sensor.temperature, e.sensor.humidity, hours_to_show=24)" in src


def test_map_card_rows_decompile_as_positional_args() -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "map",
                        # `c.map()` has no `title=` kwarg at all (HA's real
                        # map card schema doesn't support one) -- it round-
                        # trips through `extra=`, proving that path still
                        # works alongside the new positional rows.
                        "title": "Home Devices",
                        "entities": ["device_tracker.phone", "device_tracker.car"],
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert (
        "c.map(e.device_tracker.phone, e.device_tracker.car, extra={'title': 'Home Devices'})"
        in src
    )


def test_entities_shaped_card_missing_its_always_materialized_key_stays_raw() -> None:
    """DB3-fix re-verification (task item 3): `entities`/`glance`/etc. ALWAYS
    materialize their `entities:` key (even `[]`) -- a stored card lacking
    the key entirely is unrepresentable and must stay `raw_card`."""
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "glance"}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'glance'})" in src


def test_entities_shaped_card_with_empty_rows_list_decompiles_typed() -> None:
    # The key IS present, just empty -- fully representable (`c.glance()`
    # with zero rows still materializes `"entities": []`).
    view = {
        "type": "sections",
        "sections": [{"type": "grid", "cards": [{"type": "glance", "entities": []}]}],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "c.glance()" in src


def test_conditional_card_conditions_rows_and_dict_child_decompile_typed() -> None:
    """The `conditional` card: `conditions=` via the varargs `*conditions`
    parameter (rendered through the `cond` inverter, dict fallback for an
    unmodeled condition shape) plus exactly one child under the single-dict
    `card:` key -- a `with c.conditional(...):` block wrapping the child."""
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "conditional",
                        "conditions": [
                            {
                                "condition": "state",
                                "entity": "binary_sensor.motion_detector",
                                "state": "on",
                            }
                        ],
                        "card": {"type": "markdown", "content": "Motion detected!"},
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "raw_section" not in src
    assert "with c.conditional(cond.state(e.binary_sensor.motion_detector, 'on')):" in src
    assert "c.markdown(content='Motion detected!')" in src


def test_conditional_card_unmodeled_condition_shape_falls_back_to_dict_literal() -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "conditional",
                        "conditions": [{"condition": "future_kind", "x": 1}],
                        "card": {"type": "markdown", "content": "hi"},
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "with c.conditional({'condition': 'future_kind', 'x': 1}):" in src


def test_conditional_card_missing_always_materialized_conditions_key_stays_raw() -> None:
    view = {
        "type": "sections",
        "sections": [
            {"type": "grid", "cards": [{"type": "conditional", "card": {"type": "markdown"}}]}
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card({'type': 'conditional'" in src


def test_entity_filter_with_child_card_decompiles_typed() -> None:
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "entity-filter",
                        "entities": ["light.living_room", "light.bedroom"],
                        "state_filter": ["on"],
                        "card": {"type": "markdown", "content": "hi"},
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "with c.entity_filter(" in src
    assert "c.markdown(content='hi')" in src


def test_entity_filter_with_no_card_child_decompiles_as_zero_children() -> None:
    """`entity_filter` (unlike `conditional`) legitimately holds ZERO
    children -- HA's own `push_container(..., child_is_list=False)`
    convention leaves the `card:` key entirely absent for zero, present for
    one (DB3-fix SF-2). A missing `card:` key must decompile to an EMPTY
    `with` block (`pass`), never force `raw_card`."""
    view = {
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "entity-filter",
                        "entities": ["climate.living_room", "climate.bedroom"],
                        "state_filter": ["off"],
                        "show_empty": False,
                    }
                ],
            }
        ],
    }
    src = _source(_BASE_META, {"views": [view]})
    assert "raw_card" not in src
    assert "with c.entity_filter(" in src
    assert "pass" in src


def test_entity_filter_dashboard_fixture_decompiles_both_containers_typed() -> None:
    """The corpus fixture exercising both entity_filter shapes at once: BOTH
    `with c.entity_filter(...):` containers decompile typed now (one wraps a
    `glance` presentation card that itself stays `raw_card` -- it has no
    `entities:` key at all, the always-materialized-key rule, not a
    regression; the other has zero children). Container-recursion tolerance:
    neither entity_filter is forced raw by its child/lack of one."""
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "fixtures"
        / "configs"
        / "dashboard_entity_filter.json"
    )
    config = json.loads(fixture_path.read_text(encoding="utf-8"))
    obj = parse(config, kind="dashboard")
    assert isinstance(obj, DashboardConfig)
    src = dashboard_source(obj, "entity_filter_demo")
    assert src.count("with c.entity_filter(") == 2
    assert src.count("raw_card(") == 1  # the entities-less `glance` presentation card only
    assert "raw_card({'type': 'glance'})" in src


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


def test_typed_emission_does_not_depend_on_import_order() -> None:
    """Regression (found via `hassle-dev decompile-coverage`): CARD_REGISTRY
    is populated by `hassle.cards`' import side effect; the decompiler module
    must force that import itself, or a process that never imported
    `hassle.cards` raw-falls every card. Proven in a fresh interpreter."""
    import subprocess
    import sys

    code = (
        "from hassle.ir.models import parse\n"
        "from hassle.decompiler.dashboards import dashboard_source\n"
        "obj = parse({'meta': {'url_path': 'iso-check', 'title': 'T'}, 'config':"
        " {'views': [{'type': 'sections', 'sections': [{'type': 'grid', 'cards':"
        " [{'type': 'tile', 'entity': 'light.x'}]}]}]}}, kind='dashboard')\n"
        "src = dashboard_source(obj, 'iso_check')\n"
        "assert 'c.tile(' in src and 'raw_card' not in src, src\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
