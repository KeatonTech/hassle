"""``hassle.testing`` — the pytest simulator harness (DESIGN §10, F3-adjacent
frozen surface: M7/M9 build against this).

::

    from hassle.testing import simulate

    def test_motion_turns_on_light_at_night(sim):
        sim.at("2026-07-03 22:30")
        sim.set_state("input_boolean.guest_mode", "off")
        sim.state_change("binary_sensor.hall_motion", "off", "on")
        sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)
        sim.advance(minutes=5)
        sim.assert_called("light.turn_off", entity_id="light.hallway")

I5 (DESIGN §2): the simulator executes *compiled IR* -- a
:class:`~hassle.compiler.bundle.CompileResult`, whatever produced it
(:func:`~hassle.compiler.bundle.compile_bundle` for a
real bundle, or IR :func:`~hassle.ir.parse` directly for a corpus JSON config
that never existed as DSL, :mod:`test_sim_runs_compiled_ir_only`) -- never DSL
Python. :class:`Simulator` and :func:`simulate` accept only that IR-shaped
input.

Public surface (this module + :mod:`hassle.testing.plugin`):

- :func:`simulate` / :class:`Simulator` -- construct a simulator from a
  compiled bundle.
- :class:`ServiceCall` -- one recorded (never executed) service-call action.
- :class:`UnsupportedTemplateError` -- an out-of-subset Jinja construct.
- the ``sim`` pytest fixture (:mod:`hassle.testing.plugin`, registered as a
  ``pytest11`` entry point on the ``hassle-core`` distribution).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from hassle.compiler import compile_bundle
from hassle.compiler.bundle import CompileResult
from hassle.ir.models import AutomationConfig
from hassle.testing.calls import ServiceCall
from hassle.testing.clock import FakeClock, parse_datetime
from hassle.testing.engine import AutomationEngine
from hassle.testing.errors import UnsupportedTemplateError
from hassle.testing.state import StateStore
from hassle.testing.templates import TemplateEngine

__all__ = [
    "ServiceCall",
    "Simulator",
    "UnsupportedTemplateError",
    "simulate",
]


class Simulator:
    """Deterministic HA simulator over a compiled bundle (DESIGN §10.1).

    Construct directly from a :class:`~hassle.compiler.bundle.CompileResult`
    (I5: only compiled IR is ever accepted), or via :func:`simulate` for the
    common "compile this bundle directory" case.
    """

    def __init__(self, compiled: CompileResult) -> None:
        self._compiled = compiled
        self._clock = FakeClock()
        self._states = StateStore()
        self._calls: list[ServiceCall] = []
        self._templates = TemplateEngine(self._states, lambda: self._clock.now)
        self._sun_times_raw: dict[str, str] = {}
        self._engines: list[AutomationEngine] = []
        self._engines_by_key: dict[str, AutomationEngine] = {}
        for key, obj in compiled.objects.items():
            if not isinstance(obj, AutomationConfig):
                continue
            engine = AutomationEngine(
                key,
                obj.to_ha(),
                states=self._states,
                templates=self._templates,
                calls=self._calls,
                clock_now=lambda: self._clock.now,
                sun_times=self._sun_times_today,
            )
            self._engines.append(engine)
            self._engines_by_key[key] = engine
        self._states.on_change(self._on_state_change)

    # -- clock -----------------------------------------------------------------

    def at(self, when: str) -> None:
        """Pin the fake clock to an absolute starting moment.

        Fires a `time` trigger landing exactly on this moment (the common
        "set the clock to the trigger time" test pattern) but never a
        `time_pattern` trigger, since a periodic pattern "catching up" for
        every instant between wherever the clock was and here would be
        surprising for a jump rather than a walk -- only a subsequent
        :meth:`advance` walks through intervening moments one second at a
        time. Sun baseline state is established silently too; only a later
        :meth:`advance` that *crosses* a configured sunrise/sunset fires the
        sun trigger. Pending `delay`/`wait` deadlines and `for:` holds are
        still re-checked, since a bundle-author may reasonably jump the clock
        mid-run.
        """
        self._clock.set(parse_datetime(when))
        self._prime_sun_baseline()
        for engine in self._engines:
            engine.on_time(self._clock.now, patterns=False)
            engine.check_due(self._clock.now)

    def advance(self, *, hours: int = 0, minutes: int = 0, seconds: int = 0) -> None:
        """Advance the fake clock, firing every due time trigger/delay/wait in order.

        Steps second-by-second internally so `time`/`time_pattern` triggers and
        `for:` holds landing at intermediate moments are never skipped over
        (R8: deterministic, no wall-clock).
        """
        total = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        remaining = int(total.total_seconds())
        for _ in range(remaining):
            self._clock.advance(timedelta(seconds=1))
            self._check_due()

    def _check_due(self) -> None:
        now = self._clock.now
        for engine in self._engines:
            engine.on_time(now)
            engine.check_due(now)
            engine.check_sun(self._sun_times_today())

    # -- sun ---------------------------------------------------------------------

    def set_sun_times(self, *, sunrise: str, sunset: str) -> None:
        """Configure today's sunrise/sunset (DESIGN §10.1: "sun (configurable
        sunrise/sunset)"). Checked every second of :meth:`advance`/:meth:`at`."""
        self._sun_times_raw = {"sunrise": sunrise, "sunset": sunset}
        self._prime_sun_baseline()

    def _sun_times_today(self) -> dict[str, datetime]:
        today = self._clock.now.date()
        out: dict[str, datetime] = {}
        for event, at_str in self._sun_times_raw.items():
            hour, minute, *rest = (int(p) for p in at_str.split(":"))
            second = rest[0] if rest else 0
            out[event] = datetime(today.year, today.month, today.day, hour, minute, second)
        return out

    def _prime_sun_baseline(self) -> None:
        """Establish each sun trigger's past/future baseline silently (no fire)
        against the *current* clock, so a later crossing (not "was already
        past when configured/jumped to") is what actually fires it."""
        if not self._sun_times_raw:
            return
        sun_times = self._sun_times_today()
        for engine in self._engines:
            engine.prime_sun_baseline(sun_times)

    # -- state ---------------------------------------------------------------

    def set_state(
        self, entity_id: str, state: str, attributes: dict[str, Any] | None = None
    ) -> None:
        """Set an entity's state without asserting a specific prior value."""
        self._states.set(entity_id, state, attributes)

    def state_change(
        self,
        entity_id: str,
        from_state: str,
        to_state: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Set the prior state, then transition to ``to_state`` (fires triggers).

        The ``from_state`` seed is silent (no trigger evaluation) -- only the
        ``to_state`` transition is an observed change, matching what a real
        from/to trigger actually reacts to.
        """
        self._states.seed(entity_id, from_state)
        self._states.set(entity_id, to_state, attributes)

    def _on_state_change(self, change: Any) -> None:
        for engine in self._engines:
            engine.on_state_change(change)

    # -- events ----------------------------------------------------------------

    def fire_event(self, event_type: str, **event_data: Any) -> None:
        for engine in self._engines:
            engine.on_event(event_type, event_data)

    # -- purpose triggers / manual firing (DESIGN §10.1) ------------------------

    def fire(self, automation: str, *, trigger_ctx: dict[str, Any] | None = None) -> None:
        """Run ``automation``'s action sequence directly, bypassing trigger AND
        condition evaluation (DESIGN §10.1: the documented path for
        purpose-specific triggers/conditions, which the simulator does not
        evaluate in v1 -- "no automation is untestable, some just skip
        trigger evaluation"). ``automation`` is an object key
        (``"automation:<id>"``)."""
        engine = self._engines_by_key.get(automation)
        if engine is None:
            raise KeyError(
                f"no automation with object key {automation!r} in this bundle; known keys: "
                f"{sorted(self._engines_by_key)}"
            )
        engine.fire(trigger_ctx)

    # -- assertions --------------------------------------------------------------

    def calls(self, action: str) -> list[ServiceCall]:
        """All recorded calls to ``action`` (e.g. ``"light.turn_on"``), in order."""
        return [c for c in self._calls if c.action == action]

    def assert_called(self, action: str, *, times: int | None = None, **data: Any) -> None:
        """Assert ``action`` was called with (at least) the given ``data`` kwargs.

        Matching is a subset match: only the given kwargs are checked, so a
        caller who only cares about ``entity_id`` needn't spell out every
        other field. ``times=`` asserts an exact call count (matching this
        subset), default: at least one call.
        """
        matches = [c for c in self.calls(action) if _matches_subset(c.data, data)]
        if times is not None:
            assert len(matches) == times, (
                f"expected {action!r} called {times} time(s) with {data!r}, got "
                f"{len(matches)} (all {action!r} calls: {[c.data for c in self.calls(action)]})"
            )
        else:
            assert matches, (
                f"expected {action!r} to have been called with {data!r}, but it was not "
                f"(all {action!r} calls: {[c.data for c in self.calls(action)]})"
            )

    def assert_not_called(self, action: str, **data: Any) -> None:
        matches = [c for c in self.calls(action) if _matches_subset(c.data, data)]
        assert not matches, (
            f"expected {action!r} not to have been called with {data!r}, but it was: "
            f"{[c.data for c in matches]}"
        )


def _matches_subset(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(key in actual and actual[key] == value for key, value in expected.items())


def simulate(bundle_dir: str | Path) -> Simulator:
    """Compile ``bundle_dir`` (DESIGN §7.2) and return a fresh :class:`Simulator`."""
    return Simulator(compile_bundle(bundle_dir))
