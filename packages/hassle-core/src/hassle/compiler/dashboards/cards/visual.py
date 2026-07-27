"""DB3b (visual half) -- gauge / history / statistics / text card builders.

docs/internals/dashboards-design.md §5.3 (leaf card builders) and §6.1.1 (the
frozen F5 card-builder protocol): every builder here is a plain function
(``capture_span(depth=0)``, no ``with`` block -- every card in this family is
a HA **leaf** card, §2.3), built on the shared ``put``/``merge_extra``/
``normalize_visibility`` conventions (``hassle.compiler.dashboards.builders``)
and the ``record_card`` seam (``hassle.compiler.dashboards.recorder``), and
registered into ``CARD_REGISTRY`` (``hassle.compiler.dashboards.card_registry``)
at import time.

Known HA options are typed keyword parameters; ``extra=`` is the forward-
compatibility valve for everything else (F5's "never ``**kwargs``" rule) and
``visibility=`` is on every builder, per §5.2.

``history_graph``/``statistics_graph``/``calendar``/``logbook`` share the
``entities``-varargs convention the F5 appendix documents for the
``entities`` card (§5.3): rows are ``EntityRef | str | dict`` (a dict is a
per-row option passthrough, kept verbatim); ``normalize_rows``
(``hassle.compiler.dashboards.builders`` -- the review-round fix that
collapsed this module's own ``_entity_rows`` and ``cards/layout.py``'s/
``cards/display.py``'s near-identical copies into ONE implementation) is what
both this module and ``cards/media.py`` call.

Every dict/list-valued typed option in this module (``severity=``, ``limits=``,
``period=``) is deep-copied at record time via ``put_copy`` rather than
``put`` (the review round's copy-vs-alias fix, SF-3) -- an author-supplied
option dict can never alias into the compiled card body.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_rows,
    normalize_visibility,
    put,
    put_copy,
)
from hassle.compiler.dashboards.card_registry import CardSpec, register_card
from hassle.compiler.dashboards.recorder import record_card
from hassle.compiler.helpers import EntityRef
from hassle.compiler.spans import capture_span

EntityArg = EntityRef | str


# ---------------------------------------------------------------------------
# gauge
# ---------------------------------------------------------------------------
_GAUGE_DECLARED = frozenset(
    {"type", "entity", "name", "unit", "min", "max", "needle", "severity", "theme", "visibility"}
)


def gauge(
    entity: EntityArg,
    *,
    name: Any = None,
    unit: Any = None,
    min: Any = None,
    max: Any = None,
    needle: Any = None,
    severity: Any = None,
    theme: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.gauge(entity, ...)`` -- a single-entity radial/needle gauge.

    ``severity`` is HA's ``{"green": ..., "yellow": ..., "red": ...}`` mapping,
    deep-copied at record time (``put_copy``) so a caller-owned dict can never
    alias into the compiled card.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "gauge", "entity": str(entity)}
    put(body, "name", name)
    put(body, "unit", unit)
    put(body, "min", min)
    put(body, "max", max)
    put(body, "needle", needle)
    put_copy(body, "severity", severity)
    put(body, "theme", theme)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.gauge", declared=_GAUGE_DECLARED, span=span)
    record_card(body, span=span, what="`c.gauge()`")


register_card(
    CardSpec(
        type="gauge",
        declared=frozenset(
            {
                "type",
                "entity",
                "name",
                "unit",
                "min",
                "max",
                "needle",
                "severity",
                "theme",
                "visibility",
            }
        ),
        builder="c.gauge",
        entity_params=("entity",),
    )
)


# ---------------------------------------------------------------------------
# history_graph
# ---------------------------------------------------------------------------
_HISTORY_GRAPH_DECLARED = frozenset(
    {
        "type",
        "entities",
        "title",
        "hours_to_show",
        "refresh_interval",
        "show_names",
        "logarithmic_scale",
        "visibility",
    }
)


def history_graph(
    *entities: EntityArg | dict[str, Any],
    title: Any = None,
    hours_to_show: Any = None,
    refresh_interval: Any = None,
    show_names: Any = None,
    logarithmic_scale: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.history_graph(*entities, ...)`` -- a state-history line/step chart.

    Rows are positional varargs (§5.3's ``entities``-shaped convention): an
    entity id, or a ``dict`` for a per-row option object (``{"entity": ...,
    "name": ...}``), kept verbatim.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {
        "type": "history-graph",
        "entities": normalize_rows(
            entities, builder="c.history_graph", param="entities", span=span
        ),
    }
    put(body, "title", title)
    put(body, "hours_to_show", hours_to_show)
    put(body, "refresh_interval", refresh_interval)
    put(body, "show_names", show_names)
    put(body, "logarithmic_scale", logarithmic_scale)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.history_graph", declared=_HISTORY_GRAPH_DECLARED, span=span)
    record_card(body, span=span, what="`c.history_graph()`")


register_card(
    CardSpec(
        type="history-graph",
        declared=frozenset(
            {
                "type",
                "entities",
                "title",
                "hours_to_show",
                "refresh_interval",
                "show_names",
                "logarithmic_scale",
                "visibility",
            }
        ),
        builder="c.history_graph",
        entity_params=("entities",),
    )
)


# ---------------------------------------------------------------------------
# statistics_graph
# ---------------------------------------------------------------------------
_STATISTICS_GRAPH_DECLARED = frozenset(
    {
        "type",
        "entities",
        "title",
        "stat_types",
        "chart_type",
        "period",
        "days_to_show",
        "hide_legend",
        "logarithmic_scale",
        "visibility",
    }
)


def statistics_graph(
    *entities: EntityArg | dict[str, Any],
    title: Any = None,
    stat_types: Any = None,
    chart_type: Any = None,
    period: Any = None,
    days_to_show: Any = None,
    hide_legend: Any = None,
    logarithmic_scale: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.statistics_graph(*entities, ...)`` -- long-term-statistics chart.

    ``stat_types`` is HA's list of ``"mean"``/``"min"``/``"max"``/``"sum"``/
    ``"state"``/``"change"``; ``period`` is ``"5minute"``/``"hour"``/``"day"``/
    ``"week"``/``"month"``.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {
        "type": "statistics-graph",
        "entities": normalize_rows(
            entities, builder="c.statistics_graph", param="entities", span=span
        ),
    }
    put(body, "title", title)
    put(body, "stat_types", stat_types)
    put(body, "chart_type", chart_type)
    put(body, "period", period)
    put(body, "days_to_show", days_to_show)
    put(body, "hide_legend", hide_legend)
    put(body, "logarithmic_scale", logarithmic_scale)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(
        body, extra, builder="c.statistics_graph", declared=_STATISTICS_GRAPH_DECLARED, span=span
    )
    record_card(body, span=span, what="`c.statistics_graph()`")


register_card(
    CardSpec(
        type="statistics-graph",
        declared=frozenset(
            {
                "type",
                "entities",
                "title",
                "stat_types",
                "chart_type",
                "period",
                "days_to_show",
                "hide_legend",
                "logarithmic_scale",
                "visibility",
            }
        ),
        builder="c.statistics_graph",
        entity_params=("entities",),
    )
)


# ---------------------------------------------------------------------------
# sensor
# ---------------------------------------------------------------------------
_SENSOR_DECLARED = frozenset(
    {
        "type",
        "entity",
        "name",
        "icon",
        "graph",
        "detail",
        "hours_to_show",
        "unit",
        "theme",
        "limits",
        "visibility",
    }
)


def sensor(
    entity: EntityArg,
    *,
    name: Any = None,
    icon: Any = None,
    graph: Any = None,
    detail: Any = None,
    hours_to_show: Any = None,
    unit: Any = None,
    theme: Any = None,
    limits: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.sensor(entity, ...)`` -- a single-entity value tile with an
    optional inline mini history ``graph``  (``"line"`` or ``"none"``)."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "sensor", "entity": str(entity)}
    put(body, "name", name)
    put(body, "icon", icon)
    put(body, "graph", graph)
    put(body, "detail", detail)
    put(body, "hours_to_show", hours_to_show)
    put(body, "unit", unit)
    put(body, "theme", theme)
    put_copy(body, "limits", limits)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.sensor", declared=_SENSOR_DECLARED, span=span)
    record_card(body, span=span, what="`c.sensor()`")


register_card(
    CardSpec(
        type="sensor",
        declared=frozenset(
            {
                "type",
                "entity",
                "name",
                "icon",
                "graph",
                "detail",
                "hours_to_show",
                "unit",
                "theme",
                "limits",
                "visibility",
            }
        ),
        builder="c.sensor",
        entity_params=("entity",),
    )
)


# ---------------------------------------------------------------------------
# statistic
# ---------------------------------------------------------------------------
_STATISTIC_DECLARED = frozenset({"type", "entity", "name", "stat_type", "period", "visibility"})


def statistic(
    entity: EntityArg,
    *,
    name: Any = None,
    stat_type: Any = None,
    period: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.statistic(entity, ...)`` -- a single long-term-statistics value.

    ``period`` is HA's calendar/fixed-period spec (a dict, e.g. ``{"calendar":
    {"period": "month"}}``); deep-copied at record time (``put_copy``, unlike
    ``view(header=...)``'s reference passthrough) so a caller-owned dict can
    never alias into the compiled card.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "statistic", "entity": str(entity)}
    put(body, "name", name)
    put(body, "stat_type", stat_type)
    put_copy(body, "period", period)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.statistic", declared=_STATISTIC_DECLARED, span=span)
    record_card(body, span=span, what="`c.statistic()`")


register_card(
    CardSpec(
        type="statistic",
        declared=frozenset({"type", "entity", "name", "stat_type", "period", "visibility"}),
        builder="c.statistic",
        entity_params=("entity",),
    )
)


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------
_MARKDOWN_DECLARED = frozenset({"type", "content", "title", "visibility"})


def markdown(
    content: str,
    *,
    title: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.markdown(content, ...)`` -- rendered Markdown/Jinja text.

    ``content`` is a plain string passed through verbatim -- including a
    Jinja template string (``"{{ states('sensor.x') }}"``); HA (not Hassle)
    renders it, so this builder never inspects or transforms it.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "markdown", "content": content}
    put(body, "title", title)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.markdown", declared=_MARKDOWN_DECLARED, span=span)
    record_card(body, span=span, what="`c.markdown()`")


register_card(
    CardSpec(
        type="markdown",
        declared=frozenset({"type", "content", "title", "visibility"}),
        builder="c.markdown",
    )
)


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------
_CLOCK_DECLARED = frozenset(
    {"type", "title", "clock_style", "clock_size", "show_seconds", "time_format", "visibility"}
)


def clock(
    *,
    title: Any = None,
    clock_style: Any = None,
    clock_size: Any = None,
    show_seconds: Any = None,
    time_format: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.clock(...)`` -- a digital/analog clock, no entity of its own.

    ``clock_style`` is ``"analog"`` or ``"digital"``; ``time_format`` is
    ``12``/``24``.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "clock"}
    put(body, "title", title)
    put(body, "clock_style", clock_style)
    put(body, "clock_size", clock_size)
    put(body, "show_seconds", show_seconds)
    put(body, "time_format", time_format)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.clock", declared=_CLOCK_DECLARED, span=span)
    record_card(body, span=span, what="`c.clock()`")


register_card(
    CardSpec(
        type="clock",
        declared=frozenset(
            {
                "type",
                "title",
                "clock_style",
                "clock_size",
                "show_seconds",
                "time_format",
                "visibility",
            }
        ),
        builder="c.clock",
    )
)


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------
_CALENDAR_DECLARED = frozenset({"type", "entities", "title", "initial_view", "visibility"})


def calendar(
    *entities: EntityArg | dict[str, Any],
    title: Any = None,
    initial_view: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.calendar(*entities, ...)`` -- one or more ``calendar.*`` entities.

    ``initial_view`` is HA's FullCalendar view name (``"dayGridMonth"``,
    ``"listWeek"``, …).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {
        "type": "calendar",
        "entities": normalize_rows(entities, builder="c.calendar", param="entities", span=span),
    }
    put(body, "title", title)
    put(body, "initial_view", initial_view)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.calendar", declared=_CALENDAR_DECLARED, span=span)
    record_card(body, span=span, what="`c.calendar()`")


register_card(
    CardSpec(
        type="calendar",
        declared=frozenset({"type", "entities", "title", "initial_view", "visibility"}),
        builder="c.calendar",
        entity_params=("entities",),
    )
)


# ---------------------------------------------------------------------------
# logbook
# ---------------------------------------------------------------------------
_LOGBOOK_DECLARED = frozenset({"type", "entities", "title", "hours_to_show", "visibility"})


def logbook(
    *entities: EntityArg | dict[str, Any],
    title: Any = None,
    hours_to_show: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.logbook(*entities, ...)`` -- the logbook feed filtered to
    ``entities`` (empty means "no filter", HA's own default)."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {
        "type": "logbook",
        "entities": normalize_rows(entities, builder="c.logbook", param="entities", span=span),
    }
    put(body, "title", title)
    put(body, "hours_to_show", hours_to_show)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.logbook", declared=_LOGBOOK_DECLARED, span=span)
    record_card(body, span=span, what="`c.logbook()`")


register_card(
    CardSpec(
        type="logbook",
        declared=frozenset({"type", "entities", "title", "hours_to_show", "visibility"}),
        builder="c.logbook",
        entity_params=("entities",),
    )
)
