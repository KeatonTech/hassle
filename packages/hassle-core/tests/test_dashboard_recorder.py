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
    with dashboard_recording(url_path="a-b"), pytest.raises(DashboardNestingError):
        raw_card({"type": "markdown", "content": "hi"})


def test_record_card_directly_under_a_sections_view_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"):  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
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

    with dashboard_recording(url_path="a-b") as rec, view(title="V"), section():  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with vertical_stack():
            raw_card({"type": "markdown", "content": "one"})
            raw_card({"type": "markdown", "content": "two"})

    config = rec.build_config()
    stack = config["views"][0]["sections"][0]["cards"][0]
    assert stack["type"] == "vertical-stack"
    assert [c["content"] for c in stack["cards"]] == ["one", "two"]


def test_every_recorded_node_carries_a_span_reachable_by_path() -> None:
    with dashboard_recording(url_path="a-b") as rec:  # noqa: SIM117 - lines stay distinct
        with view(title="V"):
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
    # The three nodes were opened on three consecutive source lines, so each
    # one's span really is its OWN -- not the enclosing construct's.
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


# ---------------------------------------------------------------------------
# Span-path grammar for SINGLE-child containers (reviewer finding SF-1).
#
# The F5 appendix blesses `push_container(..., child_key="card", assign=False)`
# for a `conditional` card, whose child is stored as ONE dict under `card:`,
# not a list. The path grammar must say so: `...card` addresses that child,
# while `...card[0]` -- what an unfixed `_collect_spans` emits -- resolves to
# nothing at all for DB4/DB7, since there is no list to index into.
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _conditional(*conditions: dict[str, Any]) -> Generator[None]:
    """Exactly the F5 appendix's conditional-card pattern (design §6.1.1)."""
    span = capture_span(depth=_CM_DEPTH)
    body: dict[str, Any] = {"type": "conditional", "conditions": list(conditions)}
    with push_container(
        body,
        label="a `conditional` card",
        span=span,
        child_key="card",
        child_is_list=False,
        assign=False,
    ) as node:
        yield
    body["card"] = node.children[0].body


def test_single_child_container_span_path_has_no_list_index() -> None:
    with dashboard_recording(url_path="a-b") as rec, view(title="V"), section():  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with _conditional({"condition": "state", "entity": "light.a", "state": "on"}):
            raw_card({"type": "markdown", "content": "shown"})

    spans = rec.node_spans()
    base = "views[0].sections[0].cards[0]"
    assert base in spans
    assert f"{base}.card" in spans, sorted(spans)
    assert f"{base}.card[0]" not in spans


def test_single_child_container_path_addresses_the_stored_dict() -> None:
    # The path must resolve against the COMPILED config by plain traversal --
    # that is the whole contract DB7 reports findings against.
    with dashboard_recording(url_path="a-b") as rec, view(title="V"), section():  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with _conditional({"condition": "screen", "media_query": "(max-width: 600px)"}):
            raw_card({"type": "markdown", "content": "shown"})

    config = rec.build_config()
    card = config["views"][0]["sections"][0]["cards"][0]["card"]
    assert card == {"type": "markdown", "content": "shown"}
    assert "views[0].sections[0].cards[0].card" in rec.node_spans()


def test_push_container_assigns_a_single_child_slot_itself() -> None:
    # `assign=True` with `child_is_list=False` stores the ONE child directly
    # under the key -- the convenience DB3's conditional/entity-filter builders
    # use so they never hand-splice a child body.
    @contextlib.contextmanager
    def conditional_auto() -> Generator[None]:
        span = capture_span(depth=_CM_DEPTH)
        body: dict[str, Any] = {"type": "conditional", "conditions": []}
        with push_container(
            body, label="a `conditional` card", span=span, child_key="card", child_is_list=False
        ):
            yield

    with dashboard_recording(url_path="a-b") as rec, view(title="V"), section():  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with conditional_auto():
            raw_card({"type": "markdown", "content": "only"})

    stack = rec.build_config()["views"][0]["sections"][0]["cards"][0]
    assert stack["card"] == {"type": "markdown", "content": "only"}


def test_single_child_slot_stays_absent_when_no_child_was_recorded() -> None:
    # `c.entity_filter` takes ZERO or one presentation card; an absent child
    # must leave the key absent rather than materialize a null.
    @contextlib.contextmanager
    def optional_child() -> Generator[None]:
        span = capture_span(depth=_CM_DEPTH)
        body: dict[str, Any] = {"type": "entity-filter"}
        with push_container(
            body, label="an `entity-filter` card", span=span, child_key="card", child_is_list=False
        ):
            yield

    with dashboard_recording(url_path="a-b") as rec, view(title="V"), section():  # noqa: SIM117 - the block reads as the dashboard tree it builds
        with optional_child():
            pass

    assert rec.build_config()["views"][0]["sections"][0]["cards"][0] == {"type": "entity-filter"}


def test_single_child_slot_rejects_a_second_child_rather_than_dropping_it() -> None:
    # A builder that forgot its own arity check must not silently lose cards.
    @contextlib.contextmanager
    def sloppy() -> Generator[None]:
        span = capture_span(depth=_CM_DEPTH)
        body: dict[str, Any] = {"type": "conditional"}
        with push_container(
            body, label="a `conditional` card", span=span, child_key="card", child_is_list=False
        ):
            yield

    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117 - `pytest.raises` must wrap only the failing statement
        with pytest.raises(ValueError, match="child_is_list=False"):
            with sloppy():
                raw_card({"type": "markdown", "content": "one"})
                raw_card({"type": "markdown", "content": "two"})
