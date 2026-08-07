"""Structural dashboard verbs: `view`/`section`/`badge` + the raw ladder.

Test contract for DB2 (docs/internals/dashboards-design.md §5.2/§5.5): the exact
`type=` semantics of `view`, sections-view discipline, panel arity, badge
shapes, the `extra=` merge + shadow check, and the three structural `raw_*`
verbs.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.compiler.dashboards.errors import (
    ExtraShadowsKwargError,
    PanelViewArityError,
    SectionOutsideSectionsViewError,
    SectionRequiredError,
)
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import (
    badge,
    raw_card,
    raw_section,
    raw_view,
    section,
    view,
)

CARD: dict[str, Any] = {"type": "markdown", "content": "hi"}


def _config(build: Any) -> dict[str, Any]:
    with dashboard_recording(url_path="a-b") as rec:
        build()
    return rec.build_config()


# ---------------------------------------------------------------------------
# view(type=) -- all five spellings (§5.2)
# ---------------------------------------------------------------------------


def test_view_type_defaults_to_sections_and_is_materialized_explicitly() -> None:
    def build() -> None:
        with view(title="V"), section():
            raw_card(CARD)

    v = _config(build)["views"][0]
    assert v["type"] == "sections"
    assert v["sections"] == [{"type": "grid", "cards": [CARD]}]


def test_view_type_none_emits_no_type_key_at_all() -> None:
    def build() -> None:
        with view(title="Legacy", type=None):
            raw_card(CARD)

    v = _config(build)["views"][0]
    assert "type" not in v
    assert v["cards"] == [CARD]


@pytest.mark.parametrize("view_type", ["masonry", "sidebar"])
def test_view_type_literal_is_emitted_verbatim_and_takes_cards(view_type: str) -> None:
    def build() -> None:
        with view(title="V", type=view_type):
            raw_card(CARD)
            raw_card(CARD)

    v = _config(build)["views"][0]
    assert v["type"] == view_type
    assert v["cards"] == [CARD, CARD]


def test_panel_view_takes_exactly_one_card() -> None:
    def build() -> None:
        with view(title="V", type="panel"):
            raw_card(CARD)

    v = _config(build)["views"][0]
    assert v["type"] == "panel"
    assert v["cards"] == [CARD]


def test_panel_view_with_two_cards_raises() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(PanelViewArityError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", type="panel"):
            raw_card(CARD)
            raw_card(CARD)


def test_panel_view_with_no_cards_raises() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(PanelViewArityError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", type="panel"):
            pass


def test_view_options_are_emitted_in_a_stable_order() -> None:
    def build() -> None:
        with view(
            title="V",
            path="v",
            icon="mdi:home",
            max_columns=3,
            subview=True,
            visible=False,
            theme="dark",
            background="#fff",
            header={"card": {"type": "markdown"}},
        ):
            pass

    v = _config(build)["views"][0]
    assert list(v) == [
        "type",
        "title",
        "path",
        "icon",
        "theme",
        "background",
        "max_columns",
        "subview",
        "visible",
        "header",
        "sections",
    ]


# ---------------------------------------------------------------------------
# section discipline (§5.2)
# ---------------------------------------------------------------------------


def test_section_emits_a_grid_card_container() -> None:
    def build() -> None:
        with view(title="V"), section(column_span=2):
            raw_card(CARD)

    s = _config(build)["views"][0]["sections"][0]
    assert s == {"type": "grid", "column_span": 2, "cards": [CARD]}


def test_section_under_a_masonry_view_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(SectionOutsideSectionsViewError):
            with section():
                pass


def test_section_under_a_legacy_masonry_view_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type=None):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(SectionOutsideSectionsViewError):
            with section():
                pass


def test_section_nested_in_a_section_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(SectionOutsideSectionsViewError):
            with section():
                pass


def test_leaf_card_directly_under_a_sections_view_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(SectionRequiredError):
            raw_card(CARD)


# ---------------------------------------------------------------------------
# badges (§5.2)
# ---------------------------------------------------------------------------


def test_badge_from_an_entity_id_builds_the_object_form() -> None:
    def build() -> None:
        with view(title="V"):
            badge("sensor.outside_temp", name="Outside")

    assert _config(build)["views"][0]["badges"] == [
        {"type": "entity", "entity": "sensor.outside_temp", "name": "Outside"}
    ]


def test_badge_from_a_dict_passes_through_verbatim() -> None:
    legacy: dict[str, Any] = {"type": "custom:weird-badge", "whatever": [1, 2]}

    def build() -> None:
        with view(title="V"):
            badge(legacy)

    assert _config(build)["views"][0]["badges"] == [legacy]


def test_badges_are_emitted_before_the_view_children() -> None:
    def build() -> None:
        with view(title="V"):
            badge("sensor.a")
            with section():
                raw_card(CARD)

    v = _config(build)["views"][0]
    assert list(v)[-2:] == ["badges", "sections"]


# ---------------------------------------------------------------------------
# the raw ladder (§5.5)
# ---------------------------------------------------------------------------


def test_raw_view_records_a_verbatim_view() -> None:
    body: dict[str, Any] = {"strategy": {"type": "original-states"}, "title": "Auto"}

    def build() -> None:
        raw_view(body)

    assert _config(build)["views"] == [body]


def test_raw_section_records_a_verbatim_section() -> None:
    body: dict[str, Any] = {"type": "grid", "cards": [], "unknown": True}

    def build() -> None:
        with view(title="V"):
            raw_section(body)

    assert _config(build)["views"][0]["sections"] == [body]


def test_raw_section_under_a_masonry_view_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(SectionOutsideSectionsViewError):
            raw_section({"type": "grid"})


def test_raw_verbs_copy_their_dict_so_later_mutation_cannot_leak() -> None:
    body: dict[str, Any] = {"type": "custom:x"}

    def build() -> None:
        with view(title="V"), section():
            raw_card(body)

    config = _config(build)
    body["mutated"] = True
    assert config["views"][0]["sections"][0]["cards"][0] == {"type": "custom:x"}


# ---------------------------------------------------------------------------
# extra= merge + shadow check (§5.3)
# ---------------------------------------------------------------------------


def test_extra_is_merged_verbatim_into_the_view_body() -> None:
    def build() -> None:
        with view(title="V", extra={"cards_position": "left", "unknown": {"a": 1}}):
            pass

    v = _config(build)["views"][0]
    assert v["cards_position"] == "left"
    assert v["unknown"] == {"a": 1}


def test_extra_is_merged_verbatim_into_the_section_body() -> None:
    def build() -> None:
        with view(title="V"), section(extra={"invented": [1]}):
            pass

    assert _config(build)["views"][0]["sections"][0]["invented"] == [1]


def test_extra_shadowing_a_declared_view_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(ExtraShadowsKwargError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", extra={"title": "other"}):
            pass


def test_extra_shadowing_an_omitted_declared_kwarg_still_raises() -> None:
    # Even though `path=` was never passed, `extra={"path": ...}` is rejected:
    # there is exactly ONE spelling of every modelled option.
    with dashboard_recording(url_path="a-b"), pytest.raises(ExtraShadowsKwargError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", extra={"path": "v"}):
            pass


def test_extra_shadowing_a_declared_section_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(ExtraShadowsKwargError):
            with section(column_span=2, extra={"column_span": 3}):
                pass


def test_extra_shadowing_a_badge_option_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(ExtraShadowsKwargError):
            badge("sensor.a", name="A", extra={"name": "B"})


# ---------------------------------------------------------------------------
# BLOCK-2: `view(extra=...)` must not be able to spell a STRUCTURAL key.
#
# `cards`/`sections`/`badges` are written by `view()`'s own assembly after the
# block closes. Before this fix `extra={"cards": [...]}` was accepted and then
# overwritten -- and `extra={"badges": [...]}` survived only when the block
# happened to contain no `badge()` call, which is silent, conditional data loss:
# adding one badge later would wipe the author's whole extra list.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["cards", "sections", "badges"])
def test_extra_cannot_spell_a_view_structural_key(key: str) -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(ExtraShadowsKwargError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", extra={key: []}):
            pass


def test_extra_badges_are_rejected_even_with_no_badge_call_in_the_block() -> None:
    # The conditional-loss case: with no `badge()` in the block, the old code
    # let `extra={"badges": ...}` through, so the bundle compiled clean and
    # then lost those badges the moment an author added a real `badge(...)`.
    with dashboard_recording(url_path="a-b"), pytest.raises(ExtraShadowsKwargError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", extra={"badges": [{"type": "entity", "entity": "sensor.a"}]}):
            pass


def test_extra_badges_are_rejected_with_a_badge_call_in_the_block() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(ExtraShadowsKwargError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", extra={"badges": [{"type": "entity", "entity": "sensor.a"}]}):
            badge("sensor.b")


def test_extra_cannot_spell_a_section_structural_key() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(ExtraShadowsKwargError):
            with section(extra={"cards": []}):
                pass
