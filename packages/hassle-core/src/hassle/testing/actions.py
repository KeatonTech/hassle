"""The action executor: interprets a compiled action list against live state.

Modeled as a Python generator (:func:`run_actions`) so `delay`/`wait_for_trigger`/
`wait_template` can suspend a run deterministically -- the generator yields a
:class:`Suspend` describing what it's waiting for, and the engine
(:mod:`hassle.testing.engine`) resumes it when the clock advances far enough or
a matching state change/event arrives. This is what lets `mode: restart` cancel
a run mid-`delay` by simply discarding its generator (Python generators clean
up via `.close()`, and nothing here holds external resources) -- no thread, no
real sleep, fully deterministic (R8).
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from hassle.testing.calls import ServiceCall
from hassle.testing.triggers import (
    is_numeric_state_trigger,
    is_state_trigger,
    is_zone_trigger,
    numeric_state_crosses,
    parse_offset,
    state_trigger_matches,
    zone_trigger_matches,
)

if TYPE_CHECKING:
    from hassle.testing.state import StateChange, StateStore
    from hassle.testing.templates import TemplateEngine

# Returns today's configured sun times ({"sunrise": dt, "sunset": dt}), or
# {} if none are configured (`sim.set_sun_times` was never called).
SunTimesProvider = Callable[[], dict[str, datetime]]


def no_sun_times() -> dict[str, datetime]:
    """The default :data:`SunTimesProvider`: no sun times configured."""
    return {}


@dataclass
class SuspendDelay:
    duration: timedelta


@dataclass
class SuspendWaitForTrigger:
    triggers: list[dict[str, Any]]
    timeout: timedelta | None
    continue_on_timeout: bool


@dataclass
class SuspendWaitTemplate:
    template_text: str
    timeout: timedelta | None
    continue_on_timeout: bool


Suspend = SuspendDelay | SuspendWaitForTrigger | SuspendWaitTemplate


def _empty_str_any_dict() -> dict[str, Any]:
    return {}


@dataclass
class ActionContext:
    """Mutable execution context threaded through one automation run."""

    states: StateStore
    templates: TemplateEngine
    calls: list[ServiceCall]
    variables: dict[str, Any] = field(default_factory=_empty_str_any_dict)
    trigger_ctx: dict[str, Any] = field(default_factory=_empty_str_any_dict)
    sun_times: SunTimesProvider = no_sun_times

    def template_context(self, *, repeat: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = dict(self.variables)
        ctx["trigger"] = _TriggerNamespace(self.trigger_ctx)
        if repeat is not None:
            ctx["repeat"] = _AttrDict(repeat)
        return ctx

    def render(self, value: Any, *, repeat: dict[str, Any] | None = None) -> Any:
        if isinstance(value, str):
            return self.templates.render(value, extra_context=self.template_context(repeat=repeat))
        if isinstance(value, dict):
            return {k: self.render(v, repeat=repeat) for k, v in value.items()}  # type: ignore[misc]
        if isinstance(value, list):
            return [self.render(v, repeat=repeat) for v in value]  # type: ignore[misc]
        return value


class _AttrDict(dict[str, Any]):
    """A dict that also supports attribute access (for `repeat.index` in templates)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class _TriggerNamespace(_AttrDict):
    pass


def evaluate_condition(condition: dict[str, Any], ctx: ActionContext) -> bool:
    kind = condition.get("condition")
    if kind == "state":
        state = ctx.states.get(condition["entity_id"])
        current = state.state if state is not None else None
        return current == condition.get("state")
    if kind == "numeric_state":
        state = ctx.states.get(condition["entity_id"])
        if state is None:
            return False
        try:
            value = float(state.state)
        except ValueError:
            return False
        above = condition.get("above")
        below = condition.get("below")
        above_ok = above is None or value > float(above)
        below_ok = below is None or value < float(below)
        return above_ok and below_ok
    if kind == "template":
        rendered = ctx.render(condition["value_template"])
        return str(rendered).strip().lower() in ("true", "1", "yes", "on")
    if kind == "and":
        return all(evaluate_condition(c, ctx) for c in condition.get("conditions", []))
    if kind == "or":
        return any(evaluate_condition(c, ctx) for c in condition.get("conditions", []))
    if kind == "not":
        return not any(evaluate_condition(c, ctx) for c in condition.get("conditions", []))
    if kind == "zone":
        state = ctx.states.get(condition["entity_id"])
        return state is not None and state.state == condition.get("zone")
    if kind == "sun":
        return _evaluate_sun_condition(condition, ctx)
    if kind == "trigger":
        return ctx.trigger_ctx.get("id") == condition.get("id")
    # Purpose-specific conditions (`met(...)`) and anything else unmodeled:
    # treated as satisfied under `sim.fire(...)` (which bypasses condition
    # gating entirely, see engine.py) -- reaching here through the normal
    # trigger-evaluation path means an unknown classic-condition kind, which
    # we conservatively treat as not blocking (v1 scope, documented).
    return True


