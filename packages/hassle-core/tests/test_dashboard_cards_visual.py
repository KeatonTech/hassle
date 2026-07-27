"""DB3b (visual half): gauge / history / statistics / text card builders.

Test contract (docs/internals/dashboards-design.md §5.3, §6.1.1 -- the frozen
F5 card-builder protocol): every builder in `cards/visual.py` is a leaf card
built on the shared `put`/`merge_extra`/`normalize_visibility` conventions and
the `record_card` seam, registered exactly once in `CARD_REGISTRY` with the
right `entity_params` for DB7's table-driven extraction.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.cards import cond
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY
from hassle.compiler.dashboards.cards import visual as v
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import view

VISUAL_TYPES: tuple[str, ...] = (
    "gauge",
    "history-graph",
    "statistics-graph",
    "sensor",
    "statistic",
    "markdown",
    "clock",
    "calendar",
    "logbook",
)


def _cards(build: Any) -> list[dict[str, Any]]:
    """Record cards directly in a `masonry` view (no `section()` needed)."""
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V", type="masonry"):
            build()
        return rec.build_config()["views"][0]["cards"]


# ---------------------------------------------------------------------------
# gauge
# ---------------------------------------------------------------------------


def test_gauge_typed_options() -> None:
    def build() -> None:
        v.gauge(
            "sensor.cpu_temp",
            name="CPU",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "red": 85},
            theme="dark",
        )

    assert _cards(build) == [
        {
            "type": "gauge",
            "entity": "sensor.cpu_temp",
            "name": "CPU",
            "unit": "°C",
            "min": 0,
            "max": 100,
            "needle": True,
            "severity": {"green": 0, "red": 85},
            "theme": "dark",
        }
    ]


def test_gauge_omits_options_that_were_never_passed() -> None:
    def build() -> None:
        v.gauge("sensor.cpu_temp")

    assert _cards(build) == [{"type": "gauge", "entity": "sensor.cpu_temp"}]


def test_gauge_extra_merges_verbatim() -> None:
    def build() -> None:
        v.gauge("sensor.cpu_temp", extra={"card_mod": {"a": 1}})

    assert _cards(build) == [{"type": "gauge", "entity": "sensor.cpu_temp", "card_mod": {"a": 1}}]


def test_gauge_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            v.gauge("sensor.cpu_temp", extra={"name": "other"})


def test_gauge_visibility_normalizes_conditions() -> None:
    def build() -> None:
        v.gauge("sensor.cpu_temp", visibility=cond.state("input_boolean.on", "on"))

    assert _cards(build)[0]["visibility"] == [
        {"condition": "state", "entity": "input_boolean.on", "state": "on"}
    ]


# ---------------------------------------------------------------------------
# history_graph / statistics_graph -- entities varargs
# ---------------------------------------------------------------------------


def test_history_graph_entities_are_positional_varargs_of_mixed_rows() -> None:
    def build() -> None:
        v.history_graph(
            "sensor.a",
            {"entity": "sensor.b", "name": "B"},
            title="Temps",
            hours_to_show=48,
        )

    assert _cards(build) == [
        {
            "type": "history-graph",
            "entities": ["sensor.a", {"entity": "sensor.b", "name": "B"}],
            "title": "Temps",
            "hours_to_show": 48,
        }
    ]


def test_history_graph_with_no_entities_still_materializes_an_empty_list() -> None:
    def build() -> None:
        v.history_graph(title="Empty")

    assert _cards(build) == [{"type": "history-graph", "entities": [], "title": "Empty"}]


def test_history_graph_copies_dict_rows_so_later_mutation_cannot_leak() -> None:
    row: dict[str, Any] = {"entity": "sensor.a"}

    def build() -> None:
        v.history_graph(row)

    cards = _cards(build)
    row["mutated"] = True
    assert cards[0]["entities"] == [{"entity": "sensor.a"}]


def test_statistics_graph_typed_options() -> None:
    def build() -> None:
        v.statistics_graph(
            "sensor.energy",
            title="Energy",
            stat_types=["mean", "max"],
            chart_type="bar",
            period="hour",
            days_to_show=7,
            hide_legend=True,
            logarithmic_scale=False,
        )

    assert _cards(build) == [
        {
            "type": "statistics-graph",
            "entities": ["sensor.energy"],
            "title": "Energy",
            "stat_types": ["mean", "max"],
            "chart_type": "bar",
            "period": "hour",
            "days_to_show": 7,
            "hide_legend": True,
            "logarithmic_scale": False,
        }
    ]


def test_statistics_graph_extra_shadowing_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            v.statistics_graph("sensor.energy", extra={"period": "day"})


# ---------------------------------------------------------------------------
# sensor / statistic
# ---------------------------------------------------------------------------


def test_sensor_typed_options() -> None:
    def build() -> None:
        v.sensor(
            "sensor.cpu_temp",
            name="CPU",
            icon="mdi:thermometer",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
            theme="dark",
            limits={"min": 0, "max": 100},
        )

    assert _cards(build) == [
        {
            "type": "sensor",
            "entity": "sensor.cpu_temp",
            "name": "CPU",
            "icon": "mdi:thermometer",
            "graph": "line",
            "detail": 2,
            "hours_to_show": 24,
            "unit": "°C",
            "theme": "dark",
            "limits": {"min": 0, "max": 100},
        }
    ]


def test_statistic_typed_options() -> None:
    def build() -> None:
        v.statistic(
            "sensor.energy",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )

    assert _cards(build) == [
        {
            "type": "statistic",
            "entity": "sensor.energy",
            "name": "Energy this month",
            "stat_type": "sum",
            "period": {"calendar": {"period": "month"}},
        }
    ]


# ---------------------------------------------------------------------------
# markdown -- Jinja content passthrough
# ---------------------------------------------------------------------------


def test_markdown_content_with_a_jinja_template_passes_through_verbatim() -> None:
    template = "Current: {{ states('sensor.cpu_temp') }}°C"

    def build() -> None:
        v.markdown(template, title="Status")

    assert _cards(build) == [{"type": "markdown", "content": template, "title": "Status"}]


def test_markdown_omits_title_when_absent() -> None:
    def build() -> None:
        v.markdown("plain text")

    assert _cards(build) == [{"type": "markdown", "content": "plain text"}]


# ---------------------------------------------------------------------------
# clock -- no entity of its own
# ---------------------------------------------------------------------------


def test_clock_typed_options_and_no_entity_field() -> None:
    def build() -> None:
        v.clock(clock_style="analog", clock_size="large", show_seconds=True, time_format="24")

    cards = _cards(build)
    assert cards == [
        {
            "type": "clock",
            "clock_style": "analog",
            "clock_size": "large",
            "show_seconds": True,
            "time_format": "24",
        }
    ]
    assert "entity" not in cards[0]


# ---------------------------------------------------------------------------
# calendar / logbook -- entities varargs
# ---------------------------------------------------------------------------


def test_calendar_entities_varargs_and_initial_view() -> None:
    def build() -> None:
        v.calendar("calendar.family", "calendar.work", initial_view="listWeek", title="Sched")

    assert _cards(build) == [
        {
            "type": "calendar",
            "entities": ["calendar.family", "calendar.work"],
            "title": "Sched",
            "initial_view": "listWeek",
        }
    ]


def test_logbook_entities_varargs_and_hours_to_show() -> None:
    def build() -> None:
        v.logbook("sensor.a", hours_to_show=12)

    assert _cards(build) == [{"type": "logbook", "entities": ["sensor.a"], "hours_to_show": 12}]


# ---------------------------------------------------------------------------
# CARD_REGISTRY -- each builder registered exactly once, with correct wiring
# ---------------------------------------------------------------------------


def test_every_visual_card_type_is_registered_exactly_once() -> None:
    for card_type in VISUAL_TYPES:
        assert card_type in CARD_REGISTRY, f"{card_type!r} missing from CARD_REGISTRY"
    # `CARD_REGISTRY` is a plain dict keyed by `type` -- duplicate registration
    # is impossible to represent (the second `register_card` call would have
    # raised `ValueError` at import time), but pin the count too so a rename
    # that silently drops a row is still caught.
    present = [t for t in CARD_REGISTRY if t in VISUAL_TYPES]
    assert sorted(present) == sorted(VISUAL_TYPES)


@pytest.mark.parametrize(
    ("card_type", "builder", "entity_params"),
    [
        ("gauge", "c.gauge", ("entity",)),
        ("history-graph", "c.history_graph", ("entities",)),
        ("statistics-graph", "c.statistics_graph", ("entities",)),
        ("sensor", "c.sensor", ("entity",)),
        ("statistic", "c.statistic", ("entity",)),
        ("markdown", "c.markdown", ()),
        ("clock", "c.clock", ()),
        ("calendar", "c.calendar", ("entities",)),
        ("logbook", "c.logbook", ("entities",)),
    ],
)
def test_card_spec_wiring(card_type: str, builder: str, entity_params: tuple[str, ...]) -> None:
    spec = CARD_REGISTRY[card_type]
    assert spec.builder == builder
    assert spec.entity_params == entity_params
    assert spec.container == "leaf"
    assert spec.context_manager is False
