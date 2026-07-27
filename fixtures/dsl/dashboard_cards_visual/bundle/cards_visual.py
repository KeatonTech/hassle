"""Golden case: DB3b's visual/history/text card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/visual.py`: `gauge`,
`history_graph`, `statistics_graph`, `sensor`, `statistic`, `markdown`
(including a Jinja template `content=`, passed through verbatim -- HA renders
it, Hassle never inspects it), `clock`, `calendar`, `logbook`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-visual", title="Visual & History")
def cards_visual():
    with view(title="Visual", type="masonry"):
        c.gauge(
            "sensor.cpu_temp",
            name="CPU Temp",
            unit="°C",
            min=0,
            max=100,
            needle=True,
            severity={"green": 0, "yellow": 60, "red": 85},
        )
        c.history_graph(
            "sensor.cpu_temp",
            "sensor.living_room_temp",
            {"entity": "sensor.attic_temp", "name": "Attic"},
            title="Temperatures",
            hours_to_show=48,
            show_names=True,
        )
        c.statistics_graph(
            "sensor.energy_usage",
            title="Energy",
            stat_types=["mean", "max"],
            period="hour",
            days_to_show=7,
        )
        c.sensor(
            "sensor.cpu_temp",
            name="CPU",
            graph="line",
            detail=2,
            hours_to_show=24,
            unit="°C",
        )
        c.statistic(
            "sensor.energy_usage",
            name="Energy this month",
            stat_type="sum",
            period={"calendar": {"period": "month"}},
        )
        c.markdown(
            "## Status\n\nCurrent temp: {{ states('sensor.cpu_temp') }}°C",
            title="Status",
        )
        c.clock(clock_style="analog", show_seconds=True, time_format="24")
        c.calendar(
            "calendar.family",
            "calendar.work",
            initial_view="listWeek",
            title="Schedule",
        )
        c.logbook("sensor.cpu_temp", hours_to_show=12, title="Recent activity")
