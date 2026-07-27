"""`DashboardRecorder` — container stack, span sidecar, and the record seams.

Test contract for DB2 (docs/internals/dashboards-design.md §6.1): the dashboard
recorder is a SIBLING of the automation `Recorder`, with its own `ContextVar`
stack, its own container stack (dashboard -> view -> section/container-card ->
cards), and its own non-public record seam (`record_card` / `push_container`)
that every `hassle.cards` builder is implemented on top of.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import Any

import pytest

from hassle.compiler.dashboards.errors import (
    DashboardNestingError,
    NoDashboardContextError,
    SectionRequiredError,
)
from hassle.compiler.dashboards.recorder import (
    _CM_DEPTH,  # pyright: ignore[reportPrivateUsage]
    DashboardRecorder,
    active_dashboard,
    dashboard_recording,
    push_container,
    record_card,
)
from hassle.compiler.dashboards.structure import raw_card, section, view
from hassle.compiler.spans import capture_span


def test_no_active_recorder_outside_a_dashboard_recording() -> None:
    assert active_dashboard() is None


def test_dashboard_recording_installs_and_removes_the_recorder() -> None:
    with dashboard_recording(url_path="climate-control") as rec:
        assert isinstance(rec, DashboardRecorder)
        assert active_dashboard() is rec
    assert active_dashboard() is None


def test_context_var_stack_nests_and_restores() -> None:
    # Nested `@dashboard` tracing is impossible in practice, but the ContextVar
    # convention buys the same isolation/reentrancy the automation recorder has.
    with dashboard_recording(url_path="outer-one") as outer:
        with dashboard_recording(url_path="inner-one") as inner:
            assert active_dashboard() is inner
        assert active_dashboard() is outer


def test_record_card_outside_a_dashboard_raises_no_dashboard_context() -> None:
    with pytest.raises(NoDashboardContextError):
        record_card({"type": "markdown"}, span=None)


def test_record_card_at_the_dashboard_level_raises_nesting_error() -> None:
    with dashboard_recording(url_path="a-b"):
        with pytest.raises(DashboardNestingError):
            raw_card({"type": "markdown", "content": "hi"})


def test_record_card_directly_under_a_sections_view_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):
        with pytest.raises(SectionRequiredError):
            raw_card({"type": "markdown", "content": "hi"})


def test_container_stack_depth_tracks_the_open_containers() -> None:
    with dashboard_recording(url_path="a-b") as rec:
        assert rec.depth == 1  # the dashboard root frame
        with view(title="V"):
            assert rec.depth == 2
            with section():
                assert rec.depth == 3
            assert rec.depth == 2
        assert rec.depth == 1


def test_push_container_places_the_container_and_collects_its_children() -> None:
    # `push_container` is the seam DB3's container-card builders drive: it
    # records the container body as a card in the CURRENT frame, then redirects
    # subsequent `record_card` calls into it.
    @contextlib.contextmanager
    def vertical_stack() -> Generator[None]:
        span = capture_span(depth=_CM_DEPTH)
        body: dict[str, Any] = {"type": "vertical-stack"}
        with push_container(body, label="a `vertical-stack` card", span=span):
            yield

    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V"), section():
            with vertical_stack():
                raw_card({"type": "markdown", "content": "one"})
                raw_card({"type": "markdown", "content": "two"})

    config = rec.build_config()
    stack = config["views"][0]["sections"][0]["cards"][0]
    assert stack["type"] == "vertical-stack"
    assert [c["content"] for c in stack["cards"]] == ["one", "two"]


def test_every_recorded_node_carries_a_span_reachable_by_path() -> None:
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V"):  # noqa: SIM117 - distinct lines are load-bearing
            with section():
                raw_card({"type": "markdown", "content": "one"})

    spans = rec.node_spans()
    assert set(spans) == {
        "views[0]",
        "views[0].sections[0]",
        "views[0].sections[0].cards[0]",
    }
    for path, span in spans.items():
        assert span is not None, path
        assert span.file.endswith("test_dashboard_recorder.py")
    # The three nodes were opened on three consecutive source lines.
    assert (
        spans["views[0]"].line
        < spans["views[0].sections[0]"].line
        < spans["views[0].sections[0].cards[0]"].line
    )


def test_badge_nodes_get_their_own_span_path() -> None:
    from hassle.compiler.dashboards.structure import badge

    with dashboard_recording(url_path="a-b") as rec, view(title="V"):
        badge("sensor.outside")

    assert "views[0].badges[0]" in rec.node_spans()
