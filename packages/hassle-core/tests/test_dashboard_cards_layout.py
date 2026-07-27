"""`hassle.cards` layout/container builders — DB3a's batch.

Test contract (docs/internals/dashboards-design.md §5.3, §6.1.1 F5):
`vertical_stack`/`horizontal_stack`/`grid` are ordinary `cards:` list
containers; `conditional` wraps EXACTLY one child card
(`ConditionalCardArityError` otherwise); `entity_filter` wraps ZERO or ONE.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hassle.cards import cond, conditional, entity_filter, grid, horizontal_stack, vertical_stack
from hassle.compiler.dashboards.errors import ConditionalCardArityError, ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import raw_card, section, view
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"
CARD: dict[str, Any] = {"type": "markdown", "content": "hi"}


def _config(build: Any) -> dict[str, Any]:
    with dashboard_recording(url_path="a-b") as rec:
        build()
    return rec.build_config()


def _one_card(build: Any) -> dict[str, Any]:
    v = _config(build)["views"][0]
    return v["sections"][0]["cards"][0] if "sections" in v else v["cards"][0]


# ---------------------------------------------------------------------------
# vertical_stack / horizontal_stack
# ---------------------------------------------------------------------------
def test_vertical_stack_holds_its_children_in_order() -> None:
    def build() -> None:
        with view(title="V"), section(), vertical_stack(title="Stack"):
            raw_card(CARD)
            raw_card({"type": "markdown", "content": "two"})

    stack = _one_card(build)
    assert stack == {
        "type": "vertical-stack",
        "title": "Stack",
        "cards": [CARD, {"type": "markdown", "content": "two"}],
    }


def test_horizontal_stack_has_no_title_option() -> None:
    def build() -> None:
        with view(title="V"), section(), horizontal_stack():
            raw_card(CARD)

    stack = _one_card(build)
    assert stack == {"type": "horizontal-stack", "cards": [CARD]}


def test_horizontal_stack_extra_can_still_carry_a_title_like_key() -> None:
    # `extra=` is the forward-compat valve: even though `title` is not a typed
    # kwarg here, an unmodelled option of that name is not blocked.
    def build() -> None:
        with view(title="V"), section(), horizontal_stack(extra={"unknown_option": 1}):
            raw_card(CARD)

    stack = _one_card(build)
    assert stack["unknown_option"] == 1


def test_stack_extra_shadowing_cards_key_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            with vertical_stack(extra={"cards": []}):
                pass


# ---------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------
def test_grid_card_stores_columns_and_square() -> None:
    def build() -> None:
        with view(title="V"), section(), grid(columns=3, square=False):
            raw_card(CARD)

    assert _one_card(build) == {
        "type": "grid",
        "columns": 3,
        "square": False,
        "cards": [CARD],
    }


def test_grid_card_omits_options_that_were_never_passed() -> None:
    def build() -> None:
        with view(title="V"), section(), grid():
            raw_card(CARD)

    g = _one_card(build)
    assert "columns" not in g
    assert "square" not in g


# ---------------------------------------------------------------------------
# nested containers
# ---------------------------------------------------------------------------
def test_vertical_horizontal_grid_nest_three_deep() -> None:
    def build() -> None:
        with (
            view(title="V"),
            section(),
            vertical_stack(),
            horizontal_stack(),
            grid(columns=2),
        ):
            raw_card(CARD)

    outer = _one_card(build)
    assert outer["type"] == "vertical-stack"
    middle = outer["cards"][0]
    assert middle["type"] == "horizontal-stack"
    inner = middle["cards"][0]
    assert inner == {"type": "grid", "columns": 2, "cards": [CARD]}


# ---------------------------------------------------------------------------
# conditional — exactly one card
# ---------------------------------------------------------------------------
def test_conditional_wraps_exactly_one_card() -> None:
    def build() -> None:
        with view(title="V"), section(), conditional(cond.state("light.hall", "on")):
            raw_card(CARD)

    assert _one_card(build) == {
        "type": "conditional",
        "conditions": [{"condition": "state", "entity": "light.hall", "state": "on"}],
        "card": CARD,
    }


def test_conditional_with_zero_cards_raises_arity_error() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ConditionalCardArityError) as excinfo:
            with conditional(cond.state("light.hall", "on")):
                pass
    assert excinfo.value.count == 0
    assert excinfo.value.allowed == "exactly one"


def test_conditional_with_two_cards_raises_arity_error() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ConditionalCardArityError) as excinfo:
            with conditional(cond.state("light.hall", "on")):
                raw_card(CARD)
                raw_card(CARD)
    assert excinfo.value.count == 2


def test_conditional_card_arity_error_message_snapshot() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ConditionalCardArityError) as excinfo:
            with conditional(cond.state("light.hall", "on")):
                raw_card(CARD)
                raw_card(CARD)
    check_snapshot(
        SNAP_DIR,
        "dashboard_conditional_card_arity",
        normalize_error(str(excinfo.value), mask_lines_for=Path(__file__).name),
    )


# ---------------------------------------------------------------------------
# entity_filter — zero or one card
# ---------------------------------------------------------------------------
def test_entity_filter_with_a_presentation_card() -> None:
    def build() -> None:
        with view(title="V"), section(), entity_filter(entities=["light.a", "light.b"]):
            raw_card({"type": "glance"})

    assert _one_card(build) == {
        "type": "entity-filter",
        "entities": ["light.a", "light.b"],
        "card": {"type": "glance"},
    }


def test_entity_filter_without_a_presentation_card() -> None:
    def build() -> None:
        with view(title="V"), section(), entity_filter(entities=["light.a"]):
            pass

    assert _one_card(build) == {"type": "entity-filter", "entities": ["light.a"]}


def test_entity_filter_state_filter_and_show_empty() -> None:
    def build() -> None:
        with (
            view(title="V"),
            section(),
            entity_filter(entities=["light.a"], state_filter=["on"], show_empty=False),
        ):
            pass

    assert _one_card(build) == {
        "type": "entity-filter",
        "entities": ["light.a"],
        "state_filter": ["on"],
        "show_empty": False,
    }


def test_entity_filter_row_dict_passes_through() -> None:
    row: dict[str, Any] = {"entity": "light.a", "state_filter": ["on"]}

    def build() -> None:
        with view(title="V"), section(), entity_filter(entities=[row]):
            pass

    assert _one_card(build)["entities"] == [row]


def test_entity_filter_with_two_cards_raises_arity_error() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ConditionalCardArityError) as excinfo:
            with entity_filter(entities=["light.a"]):
                raw_card(CARD)
                raw_card(CARD)
    assert excinfo.value.allowed == "zero or one"