def _evaluate_sun_condition(condition: dict[str, Any], ctx: ActionContext) -> bool:
    """``condition: sun`` (DESIGN §5.4/§10.1): now() is after/before a
    configured sunrise/sunset event, each with its own optional offset.

    Requires ``sim.set_sun_times(...)`` to have been called -- with no sun
    times configured there is nothing to compare against, so (like an
    unconfigured registry lookup elsewhere in v1) the condition is treated as
    satisfied rather than hard-failing simulation of unrelated logic.
    """
    sun_times = ctx.sun_times()
    if not sun_times:
        return True
    now = ctx.templates.now
    after = condition.get("after")
    if after is not None:
        base = sun_times.get(after)
        if base is not None:
            target = base + parse_offset(condition.get("after_offset"))
            if now < target:
                return False
    before = condition.get("before")
    if before is not None:
        base = sun_times.get(before)
        if base is not None:
            target = base + parse_offset(condition.get("before_offset"))
            if now >= target:
                return False
    return True


def _matches_wait_trigger(trigger: dict[str, Any], change: StateChange) -> bool:
    if is_state_trigger(trigger):
        return state_trigger_matches(trigger, change)
    if is_numeric_state_trigger(trigger):
        return numeric_state_crosses(trigger, change)
    if is_zone_trigger(trigger):
        return zone_trigger_matches(trigger, change)
    return False


def run_actions(
    actions: list[dict[str, Any]], ctx: ActionContext
) -> Generator[Suspend, StateChange | None, bool]:
    """Execute ``actions`` in order; ``yield`` suspends the run for the engine.

    Returns ``True`` if the sequence ran to completion, ``False`` if a `stop`
    action (or a timed-out `wait_for_trigger`/`wait_template` with
    ``continue_on_timeout=False``) halted it early.
    """
    for action in actions:
        should_continue = yield from _run_one(action, ctx)
        if not should_continue:
            return False
    return True


def _run_one(
    action: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, StateChange | None, bool]:
    if "action" in action:
        _record_service_call(action, ctx)
        return True
    if "delay" in action:
        duration = _duration(action["delay"])
        yield SuspendDelay(duration)
        return True
    if "variables" in action:
        for key, value in action["variables"].items():
            ctx.variables[key] = ctx.render(value)
        return True
    if "stop" in action:
        return False
    if "event" in action:
        # fire_event action: recorded like a service call under a synthetic
        # action name so assert_called can still observe it if desired.
        ctx.calls.append(
            ServiceCall("event." + str(action["event"]), data=dict(action.get("event_data", {})))
        )
        return True
    if "if" in action:
        conditions = action["if"]
        matched = all(evaluate_condition(c, ctx) for c in conditions)
        branch = action["then"] if matched else action.get("else", [])
        return (yield from run_actions(branch, ctx))
    if "choose" in action:
        for branch in action["choose"]:
            if all(evaluate_condition(c, ctx) for c in branch.get("conditions", [])):
                return (yield from run_actions(branch.get("sequence", []), ctx))
        default = action.get("default")
        if default is not None:
            return (yield from run_actions(default, ctx))
        return True
    if "repeat" in action:
        return (yield from _run_repeat(action["repeat"], ctx))
    if "parallel" in action:
        # The simulator executes parallel branches sequentially (deterministic,
        # single-threaded) but treats each branch as logically concurrent: no
        # branch's `stop`/early-exit affects another (unlike `then`/`sequence`),
        # matching HA's isolation semantics for `parallel`.
        for branch in action["parallel"]:
            yield from run_actions(branch.get("sequence", []), ctx)
        return True
    if "wait_for_trigger" in action:
        return (yield from _run_wait_for_trigger(action, ctx))
    if "wait_template" in action:
        return (yield from _run_wait_template(action, ctx))
    # Unknown/unmodeled action shape: no-op (forward-compatible; validation
    # tier catches genuinely malformed bundles, out of M4 scope).
    return True


def _record_service_call(action: dict[str, Any], ctx: ActionContext) -> None:
    data = dict(action.get("data", {}))
    target = action.get("target")
    if target:
        for key, value in target.items():
            data.setdefault(key, value)
    rendered_data = {k: ctx.render(v) for k, v in data.items()}
    ctx.calls.append(ServiceCall(action["action"], data=rendered_data, target=target))


