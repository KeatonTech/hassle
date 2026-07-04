"""M4 test 2: mode semantics (DESIGN §10.1) -- the heart of the simulator.

restart cancels a pending delay (the canonical motion-light bug); single drops
a re-trigger while running; queued runs the second trigger after the first
finishes; parallel interleaves (both instances' actions land, not serialized).
Plus max / max_exceeded.
"""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim

_RESTART_BUNDLE = """
    from hassle import automation, delay, service, state, when

    @automation(id="a", alias="a", mode="restart")
    def a():
        when(state("binary_sensor.motion").to("on"))
        service("light.turn_on", entity_id="light.hallway")
        delay(minutes=2)
        service("light.turn_off", entity_id="light.hallway")
    """

_SINGLE_BUNDLE = """
    from hassle import automation, delay, service, state, when

    @automation(id="a", alias="a", mode="single")
    def a():
        when(state("binary_sensor.motion").to("on"))
        service("light.turn_on", entity_id="light.hallway")
        delay(minutes=2)
        service("light.turn_off", entity_id="light.hallway")
    """

_QUEUED_BUNDLE = """
    from hassle import automation, delay, service, state, when

    @automation(id="a", alias="a", mode="queued", max=5)
    def a():
        when(state("binary_sensor.motion").to("on"))
        service("light.turn_on", entity_id="light.hallway")
        delay(minutes=2)
        service("light.turn_off", entity_id="light.hallway")
    """

_PARALLEL_BUNDLE = """
    from hassle import automation, delay, service, state, when

    @automation(id="a", alias="a", mode="parallel", max=10)
    def a():
        when(state("binary_sensor.motion").to("on"))
        service("light.turn_on", entity_id="light.hallway")
        delay(minutes=2)
        service("light.turn_off", entity_id="light.hallway")
    """


# ---------------------------------------------------------------------------
# restart -- cancels a pending delay (the canonical motion-light bug)
# ---------------------------------------------------------------------------


def test_restart_cancels_pending_delay(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _RESTART_BUNDLE)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=1)
    # Re-trigger before the delay expires: restart cancels the pending
    # `delay` + `light.turn_off`, and starts the run over from the top.
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=2)
    # The *original* run's turn_off must never fire at its original T+2min.
    sim.advance(minutes=1)
    sim.assert_not_called("light.turn_off")
    # The new run's own delay does expire, 2 minutes after its own start.
    sim.advance(minutes=1)
    sim.assert_called("light.turn_off", times=1)


def test_restart_single_run_completes_normally(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _RESTART_BUNDLE)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=2)
    sim.assert_called("light.turn_on", times=1)
    sim.assert_called("light.turn_off", times=1)


# ---------------------------------------------------------------------------
# single -- drops a re-trigger while running
# ---------------------------------------------------------------------------


def test_single_drops_retrigger_while_running(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _SINGLE_BUNDLE)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=1)
    # Re-trigger while the first run is still in its delay: dropped entirely.
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=1)
    # Original run's turn_off still fires at its own T+2min.
    sim.assert_called("light.turn_off", times=1)


def test_single_accepts_new_trigger_after_completion(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _SINGLE_BUNDLE)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=2)
    sim.assert_called("light.turn_on", times=1)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=2)


# ---------------------------------------------------------------------------
# queued -- runs the second trigger after the first finishes
# ---------------------------------------------------------------------------


def test_queued_runs_second_trigger_after_first_finishes(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _QUEUED_BUNDLE)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=1)
    # Second trigger arrives mid-run: queued, does not start until the first
    # run's `delay` + `turn_off` complete.
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=1)
    # First run completes (T+2min from its own start).
    sim.assert_called("light.turn_off", times=1)
    # The queued run starts immediately after.
    sim.assert_called("light.turn_on", times=2)
    sim.advance(minutes=2)
    sim.assert_called("light.turn_off", times=2)


def test_queued_respects_max_queue_depth(tmp_path: Path) -> None:
    source = """
        from hassle import automation, delay, service, state, when

        @automation(id="a", alias="a", mode="queued", max=1)
        def a():
            when(state("binary_sensor.motion").to("on"))
            service("light.turn_on", entity_id="light.hallway")
            delay(minutes=2)
            service("light.turn_off", entity_id="light.hallway")
        """
    sim = build_sim(tmp_path, source)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    # max=1: only one run may be queued behind the active one. Two more
    # triggers arrive; the queue (depth 1) holds the first, the second is
    # dropped (max_exceeded behavior).
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=2)
    sim.assert_called("light.turn_on", times=2)
    sim.advance(minutes=2)
    # No third run: the extra trigger over max was dropped, not queued twice.
    sim.assert_called("light.turn_on", times=2)


# ---------------------------------------------------------------------------
# parallel -- interleaves; each run's actions land independently
# ---------------------------------------------------------------------------


def test_parallel_runs_interleave(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _PARALLEL_BUNDLE)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=1)
    # Second trigger starts a concurrent, independent run (not queued/dropped).
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=2)
    # First run's delay expires at its own T+2min -- fires while the second
    # run's delay is still pending (interleaved, not serialized).
    sim.advance(minutes=1)
    sim.assert_called("light.turn_off", times=1)
    sim.assert_called("light.turn_on", times=2)
    sim.advance(minutes=1)
    sim.assert_called("light.turn_off", times=2)


def test_parallel_max_exceeded_drops_extra_runs(tmp_path: Path) -> None:
    source = """
        from hassle import automation, delay, service, state, when

        @automation(id="a", alias="a", mode="parallel", max=1, max_exceeded="silent")
        def a():
            when(state("binary_sensor.motion").to("on"))
            service("light.turn_on", entity_id="light.hallway")
            delay(minutes=2)
            service("light.turn_off", entity_id="light.hallway")
        """
    sim = build_sim(tmp_path, source)
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    # max=1: a second concurrent trigger while the first is still running
    # must be dropped (not queued, not run in parallel).
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    sim.advance(minutes=2)
    sim.assert_called("light.turn_off", times=1)
    # After the run completes, a fresh trigger starts a new run again.
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", times=2)
