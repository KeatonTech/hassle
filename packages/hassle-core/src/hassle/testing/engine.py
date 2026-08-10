"""The simulator engine: ties the clock, state store, trigger evaluator, and
action executor together with mode semantics (DESIGN §10.1).

One :class:`AutomationEngine` per compiled automation. The top-level
:class:`Simulator` (``hassle/testing/__init__.py``) owns one engine per
automation object plus the shared clock/state/template machinery, and fans
out every stimulus (state change, clock advance, event, explicit fire) to
each engine in turn.

Mode semantics:

- ``single`` (default): a new trigger while a run is active is dropped.
- ``restart``: a new trigger cancels the active run (including any pending
  `delay`/`wait_for_trigger`) and starts fresh.
- ``queued``: a new trigger while a run is active is queued (up to ``max``,
  default 10) and started when the active run completes.
- ``parallel``: a new trigger always starts a new, independent run, up to
  ``max`` concurrent runs (default 10); beyond that, ``max_exceeded``
  determines whether it's dropped silently or logged (the simulator only
  models the "extra run is dropped" behavior -- logging is a real-HA concern
  out of scope here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from hassle.testing.actions import (
    ActionContext,
    EventOccurrence,
    SunTimesProvider,
    Suspend,
    SuspendDelay,
    SuspendWaitForTrigger,
    SuspendWaitTemplate,
    WaitResumeValue,
    base_trigger_context,
    evaluate_condition,
    no_sun_times,
    run_actions,
    state_change_trigger_context,
)
from hassle.testing.calls import ServiceCall
from hassle.testing.state import StateChange, StateStore
from hassle.testing.templates import TemplateEngine
from hassle.testing.triggers import (
    ForDuration,
    for_duration_of,
    is_event_trigger,
    is_numeric_state_trigger,
    is_state_trigger,
    is_sun_trigger,
    is_template_trigger,
    is_time_pattern_trigger,
    is_time_trigger,
    is_zone_trigger,
    numeric_state_crosses,
    parse_offset,
    state_trigger_matches,
    template_trigger_edge,
    time_matches,
    time_pattern_matches,
    zone_trigger_matches,
)

_DEFAULT_MAX = 10


def _empty_str_any_dict() -> dict[str, Any]:
    return {}


def _epoch() -> datetime:
    return datetime(1970, 1, 1)


@dataclass
class _Run:
    """One in-flight (or queued) execution of an automation's action sequence."""

    generator: Any  # Generator[Suspend, WaitResumeValue, bool] | None (None while queued)
    ctx: ActionContext
    pending: Suspend | None = None
    wake_at: datetime | None = None
    started_at: datetime = field(default_factory=_epoch)
    trigger_ctx: dict[str, Any] = field(default_factory=_empty_str_any_dict)


