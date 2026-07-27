"""Dashboard compile-error snapshots (docs/internals/dashboards-design.md §5.6).

Error messages are product surface: each states *what* went wrong, *where*
(file:line), and *the fix*, in one paragraph, and is pinned by a text snapshot
under ``tests/snapshots/errors/`` (regenerate with ``HASSLE_UPDATE_SNAPSHOTS=1``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hassle.cards import cond
from hassle.compiler import compile_bundle
from hassle.compiler.dashboards.errors import (
    DashboardConditionInAutomationError,
    DashboardConditionTypeError,
    DashboardNestingError,
    DashboardUrlPathError,
    DefaultDashboardMetadataError,
    ExtraShadowsKwargError,
    NoDashboardContextError,
    PanelViewArityError,
    SectionOutsideSectionsViewError,
    SectionRequiredError,
)
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import badge, raw_card, section, view
from hassle.compiler.errors import NoRecordingContextError
from hassle.compiler.recording import recording
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"

CARD: dict[str, Any] = {"type": "markdown", "content": "hi"}


def _check(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, normalize_error(actual, mask_lines_for=Path(__file__).name))


def _compile_error(case: str, expected: type[Exception]) -> str:
    with pytest.raises(expected) as excinfo:
        compile_bundle(FIXTURES / case / "bundle")
    return str(excinfo.value)


# ---------------------------------------------------------------------------
# context / nesting
# ---------------------------------------------------------------------------
def test_no_dashboard_context_message() -> None:
    with pytest.raises(NoDashboardContextError) as excinfo:
        raw_card(CARD)
    _check("dashboard_no_context", str(excinfo.value))


def test_no_dashboard_context_inside_an_automation_body_message() -> None:
    with recording(kind="automation", id="x"):
        with pytest.raises(NoDashboardContextError) as excinfo:
            raw_card(CARD)
    _check("dashboard_no_context_in_automation", str(excinfo.value))


def test_automation_action_verb_inside_a_dashboard_body_message() -> None:
    from hassle import service

    with dashboard_recording(url_path="a-b"):
        with pytest.raises(NoRecordingContextError) as excinfo:
            service("light.turn_on")
    _check("dashboard_action_verb_in_dashboard", str(excinfo.value))


def test_card_at_the_dashboard_level_message() -> None:
    with dashboard_recording(url_path="a-b"):
        with pytest.raises(DashboardNestingError) as excinfo:
            raw_card(CARD)
    _check("dashboard_card_needs_a_view", str(excinfo.value))


def test_badge_outside_a_view_message() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():
        with pytest.raises(DashboardNestingError) as excinfo:
            badge("sensor.a")
    _check("dashboard_badge_outside_view", str(excinfo.value))


def test_nested_view_message() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):
        with pytest.raises(DashboardNestingError) as excinfo:
            with view(title="W"):
                pass
    _check("dashboard_nested_view", str(excinfo.value))


# ---------------------------------------------------------------------------
# structure discipline
# ---------------------------------------------------------------------------
def test_section_required_message() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):
        with pytest.raises(SectionRequiredError) as excinfo:
            raw_card(CARD)
    _check("dashboard_section_required", str(excinfo.value))


def test_section_outside_sections_view_message() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):
        with pytest.raises(SectionOutsideSectionsViewError) as excinfo:
            with section():
                pass
    _check("dashboard_section_outside_sections_view", str(excinfo.value))


def test_panel_view_arity_message() -> None:
    with dashboard_recording(url_path="a-b"):
        with pytest.raises(PanelViewArityError) as excinfo:
            with view(title="V", type="panel"):
                raw_card(CARD)
                raw_card(CARD)
    _check("dashboard_panel_view_arity", str(excinfo.value))


def test_extra_shadows_kwarg_message() -> None:
    with dashboard_recording(url_path="a-b"):
        with pytest.raises(ExtraShadowsKwargError) as excinfo:
            with view(title="V", extra={"title": "other"}):
                pass
    _check("dashboard_extra_shadows_kwarg", str(excinfo.value))


# ---------------------------------------------------------------------------
# identity / metadata (§5.2, §3.4)
# ---------------------------------------------------------------------------
def test_url_path_missing_message() -> None:
    _check(
        "dashboard_url_path_missing",
        _compile_error("dashboard_error_url_path_missing", DashboardUrlPathError),
    )


def test_url_path_both_message() -> None:
    _check(
        "dashboard_url_path_both",
        _compile_error("dashboard_error_url_path_both", DashboardUrlPathError),
    )


def test_url_path_hyphenless_message() -> None:
    _check(
        "dashboard_url_path_hyphenless",
        _compile_error("dashboard_error_url_path_hyphenless", DashboardUrlPathError),
    )


def test_raw_dashboard_meta_without_url_path_message() -> None:
    _check(
        "dashboard_url_path_meta_missing",
        _compile_error("dashboard_error_raw_meta_no_url_path", DashboardUrlPathError),
    )


def test_default_dashboard_metadata_message() -> None:
    _check(
        "dashboard_default_metadata",
        _compile_error("dashboard_error_default_metadata", DefaultDashboardMetadataError),
    )


# ---------------------------------------------------------------------------
# cross-vocabulary condition traps (§5.4)
# ---------------------------------------------------------------------------
def test_dashboard_condition_type_message() -> None:
    from hassle import state

    with dashboard_recording(url_path="a-b"):
        with pytest.raises(DashboardConditionTypeError) as excinfo:
            with view(title="V", visibility=[state("light.a").is_("on")]):
                pass
    _check("dashboard_condition_type", str(excinfo.value))


def test_dashboard_condition_in_automation_message() -> None:
    from hassle import only_if

    with recording(kind="automation", id="x"):
        with pytest.raises(DashboardConditionInAutomationError) as excinfo:
            only_if(cond.state("light.a", "on"))  # pyright: ignore[reportArgumentType]
    _check("dashboard_condition_in_automation", str(excinfo.value))
