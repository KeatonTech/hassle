"""Template subset goldens + test_unsupported_template_raises.

The simulator's Jinja environment must register HA's extension functions
(`states`, `is_state`, `state_attr`, `now`, `today_at`, `as_timestamp`, `iif`,
`float`/`int`/`round` filters, timedelta arithmetic) AND HA's math globals/
filters that stock jinja2 lacks (sin/cos/tan/asin/acos/atan/atan2/sqrt/log,
pi/e/tau, round/min/max/abs), plus `variables:` scope resolution. Anything
outside the supported subset raises `UnsupportedTemplateError` naming the
construct and pointing at `hassle render --live` -- never silently wrong.

Also covers (bottom of this file): bare `states()`/string-equality templates
(the `state_of(...)` DSL surface's compiled output) evaluate correctly too --
verified directly rather than assumed, since `states()` already returns a
plain Python `str` and stock jinja2's own `==`/`in` operators need no HA-
specific registration to work on it (unlike `is_state`/`state_attr`, which
DO need the explicit globals registered above).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from _sim_helpers import build_sim

from hassle.testing import UnsupportedTemplateError

# ---------------------------------------------------------------------------
# core HA extensions: states() / is_state() / state_attr() / iif
# ---------------------------------------------------------------------------


def test_template_states_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template("{{ states('sensor.temp') }}"))
        """,
    )
    sim.set_state("sensor.temp", "21.5")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="21.5")


def test_template_is_state_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ 'yes' if is_state('person.kai', 'home') else 'no' }}"),
            )
        """,
    )
    sim.set_state("person.kai", "home")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="yes")


def test_template_state_attr_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ state_attr('light.hallway', 'brightness') }}"),
            )
        """,
    )
    sim.set_state("light.hallway", "on", attributes={"brightness": 128})
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="128")


def test_template_iif_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template("{{ iif(1 > 0, 'yes', 'no') }}"))
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="yes")


def test_template_float_int_round_filters(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ (states('sensor.temp') | float | round(1)) }}"),
            )
        """,
    )
    sim.set_state("sensor.temp", "21.456")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="21.5")


def test_template_now_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template("{{ now().strftime('%H:%M') }}"))
        """,
    )
    sim.at("2026-07-03 08:15:00")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="08:15")


def test_template_today_at_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ (now() >= today_at('08:00:00')) }}"),
            )
        """,
    )
    sim.at("2026-07-03 08:15:00")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="True")


def test_template_as_timestamp_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ as_timestamp(now()) | int }}"),
            )
        """,
    )
    sim.at("2026-07-03 00:00:00")
    sim.state_change("button.go", "off", "on")
    calls = sim.calls("notify.mobile_app")
    assert calls[0].data["message"].isdigit()


# ---------------------------------------------------------------------------
# HA math globals/filters (stock jinja2 lacks these -- must be registered)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("{{ sin(0) }}", str(math.sin(0))),
        ("{{ cos(0) }}", str(math.cos(0))),
        ("{{ tan(0) }}", str(math.tan(0))),
        ("{{ sqrt(16) }}", str(math.sqrt(16))),
    ],
)
def test_template_math_functions(tmp_path: Path, expr: str, expected: str) -> None:
    sim = build_sim(
        tmp_path,
        f"""
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template({expr!r}))
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message=expected)


def test_template_asin_acos_atan_atan2(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ asin(1) }}|{{ acos(1) }}|{{ atan(1) }}|{{ atan2(1, 1) }}"),
            )
        """,
    )
    sim.state_change("button.go", "off", "on")
    expected = f"{math.asin(1)}|{math.acos(1)}|{math.atan(1)}|{math.atan2(1, 1)}"
    sim.assert_called("notify.mobile_app", message=expected)


def test_template_log_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template("{{ log(100, 10) }}"))
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message=str(math.log(100, 10)))