class AutomationEngine:
    """Runs one compiled automation against shared clock/state/templates."""

    def __init__(
        self,
        object_key: str,
        config: dict[str, Any],
        *,
        states: StateStore,
        templates: TemplateEngine,
        calls: list[ServiceCall],
        clock_now: Any,
        sun_times: SunTimesProvider = no_sun_times,
        scripts: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.object_key = object_key
        self.config = config
        self._states = states
        self._templates = templates
        self._calls = calls
        self._clock_now = clock_now
        self._sun_times = sun_times
        # Bundle scripts by slug, threaded into every run's ActionContext so
        # direct `script.<slug>` calls expand inline.
        self._scripts = scripts if scripts is not None else {}
        self.mode = config.get("mode", "single")
        self.max = int(config.get("max", _DEFAULT_MAX))
        default_max_exceeded = "single" if self.mode != "parallel" else "silent"
        self.max_exceeded = config.get("max_exceeded", default_max_exceeded)
        self._active: list[_Run] = []
        self._queue: list[_Run] = []
        # Per-trigger `for:` hold state: trigger index -> (deadline, expected
        # StateChange, the trigger context captured when the hold STARTED --
        # a held trigger must fire with the context of the change that began
        # the hold, not one rebuilt at expiry).
        self._pending_for: dict[int, tuple[datetime, StateChange, dict[str, Any]]] = {}
        # Template-trigger previous-truth cache, by trigger index.
        self._template_truth: dict[int, bool] = {}
        # Sun-trigger previous-past cache (offset-adjusted), by trigger index.
        self._sun_past: dict[int, bool] = {}

    def _entity_state(self, entity_id: str) -> str | None:
        """Entity-state lookup for `at: <entity>` time triggers."""
        state = self._states.get(entity_id)
        return state.state if state is not None else None

    # -- stimulus entry points -------------------------------------------------

    def on_state_change(self, change: StateChange) -> None:
        # First, resume any run waiting on a matching wait_for_trigger.
        self._resume_waits_on_state(change)
        # Then, evaluate this automation's own triggers for a fresh start.
        for index, trigger in enumerate(self.config.get("triggers", [])):
            if is_state_trigger(trigger):
                if not state_trigger_matches(trigger, change):
                    self._pending_for.pop(index, None)
                    continue
                self._handle_state_match(index, trigger, change)
            elif is_numeric_state_trigger(trigger):
                if numeric_state_crosses(trigger, change):
                    self._start_or_queue(
                        trigger_ctx=state_change_trigger_context(
                            trigger, index, "numeric_state", change
                        )
                    )
            elif is_zone_trigger(trigger):
                if zone_trigger_matches(trigger, change):
                    self._start_or_queue(
                        trigger_ctx=state_change_trigger_context(trigger, index, "zone", change)
                    )
            elif is_template_trigger(trigger):
                self._evaluate_template_trigger(index, trigger, change)

    def _handle_state_match(self, index: int, trigger: dict[str, Any], change: StateChange) -> None:
        trigger_ctx = state_change_trigger_context(trigger, index, "state", change)
        for_duration: ForDuration | None = for_duration_of(trigger)
        if for_duration is None:
            self._pending_for.pop(index, None)
            self._start_or_queue(trigger_ctx=trigger_ctx)
            return
        deadline = self._clock_now() + timedelta(seconds=for_duration.total_seconds())
        self._pending_for[index] = (deadline, change, trigger_ctx)

    def _evaluate_template_trigger(
        self, index: int, trigger: dict[str, Any], change: StateChange
    ) -> None:
        ctx = ActionContext(
            states=self._states,
            templates=self._templates,
            calls=[],
            sun_times=self._sun_times,
        )

        def _render_now() -> bool:
            rendered = ctx.render(trigger["value_template"])
            return str(rendered).strip().lower() in ("true", "1", "yes", "on")

        if index not in self._template_truth:
            # First time this trigger is evaluated: establish its baseline
            # truth value as of *before* this change (so a change that lands
            # on an already-true template doesn't spuriously look like an
            # edge) by temporarily rolling the changed entity back to its
            # prior state, evaluating, then restoring -- the template may
            # reference other entities too, but this is the one that just
            # changed and is therefore the only one whose "before" value we
            # can reconstruct.
            if change.old is not None:
                self._states.seed(change.entity_id, change.old.state, change.old.attributes)
                self._template_truth[index] = _render_now()
                self._states.seed(change.entity_id, change.new.state, change.new.attributes)
            else:
                self._template_truth[index] = False
        is_true = _render_now()
        was_true = self._template_truth[index]
        self._template_truth[index] = is_true
        if template_trigger_edge(trigger, was_true, is_true):
            self._start_or_queue(
                trigger_ctx=state_change_trigger_context(trigger, index, "template", change)
            )

    def on_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        # First, resume any run waiting on a matching wait_for_trigger (task
        # #32, docs/internals/ha-api-notes.md §36.2 gap 1: this previously only ever
        # started NEW runs via `_start_or_queue` below, so a run already
        # suspended inside `wait_for_trigger([event(...)])` was never woken
        # by a fired event -- mirrors `on_state_change`'s own
        # resume-then-start-fresh order).
        self._resume_waits_on_event(EventOccurrence(event_type, event_data))
        # Then, evaluate this automation's own triggers for a fresh start.
        for index, trigger in enumerate(self.config.get("triggers", [])):
            if is_event_trigger(trigger) and trigger.get("event_type") == event_type:
                self._start_or_queue(
                    trigger_ctx={
                        **base_trigger_context(trigger, index, "event"),
                        # `trigger.event.data.*` is long-standing behavior and
                        # keeps its exact shape; `event_type` is additive.
                        "event": {"event_type": event_type, "data": event_data},
                    }
                )

    def on_time(self, moment: datetime, *, patterns: bool = True) -> None:
        for index, trigger in enumerate(self.config.get("triggers", [])):
            is_due_time = is_time_trigger(trigger) and time_matches(
                trigger, moment, resolve_entity=self._entity_state
            )
            is_pattern_trigger = patterns and is_time_pattern_trigger(trigger)
            is_due_pattern = is_pattern_trigger and time_pattern_matches(trigger, moment)
            if is_due_time or is_due_pattern:
                platform = "time" if is_due_time else "time_pattern"
                self._start_or_queue(trigger_ctx=base_trigger_context(trigger, index, platform))

    def check_sun(self, sun_times: dict[str, datetime]) -> None:
        """Evaluate every ``sun`` trigger's own offset against today's configured
        sunrise/sunset (DESIGN §10.1: "sun (configurable sunrise/sunset)").

        Each trigger's ``offset:`` shifts *when that trigger considers the
        event to have happened* -- e.g. ``offset="-00:30:00"`` fires 30
        minutes before the base sunset moment -- so this is evaluated
        per-trigger rather than as one shared "sunset happened" broadcast.
        """
        if not sun_times:
            return
        now = self._clock_now()
        triggers: list[dict[str, Any]] = self.config.get("triggers", [])
        for index, is_past in self._sun_past_states(sun_times, now):
            was_past = self._sun_past.get(index, False)
            self._sun_past[index] = is_past
            if is_past and not was_past:
                self._start_or_queue(
                    trigger_ctx=base_trigger_context(triggers[index], index, "sun")
                )

    def prime_sun_baseline(self, sun_times: dict[str, datetime]) -> None:
        """Silently establish each sun trigger's past/future baseline (no fire)."""
        now = self._clock_now()
        for index, is_past in self._sun_past_states(sun_times, now):
            self._sun_past[index] = is_past

    def _sun_past_states(
        self, sun_times: dict[str, datetime], now: datetime
    ) -> list[tuple[int, bool]]:
        out: list[tuple[int, bool]] = []
        for index, trigger in enumerate(self.config.get("triggers", [])):
            if not is_sun_trigger(trigger):
                continue
            base = sun_times.get(trigger.get("event"))
            if base is None:
                continue
            target = base + parse_offset(trigger.get("offset"))
            out.append((index, now >= target))
        return out

    def fire(self, trigger_ctx: dict[str, Any] | None) -> None:
        """``sim.fire(...)``: bypass trigger AND condition evaluation entirely."""
        self._start_or_queue(trigger_ctx=trigger_ctx or {}, skip_conditions=True)

    # -- run lifecycle ----------------------------------------------------------

    def _conditions_pass(self) -> bool:
        conditions = self.config.get("conditions", [])
        if not conditions:
            return True
        ctx = ActionContext(
            states=self._states,
            templates=self._templates,
            calls=[],
            sun_times=self._sun_times,
        )
        return all(evaluate_condition(c, ctx) for c in conditions)

    def _start_or_queue(
        self, *, trigger_ctx: dict[str, Any], skip_conditions: bool = False
    ) -> None:
        if not skip_conditions and not self._conditions_pass():
            return
        if self.mode == "single":
            if self._active:
                return
            self._launch(trigger_ctx)
        elif self.mode == "restart":
            for run in self._active:
                run.generator.close()
            self._active.clear()
            self._launch(trigger_ctx)
        elif self.mode == "queued":
            if not self._active:
                self._launch(trigger_ctx)
            elif len(self._queue) < self.max:
                self._queue.append(self._make_run(trigger_ctx, queued=True))
            # else: dropped (queue full).
        elif self.mode == "parallel":
            if len(self._active) < self.max:
                self._launch(trigger_ctx)
            # else: dropped (max_exceeded -- "silent" modeled as drop).

    def _make_run(self, trigger_ctx: dict[str, Any], *, queued: bool) -> _Run:
        ctx = ActionContext(
            states=self._states,
            templates=self._templates,
            calls=self._calls,
            trigger_ctx=trigger_ctx,
            sun_times=self._sun_times,
            scripts=self._scripts,
        )
        gen = None if queued else run_actions(self.config.get("actions", []), ctx)
        return _Run(generator=gen, ctx=ctx, started_at=self._clock_now(), trigger_ctx=trigger_ctx)

    def _launch(self, trigger_ctx: dict[str, Any]) -> None:
        run = self._make_run(trigger_ctx, queued=False)
        self._active.append(run)
        self._advance_run(run, resume_value=None)

    def _advance_run(self, run: _Run, *, resume_value: WaitResumeValue) -> None:
        try:
            suspend = run.generator.send(resume_value)
        except StopIteration:
            self._finish_run(run)
            return
        run.pending = suspend
        if isinstance(suspend, SuspendDelay):
            run.wake_at = self._clock_now() + suspend.duration
        elif isinstance(suspend, SuspendWaitForTrigger | SuspendWaitTemplate):
            run.wake_at = self._clock_now() + suspend.timeout if suspend.timeout else None

    def _finish_run(self, run: _Run) -> None:
        if run in self._active:
            self._active.remove(run)
        if self.mode == "queued" and self._queue:
            next_run = self._queue.pop(0)
            next_run.generator = run_actions(self.config.get("actions", []), next_run.ctx)
            next_run.started_at = self._clock_now()
            self._active.append(next_run)
            self._advance_run(next_run, resume_value=None)

    def _resume_waits_on_state(self, change: StateChange) -> None:
        for run in list(self._active):
            if isinstance(run.pending, SuspendWaitForTrigger):
                self._advance_run(run, resume_value=change)
            elif isinstance(run.pending, SuspendWaitTemplate):
                # wait_template has no explicit "trigger" shape -- re-check the
                # template on every state change (any of them might be its
                # dependency); the generator itself no-ops if still false.
                self._advance_run(run, resume_value=change)

    def _resume_waits_on_event(self, occurrence: EventOccurrence) -> None:
        """The event-carrying counterpart of :meth:`_resume_waits_on_state`.
        Only ``wait_for_trigger`` is resumable by an event --
        ``wait_template`` has no event-shaped dependency to react to (it only
        ever re-renders on a *state* change, per DESIGN §10.1's template
        subset), so it is deliberately not woken here.
        """
        for run in list(self._active):
            if isinstance(run.pending, SuspendWaitForTrigger):
                self._advance_run(run, resume_value=occurrence)

    # -- clock -------------------------------------------------------------------

    def check_due(self, now: datetime) -> None:
        # `for:` holds: fire if the deadline passed and the state still holds,
        # carrying the context captured when the hold started.
        for index, (deadline, change, trigger_ctx) in list(self._pending_for.items()):
            if now >= deadline:
                current = self._states.get(change.entity_id)
                still_holds = current is not None and current.state == change.new.state
                del self._pending_for[index]
                if still_holds:
                    self._start_or_queue(trigger_ctx=trigger_ctx)
        # Delays and wait timeouts.
        for run in list(self._active):
            waitable_types = SuspendDelay | SuspendWaitForTrigger | SuspendWaitTemplate
            is_waitable = isinstance(run.pending, waitable_types)
            if run.wake_at is not None and now >= run.wake_at and is_waitable:
                run.wake_at = None
                self._advance_run(run, resume_value=None)
