"""Empirical verification of `_CM_DEPTH = 2` for the dashboard structural CMs.

Same reasoning as `test_span_depth_empirical.py` (which pins the general
`@contextlib.contextmanager` frame chain for the control-flow constructs), but
line-pinned against the REAL dashboard constructs -- `with view(...)`, `with
section()`, `badge(...)`, `raw_card(...)` -- so a future change to the recorder,
to `capture_span`, or to Python's `contextlib` cannot silently break dashboard
span attribution.

The design (docs/internals/dashboards-design.md §6.1) requires that every
recorded card/view/section carry a `SourceSpan` sidecar pointing at the
AUTHOR's line, since tier-2 validation findings are reported at that
`file:line`.

Every `with` below is deliberately nested rather than combined (`# noqa:
SIM117`): each construct must sit on its OWN source line for the line pins to
mean anything at all.
"""

from __future__ import annotations

from hassle.compiler.dashboards.recorder import (
    _CM_DEPTH,  # pyright: ignore[reportPrivateUsage]
    dashboard_recording,
)
from hassle.compiler.dashboards.structure import badge, raw_card, section, view


def test_cm_depth_constant_is_two() -> None:
    # The constant is the documented reason, in one place; the tests below are
    # the empirical proof that 2 is the right value.
    assert _CM_DEPTH == 2


def test_view_and_section_spans_point_at_the_with_statement_lines() -> None:
    with dashboard_recording(url_path="a-b") as rec:  # noqa: SIM117 - lines stay distinct
        with view(title="V"):  # line 37
            with section():  # line 38
                raw_card({"type": "markdown"})  # line 39

    spans = rec.node_spans()
    assert spans["views[0]"].line == 37
    assert spans["views[0].sections[0]"].line == 38
    assert spans["views[0].sections[0].cards[0]"].line == 39
    for span in spans.values():
        assert span.file.endswith("test_dashboard_span_depth_empirical.py")


def test_badge_span_points_at_the_call_site() -> None:
    with dashboard_recording(url_path="a-b") as rec:  # noqa: SIM117 - lines stay distinct
        with view(title="V"):
            badge("sensor.a")  # line 52

    assert rec.node_spans()["views[0].badges[0]"].line == 52


def test_span_depth_does_not_compound_under_nesting() -> None:
    # Each construct's own `capture_span(depth=_CM_DEPTH)` call is made from
    # its own generator frame, one contextlib trampoline away from its own call
    # site, no matter how many other constructs are open above it.
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="A"):  # line 62  # noqa: SIM117 - lines stay distinct
            with section():  # line 63
                raw_card({"type": "markdown"})  # line 64
        with view(title="B", type="masonry"):  # line 65
            raw_card({"type": "markdown"})  # line 66

    spans = rec.node_spans()
    assert spans["views[0]"].line == 62
    assert spans["views[0].sections[0]"].line == 63
    assert spans["views[0].sections[0].cards[0]"].line == 64
    assert spans["views[1]"].line == 65
    assert spans["views[1].cards[0]"].line == 66