def test_template_pi_e_tau_constants(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template("{{ pi }}|{{ e }}|{{ tau }}"))
        """,
    )
    sim.state_change("button.go", "off", "on")
    expected = f"{math.pi}|{math.e}|{math.tau}"
    sim.assert_called("notify.mobile_app", message=expected)


def test_template_min_max_abs_round_builtins(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template(
                    "{{ min(3, 1, 2) }}|{{ max(3, 1, 2) }}|{{ abs(-5) }}|{{ round(3.14159, 2) }}"
                ),
            )
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="1|3|5|3.14")


def test_template_sun_angle_math_expression(tmp_path: Path) -> None:
    """DESIGN §5.4 acceptance example: `param("sun_angle") / 360 * 2 * PI`
    style math must actually evaluate in the simulator -- this is
    exactly the math-template class that would be untestable without the
    HA math set registered."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template(
                    "{{ (states('sensor.sun_angle') | float / 360 * 2 * pi) | round(4) }}"
                ),
            )
        """,
    )
    sim.set_state("sensor.sun_angle", "90")
    sim.state_change("button.go", "off", "on")
    expected = str(round(90 / 360 * 2 * math.pi, 4))
    sim.assert_called("notify.mobile_app", message=expected)


# ---------------------------------------------------------------------------
# variables: scope resolution in templates
# ---------------------------------------------------------------------------


def test_template_resolves_variables_scope(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, variables, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            variables(threshold=42)
            service("notify.mobile_app", message=template("{{ threshold }}"))
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="42")


def test_template_variables_scope_supports_expressions(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, variables, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            variables(base=10, offset=5)
            service("notify.mobile_app", message=template("{{ base + offset }}"))
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="15")


def test_template_trigger_variables_available_via_trigger_ctx(tmp_path: Path) -> None:
    """DESIGN §10.1: purpose-triggers (and any trigger) can be exercised via
    `sim.fire(automation, trigger_ctx={...})`; the `trigger.*` template
    namespace must resolve from that context."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, template, when, event

        @automation(id="a", alias="a")
        def a():
            when(event("my_event"))
            service("notify.mobile_app", message=template("{{ trigger.event.data.who }}"))
        """,
    )
    sim.fire("automation:a", trigger_ctx={"event": {"data": {"who": "kai"}}})
    sim.assert_called("notify.mobile_app", message="kai")


# ---------------------------------------------------------------------------
# UnsupportedTemplateError -- never silently wrong
# ---------------------------------------------------------------------------


def test_unsupported_template_raises_for_unknown_function(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ some_totally_unsupported_ha_function() }}"),
            )
        """,
    )
    with pytest.raises(UnsupportedTemplateError) as excinfo:
        sim.state_change("button.go", "off", "on")
    message = str(excinfo.value)
    assert "some_totally_unsupported_ha_function" in message
    assert "hassle render --live" in message


def test_unsupported_template_raises_for_bad_syntax(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("notify.mobile_app", message=template("{{ states( }}"))
        """,
    )
    with pytest.raises(UnsupportedTemplateError) as excinfo:
        sim.state_change("button.go", "off", "on")
    assert "hassle render --live" in str(excinfo.value)


def test_unsupported_template_raises_for_unknown_filter_names_the_filter(
    tmp_path: Path,
) -> None:
    """An unknown filter (`| some_unregistered_filter`) is a
    TemplateAssertionError (a TemplateSyntaxError subclass) whose own message
    already names the filter -- the error must surface that name instead of
    the generic "invalid template syntax"."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ states('sensor.temp') | some_unregistered_filter }}"),
            )
        """,
    )
    with pytest.raises(UnsupportedTemplateError) as excinfo:
        sim.state_change("button.go", "off", "on")
    message = str(excinfo.value)
    assert "some_unregistered_filter" in message
    assert "hassle render --live" in message


def test_unsupported_template_names_the_construct(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ integration_entities('mqtt') }}"),
            )
        """,
    )
    with pytest.raises(UnsupportedTemplateError) as excinfo:
        sim.state_change("button.go", "off", "on")
    assert "integration_entities" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Bare states()/string-equality templates (state_of(...) surface)
# ---------------------------------------------------------------------------


def test_bare_states_string_equality_evaluates_in_simulator(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state_of, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=state_of("sensor.time_of_day").eq("day"),
            )
        """,
    )
    sim.set_state("sensor.time_of_day", "day")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="True")


def test_bare_states_string_inequality_evaluates_in_simulator(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state_of, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=state_of("sensor.time_of_day").ne("night"),
            )
        """,
    )
    sim.set_state("sensor.time_of_day", "day")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="True")


def test_bare_states_string_membership_evaluates_in_simulator(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state_of, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=state_of("sensor.time_of_day").in_(["dawn", "dusk"]),
            )
        """,
    )
    sim.set_state("sensor.time_of_day", "dawn")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="True")


def test_only_if_condition_using_state_of_eq(tmp_path: Path) -> None:
    """`state_of(...).eq(...)` used as a `only_if(...)` template condition
    (DESIGN §5.4's `template()` condition path) gates the action correctly."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, only_if, service, state_of, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            only_if(state_of("sensor.time_of_day").eq("day"))
            service("notify.mobile_app", message="daytime action")
        """,
    )
    sim.set_state("sensor.time_of_day", "night")
    sim.state_change("button.go", "off", "on")
    assert sim.calls("notify.mobile_app") == []

    sim.set_state("sensor.time_of_day", "day")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="daytime action")
