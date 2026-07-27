"""The `cond` Lovelace-condition vocabulary and its cross-vocabulary traps.

Test contract for DB2 (docs/internals/dashboards-design.md §5.4): Lovelace
visibility/conditional conditions are a DIFFERENT schema from automation
conditions, so they get their own small vocabulary — and confusing the two is
trap-caught in BOTH directions with teaching errors.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle import all_of, any_of, if_then, not_, numeric_state, only_if, state
from hassle.cards import cond
from hassle.compiler.dashboards.errors import (
    DashboardConditionInAutomationError,
    DashboardConditionTypeError,
)
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import section, view
from hassle.compiler.recording import recording


# ---------------------------------------------------------------------------
# serialization shapes (§5.4)
# ---------------------------------------------------------------------------
def test_cond_state_positional_value() -> None:
    assert cond.state("input_boolean.guest_mode", "on").to_dashboard_condition() == {
        "condition": "state",
        "entity": "input_boolean.guest_mode",
        "state": "on",
    }


def test_cond_state_not() -> None:
    assert cond.state("light.hall", not_="off").to_dashboard_condition() == {
        "condition": "state",
        "entity": "light.hall",
        "state_not": "off",
    }


def test_cond_numeric_bounds_are_omitted_when_absent() -> None:
    assert cond.numeric("sensor.t", above=25).to_dashboard_condition() == {
        "condition": "numeric_state",
        "entity": "sensor.t",
        "above": 25,
    }
    assert cond.numeric("sensor.t", above=25, below=30).to_dashboard_condition() == {
        "condition": "numeric_state",
        "entity": "sensor.t",
        "above": 25,
        "below": 30,
    }


def test_cond_screen() -> None:
    assert cond.screen("(max-width: 600px)").to_dashboard_condition() == {
        "condition": "screen",
        "media_query": "(max-width: 600px)",
    }


def test_cond_user() -> None:
    assert cond.user("abc123", "def456").to_dashboard_condition() == {
        "condition": "user",
        "users": ["abc123", "def456"],
    }


def test_cond_combinators() -> None:
    a = cond.state("light.a", "on")
    b = cond.screen("(min-width: 900px)")
    assert cond.any(a, b).to_dashboard_condition() == {
        "condition": "or",
        "conditions": [a.to_dashboard_condition(), b.to_dashboard_condition()],
    }
    assert cond.all(a, b).to_dashboard_condition() == {
        "condition": "and",
        "conditions": [a.to_dashboard_condition(), b.to_dashboard_condition()],
    }
    assert cond.not_(a).to_dashboard_condition() == {
        "condition": "not",
        "conditions": [a.to_dashboard_condition()],
    }


def test_combinators_accept_verbatim_dicts() -> None:
    raw: dict[str, Any] = {"condition": "future_kind", "whatever": 1}
    assert cond.any(raw).to_dashboard_condition() == {
        "condition": "or",
        "conditions": [raw],
    }


# ---------------------------------------------------------------------------
# visibility= normalization (§5.2)
# ---------------------------------------------------------------------------
def test_visibility_accepts_a_list_of_conds_and_dicts() -> None:
    raw: dict[str, Any] = {"condition": "future_kind"}
    with dashboard_recording(url_path="a-b") as rec:  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with view(title="V", visibility=[cond.screen("(max-width: 600px)"), raw]):
            pass
    assert rec.build_config()["views"][0]["visibility"] == [
        {"condition": "screen", "media_query": "(max-width: 600px)"},
        raw,
    ]


def test_visibility_accepts_a_single_condition() -> None:
    with dashboard_recording(url_path="a-b") as rec:  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with view(title="V"), section(visibility=cond.state("light.a", "on")):
            pass
    assert rec.build_config()["views"][0]["sections"][0]["visibility"] == [
        {"condition": "state", "entity": "light.a", "state": "on"}
    ]


# ---------------------------------------------------------------------------
# cross-vocabulary traps, both directions (§5.4)
# ---------------------------------------------------------------------------
def test_automation_condition_in_a_dashboard_slot_raises() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(DashboardConditionTypeError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", visibility=[state("light.a").is_("on")]):
            pass


def test_automation_condition_trap_names_the_cond_equivalent() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(DashboardConditionTypeError) as exc:  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", visibility=[numeric_state("sensor.t", above=5)]):
            pass
    assert "cond.numeric(" in str(exc.value)


def test_a_dashboard_condition_in_only_if_raises_the_mirror() -> None:
    with recording(kind="automation", id="x"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(DashboardConditionInAutomationError):
            only_if(cond.state("light.a", "on"))  # pyright: ignore[reportArgumentType]


def test_a_dashboard_condition_in_if_then_raises_the_mirror() -> None:
    with recording(kind="automation", id="x"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(DashboardConditionInAutomationError):
            with if_then(cond.state("light.a", "on")):  # pyright: ignore[reportArgumentType]
                pass


@pytest.mark.parametrize("combinator", [all_of, any_of, not_])
def test_a_dashboard_condition_in_a_combinator_raises_the_mirror(combinator: Any) -> None:
    with recording(kind="automation", id="x"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(DashboardConditionInAutomationError):
            combinator(cond.state("light.a", "on")).to_condition()


def test_a_plain_value_in_a_visibility_slot_raises() -> None:
    with dashboard_recording(url_path="a-b"), pytest.raises(DashboardConditionTypeError):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with view(title="V", visibility=[42]):  # pyright: ignore[reportArgumentType]
            pass