def _duration(value: dict[str, Any] | str) -> timedelta:
    """Parse a compiled duration field (``delay``/``wait_for_trigger``'s
    ``timeout``/``wait_template``'s ``timeout``) into a :class:`timedelta`.

    Accepts both shapes the compiler can legitimately emit here: HA's usual
    dict form (``{"hours": .., "minutes": .., ...}``) and a plain
    ``"HH:MM:SS"`` string -- `wait_for`'s ``timeout=`` is passed through
    verbatim by the compiler (unlike `for_=`, it is never routed through
    ``normalize_duration``, see ``hassle.compiler.control_flow.wait_for``), so
    a bundle author writing ``wait_for(..., timeout="00:10:00")`` (exactly
    what ``fixtures/dsl/wait_for_trigger`` golden-compiles) previously crashed
    the simulator with an ``AttributeError`` (M9 regression, found via the
    cookbook recipe ``wait_then_lock_reminder``:
    `packages/hassle-core/tests/test_sim_wait_for_trigger.py::
    test_wait_for_trigger_accepts_plain_string_timeout`).
    """
    if isinstance(value, str):
        h, m, s = (int(p) for p in value.split(":"))
        return timedelta(hours=h, minutes=m, seconds=s)
    return timedelta(
        hours=int(value.get("hours", 0)),
        minutes=int(value.get("minutes", 0)),
        seconds=int(value.get("seconds", 0)),
        milliseconds=int(value.get("milliseconds", 0)),
    )


def _run_repeat(
    repeat: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, StateChange | None, bool]:
    sequence = repeat.get("sequence", [])
    _MAX_ITERATIONS = 10_000  # safety net against runaway while/until conditions
    if "count" in repeat:
        for _ in range(int(repeat["count"])):
            cont = yield from run_actions(sequence, ctx)
            if not cont:
                return False
        return True
    if "for_each" in repeat:
        for index, item in enumerate(repeat["for_each"], start=1):
            ctx.variables["repeat"] = _AttrDict({"index": index, "item": item})
            cont = yield from run_actions(sequence, ctx)
            if not cont:
                return False
        return True
    if "while" in repeat:
        conditions = repeat["while"]
        index = 1
        while index <= _MAX_ITERATIONS:
            if not _repeat_conditions_true(conditions, ctx, index):
                break
            cont = yield from run_actions(sequence, ctx)
            if not cont:
                return False
            index += 1
        return True
    if "until" in repeat:
        conditions = repeat["until"]
        index = 1
        while index <= _MAX_ITERATIONS:
            cont = yield from run_actions(sequence, ctx)
            if not cont:
                return False
            if _repeat_conditions_true(conditions, ctx, index):
                break
            index += 1
        return True
    return True


def _repeat_conditions_true(
    conditions: list[dict[str, Any]], ctx: ActionContext, index: int
) -> bool:
    repeat_ns = {"index": index}
    old_repeat = ctx.variables.get("repeat")
    ctx.variables["repeat"] = _AttrDict(repeat_ns)
    try:
        return all(_evaluate_condition_with_repeat(c, ctx, repeat_ns) for c in conditions)
    finally:
        if old_repeat is not None:
            ctx.variables["repeat"] = old_repeat
        else:
            ctx.variables.pop("repeat", None)


def _evaluate_condition_with_repeat(
    condition: dict[str, Any], ctx: ActionContext, repeat_ns: dict[str, Any]
) -> bool:
    if condition.get("condition") == "template":
        rendered = ctx.render(condition["value_template"], repeat=repeat_ns)
        return str(rendered).strip().lower() in ("true", "1", "yes", "on")
    return evaluate_condition(condition, ctx)


def _run_wait_for_trigger(
    action: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, StateChange | None, bool]:
    triggers = action["wait_for_trigger"]
    timeout = _duration(action["timeout"]) if "timeout" in action else None
    continue_on_timeout = action.get("continue_on_timeout", True)
    while True:
        change = yield SuspendWaitForTrigger(triggers, timeout, continue_on_timeout)
        if change is None:
            # Timed out.
            return continue_on_timeout
        if any(_matches_wait_trigger(t, change) for t in triggers):
            return True


def _run_wait_template(
    action: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, StateChange | None, bool]:
    template_text = action["wait_template"]
    timeout = _duration(action["timeout"]) if "timeout" in action else None
    continue_on_timeout = action.get("continue_on_timeout", True)
    if ctx.render(template_text).strip().lower() in ("true", "1", "yes", "on"):
        return True
    while True:
        change = yield SuspendWaitTemplate(template_text, timeout, continue_on_timeout)
        if change is None:
            return continue_on_timeout
        if ctx.render(template_text).strip().lower() in ("true", "1", "yes", "on"):
            return True
