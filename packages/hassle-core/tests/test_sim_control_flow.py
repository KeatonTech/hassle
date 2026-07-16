"""Choose/if branch selection incl. default; repeat while/until/count/for_each."""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim

# ---------------------------------------------------------------------------
# if_then / else_then
# ---------------------------------------------------------------------------


def test_if_then_true_branch(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, else_then, if_then, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with if_then(state("person.kai").is_("home")):
                service("notify.mobile_app", message="welcome home")
            with else_then():
                service("notify.mobile_app", message="away")
        """,
    )
    sim.set_state("person.kai", "home")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="welcome home")
    sim.assert_not_called("notify.mobile_app", message="away")


def test_if_then_else_branch(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, else_then, if_then, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with if_then(state("person.kai").is_("home")):
                service("notify.mobile_app", message="welcome home")
            with else_then():
                service("notify.mobile_app", message="away")
        """,
    )
    sim.set_state("person.kai", "not_home")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="away")
    sim.assert_not_called("notify.mobile_app", message="welcome home")


# ---------------------------------------------------------------------------
# choose / default
# ---------------------------------------------------------------------------


def test_choose_selects_first_matching_branch(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, choose, numeric_state, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with choose() as c:
                with c.when_(numeric_state("sensor.temp", above=30)):
                    service("notify.mobile_app", message="hot")
                with c.when_(numeric_state("sensor.temp", above=20)):
                    service("notify.mobile_app", message="warm")
                with c.default():
                    service("notify.mobile_app", message="cold")
        """,
    )
    sim.set_state("sensor.temp", "25")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="warm")
    sim.assert_not_called("notify.mobile_app", message="hot")
    sim.assert_not_called("notify.mobile_app", message="cold")


def test_choose_falls_through_to_default(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, choose, numeric_state, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with choose() as c:
                with c.when_(numeric_state("sensor.temp", above=30)):
                    service("notify.mobile_app", message="hot")
                with c.default():
                    service("notify.mobile_app", message="cold")
        """,
    )
    sim.set_state("sensor.temp", "10")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="cold")


def test_choose_no_default_and_no_match_calls_nothing(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, choose, numeric_state, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with choose() as c:
                with c.when_(numeric_state("sensor.temp", above=30)):
                    service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "10")
    sim.state_change("button.go", "off", "on")
    sim.assert_not_called("notify.mobile_app")


# ---------------------------------------------------------------------------
# repeat: count / while / until / for_each
# ---------------------------------------------------------------------------


def test_repeat_count_runs_exact_number_of_times(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, repeat_count, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with repeat_count(3):
                service("light.toggle", entity_id="light.porch")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("light.toggle", times=3)


def test_repeat_while_runs_until_condition_false(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, repeat_while, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with repeat_while(template("{{ repeat.index <= 3 }}")):
                service("light.toggle", entity_id="light.porch")
        """,
    )
    sim.state_change("button.go", "off", "on")
    # while: condition checked *before* each iteration, using HA's built-in
    # `repeat.index` (1-based) -- runs for index 1, 2, 3, stops at 4.
    sim.assert_called("light.toggle", times=3)


def test_repeat_while_false_from_the_start_never_runs(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, repeat_while, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with repeat_while(template("{{ repeat.index <= 0 }}")):
                service("light.toggle", entity_id="light.porch")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_not_called("light.toggle")


def test_repeat_until_runs_at_least_once(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, repeat_until, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with repeat_until(template("{{ repeat.index >= 1 }}")):
                service("light.toggle", entity_id="light.porch")
        """,
    )
    sim.state_change("button.go", "off", "on")
    # until: condition checked *after* each iteration -- runs exactly once
    # since `repeat.index >= 1` is already true after the first pass.
    sim.assert_called("light.toggle", times=1)


def test_repeat_until_runs_multiple_times(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, repeat_until, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with repeat_until(template("{{ repeat.index >= 3 }}")):
                service("light.toggle", entity_id="light.porch")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("light.toggle", times=3)


def test_repeat_for_each_runs_per_item(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, repeat_for_each, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with repeat_for_each(["light.a", "light.b", "light.c"]):
                service("light.toggle", entity_id="light.a")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("light.toggle", times=3)
