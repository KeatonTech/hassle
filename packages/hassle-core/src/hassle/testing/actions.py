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
from hassle.testing.errors import ScriptRecursionError, UnsupportedTemplateError
from hassle.testing.state import StateChange
from hassle.testing.triggers import (
    is_event_trigger,
    is_numeric_state_trigger,
    is_state_trigger,
    is_zone_trigger,
    numeric_state_crosses,
    parse_offset,
    state_trigger_matches,
    zone_trigger_matches,
)

if TYPE_CHECKING:
    from hassle.testing.state import StateStore
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


@dataclass(frozen=True)
class EventOccurrence:
    """One fired event (``Simulator.fire_event``), the event-carrying
    counterpart of :class:`~hassle.testing.state.StateChange` -- the other
    shape a pending ``SuspendWaitForTrigger`` can be resumed with (task #32,
    docs/ha-api-notes.md §36.2 gap 1: a `wait_for_trigger([event(...)])` step
    previously could only ever be resumed by a state change or a timeout).
    """

    event_type: str
    data: dict[str, Any]


# What a suspended run can be resumed with: a state change, a fired event, or
# `None` (timeout). `wait_template` only ever cares that *something* changed
# (it re-renders its own template regardless), so it accepts either shape;
# `wait_for_trigger` dispatches by shape in `_matches_wait_trigger`.
WaitResumeValue = StateChange | EventOccurrence | None


def _empty_str_any_dict() -> dict[str, Any]:
    return {}


def _empty_scripts() -> dict[str, dict[str, Any]]:
    return {}


#: Callee-nesting cap for script-call expansion (task #35) -- far above any
#: real bundle's call chain, low enough that mutual script->script recursion
#: fails fast with a clear error instead of exhausting the stack.
_MAX_SCRIPT_CALL_DEPTH = 10

#: `script.<entity_management>` service names that are NOT bundle-script
#: invocations: `script.turn_on` is fire-and-forget in HA (never blocks the
#: caller), the rest manage script entities rather than run one. All stay
#: opaque recorded calls (documented v1.1 scope).
_OPAQUE_SCRIPT_SERVICES = frozenset({"turn_on", "turn_off", "toggle", "reload"})


@dataclass
class ActionContext:
    """Mutable execution context threaded through one automation run."""

    states: StateStore
    templates: TemplateEngine
    calls: list[ServiceCall]
    variables: dict[str, Any] = field(default_factory=_empty_str_any_dict)
    trigger_ctx: dict[str, Any] = field(default_factory=_empty_str_any_dict)
    sun_times: SunTimesProvider = no_sun_times
    #: Bundle scripts by slug (`script:<slug>` object key minus the prefix),
    #: each the script's full HA config -- a direct `script.<slug>` service
    #: call expands into its `sequence`, blocking, exactly like real HA
    #: (task #35). Empty map = no expansion (the pre-#35 opaque behavior).
    scripts: dict[str, dict[str, Any]] = field(default_factory=_empty_scripts)
    #: Current script-call nesting depth (recursion guard).
    script_call_depth: int = 0
    #: Set when this sequence was halted by a `stop` with `error: true` --
    #: the one halt kind that must also abort a CALLING sequence (HA: a
    #: script error fails the caller's service call), unlike a plain `stop`
    #: (normal completion from the caller's point of view).
    halted_by_error: bool = False

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
        expected = condition.get("state")
        if isinstance(expected, list):
            # HA: `state: [a, b]` matches ANY of the listed states -- the
            # shape `.state.in_([...])`/`state(x).is_([...])` compiles to
            # (task #35; previously compared the current state to the list
            # itself, silently false forever).
            return current in expected
        return current == expected
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
        return _evaluate_template_condition(condition["value_template"], ctx)
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


def _evaluate_template_condition(value_template: str, ctx: ActionContext) -> bool:
    """A ``condition: template``'s ``value_template`` -- rendered like any
    other template, EXCEPT an undefined-name/attribute render failure here is
    swallowed to ``False`` rather than propagated as
    :class:`UnsupportedTemplateError` (task #32).

    Mirrors real HA's script engine: `async_condition_from_config`'s template
    condition logs a render error and treats the condition as not satisfied,
    it does not abort the automation run. This specifically matters for a
    `choose()` branch reading `wait.trigger.*` after a *timed-out*
    `wait_for_trigger` (`wait.trigger` is `None` there, per DESIGN's `wait`
    variable semantics) -- subscripting/attribute-accessing through that
    `None` is a legitimate, expected shape for an unmatched branch, not a
    genuinely-unsupported template construct, so it must not surface as a
    hard simulator error the way a real unknown Jinja global/filter should.
    Every OTHER template-rendering call site in this module (service-call
    `data=` values, `wait_template`'s own condition, `variables:` values)
    deliberately does NOT catch this -- only a *condition*'s truth value has
    this "render failure means not satisfied" semantics in real HA.
    """
    try:
        rendered = ctx.render(value_template)
    except UnsupportedTemplateError as exc:
        if _is_undefined_render_error(exc):
            return False
        raise
    return str(rendered).strip().lower() in ("true", "1", "yes", "on")


def _is_undefined_render_error(exc: UnsupportedTemplateError) -> bool:
    """Narrow ``UnsupportedTemplateError`` to the "undefined name/attribute"
    subset (jinja2's ``UndefinedError``, per ``TemplateEngine.render``'s own
    exception mapping) as opposed to a genuinely unsupported construct
    (invalid syntax, an unregistered filter/test) -- only the former is safe
    to treat as "condition not satisfied" rather than a real simulator gap.
    """
    return "is undefined" in exc.args[0] or "has no attribute" in exc.args[0]


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


def _matches_wait_trigger(
    trigger: dict[str, Any], occurrence: StateChange | EventOccurrence
) -> bool:
    if isinstance(occurrence, EventOccurrence):
        return is_event_trigger(trigger) and _event_trigger_matches(trigger, occurrence)
    if is_state_trigger(trigger):
        return state_trigger_matches(trigger, occurrence)
    if is_numeric_state_trigger(trigger):
        return numeric_state_crosses(trigger, occurrence)
    if is_zone_trigger(trigger):
        return zone_trigger_matches(trigger, occurrence)
    return False


def _event_trigger_matches(trigger: dict[str, Any], occurrence: EventOccurrence) -> bool:
    """Mirrors ``AutomationEngine.on_event``'s top-level event-trigger match
    (``event_type`` equality) plus the trigger's own optional ``event_data``
    filter -- a subset match against the fired event's data, the same
    semantics a real HA ``event`` trigger's ``event_data:`` gives (only the
    keys named in the filter must match; extra data keys on the occurrence
    are ignored).
    """
    if trigger.get("event_type") != occurrence.event_type:
        return False
    event_data_filter = trigger.get("event_data")
    if not event_data_filter:
        return True
    return all(occurrence.data.get(key) == value for key, value in event_data_filter.items())


def run_actions(
    actions: list[dict[str, Any]], ctx: ActionContext
) -> Generator[Suspend, WaitResumeValue, bool]:
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
) -> Generator[Suspend, WaitResumeValue, bool]:
    if "action" in action:
        _record_service_call(action, ctx)
        return (yield from _maybe_expand_script_call(action, ctx))
    if "delay" in action:
        duration = _duration(action["delay"])
        yield SuspendDelay(duration)
        return True
    if "variables" in action:
        for key, value in action["variables"].items():
            ctx.variables[key] = ctx.render(value)
        return True
    if "stop" in action:
        if action.get("error"):
            ctx.halted_by_error = True
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
        # branch's plain `stop`/early-exit affects another (unlike
        # `then`/`sequence`), matching HA's isolation semantics for
        # `parallel`. An ERROR stop is different: real HA fails the whole
        # parallel step when any branch errors, so it must halt this sequence
        # too (PR #27 review) -- and the flag is scoped per branch so a
        # branch's error is never misattributed to a later unrelated halt.
        prior_error = ctx.halted_by_error
        any_branch_error = False
        for branch in action["parallel"]:
            ctx.halted_by_error = False
            yield from run_actions(branch.get("sequence", []), ctx)
            any_branch_error = any_branch_error or ctx.halted_by_error
        ctx.halted_by_error = prior_error or any_branch_error
        return not any_branch_error
    if "wait_for_trigger" in action:
        return (yield from _run_wait_for_trigger(action, ctx))
    if "wait_template" in action:
        return (yield from _run_wait_template(action, ctx))
    # Unknown/unmodeled action shape: no-op (forward-compatible; validation
    # tier catches genuinely malformed bundles, out of M4 scope).
    return True


def _maybe_expand_script_call(
    action: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, WaitResumeValue, bool]:
    """Expand a direct ``script.<slug>`` call into the callee's sequence,
    blocking, matching real HA (task #35): the caller resumes only when the
    callee finishes, the call's rendered ``data`` becomes the callee's
    variables (HA: script fields are run variables), a plain ``stop`` in the
    callee is a normal completion for the caller, and a ``stop`` with
    ``error: true`` fails the caller's sequence too. `script.turn_on` (fire-
    and-forget in HA) and the other entity-management services stay opaque,
    as does any script not in this bundle.
    """
    name = str(action["action"])
    if not name.startswith("script."):
        return True
    slug = name.removeprefix("script.")
    if slug in _OPAQUE_SCRIPT_SERVICES:
        return True
    script_config = ctx.scripts.get(slug)
    if script_config is None:
        return True
    if ctx.script_call_depth >= _MAX_SCRIPT_CALL_DEPTH:
        raise ScriptRecursionError(slug, _MAX_SCRIPT_CALL_DEPTH)
    sequence: list[dict[str, Any]] = script_config.get("sequence", [])
    # HA seeds omitted fields' `default:`s as run variables; an explicitly
    # passed value wins.
    fields: dict[str, Any] = script_config.get("fields") or {}
    data: dict[str, Any] = {
        name: spec["default"]
        for name, spec in fields.items()
        if isinstance(spec, dict) and "default" in spec
    }
    call_data: dict[str, Any] = action.get("data", {})
    data.update({key: ctx.render(value) for key, value in call_data.items()})
    callee_ctx = ActionContext(
        states=ctx.states,
        templates=ctx.templates,
        calls=ctx.calls,
        variables=data,
        # Scripts have no `trigger` namespace of their own in HA.
        trigger_ctx={},
        sun_times=ctx.sun_times,
        scripts=ctx.scripts,
        script_call_depth=ctx.script_call_depth + 1,
    )
    completed = yield from run_actions(sequence, callee_ctx)
    if not completed and callee_ctx.halted_by_error:
        ctx.halted_by_error = True
        return False
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
) -> Generator[Suspend, WaitResumeValue, bool]:
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


def _wait_trigger_namespace(occurrence: StateChange | EventOccurrence) -> dict[str, Any]:
    """The satisfying trigger's data, shaped like HA's real post-`wait_for_trigger`
    `wait.trigger` variable for the occurrence kind that satisfied the wait
    (task #32, docs/ha-api-notes.md §36.2 gap 2). Only the `event` shape is
    modeled today (`{"event": {"event_type": ..., "data": {...}}}`, mirroring
    `AutomationEngine.on_event`'s own top-level `trigger.event.data` shape) --
    a state-satisfied wait gets an empty namespace rather than a fabricated
    `state`-trigger shape this module doesn't otherwise model for `trigger.*`.
    """
    if isinstance(occurrence, EventOccurrence):
        return {"event": {"event_type": occurrence.event_type, "data": dict(occurrence.data)}}
    return {}


def _set_wait_satisfied(ctx: ActionContext, occurrence: StateChange | EventOccurrence) -> None:
    """Populate ``ctx.variables["wait"]`` after a `wait_for_trigger` step is
    SATISFIED, so later actions' templates can read ``wait.completed`` /
    ``wait.trigger.*`` (task #32, docs/ha-api-notes.md §36.2 gap 2 --
    previously never populated at all, so any such template hit an
    `UnsupportedTemplateError` for the undefined `wait` name). `wait.trigger`
    carries the satisfying occurrence's data and `wait.completed` is true.
    """
    trigger_ns = _TriggerNamespace(_wait_trigger_namespace(occurrence))
    ctx.variables["wait"] = _AttrDict({"completed": True, "trigger": trigger_ns})


def _set_wait_timed_out(ctx: ActionContext) -> None:
    """The timeout counterpart of :func:`_set_wait_satisfied`: `wait.trigger`
    is `None` (renders as Jinja's `none`) and `wait.completed` is false --
    matching real HA's `wait` variable shape for the timeout path.
    """
    ctx.variables["wait"] = _AttrDict({"completed": False, "trigger": None})


def _run_wait_for_trigger(
    action: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, WaitResumeValue, bool]:
    # HA renders a wait_for_trigger's config (limited templates) when the
    # step executes -- a templated `event_data` filter like
    # `{{ tag ~ '_ACTION' }}` must match fired events by its RENDERED value
    # (task #35; previously compared literally and never matched).
    triggers = ctx.render(action["wait_for_trigger"])
    timeout = _duration(action["timeout"]) if "timeout" in action else None
    continue_on_timeout = action.get("continue_on_timeout", True)
    while True:
        occurrence = yield SuspendWaitForTrigger(triggers, timeout, continue_on_timeout)
        if occurrence is None:
            # Timed out.
            _set_wait_timed_out(ctx)
            return continue_on_timeout
        if any(_matches_wait_trigger(t, occurrence) for t in triggers):
            _set_wait_satisfied(ctx, occurrence)
            return True


def _run_wait_template(
    action: dict[str, Any], ctx: ActionContext
) -> Generator[Suspend, WaitResumeValue, bool]:
    template_text = action["wait_template"]
    timeout = _duration(action["timeout"]) if "timeout" in action else None
    continue_on_timeout = action.get("continue_on_timeout", True)
    if ctx.render(template_text).strip().lower() in ("true", "1", "yes", "on"):
        return True
    while True:
        occurrence = yield SuspendWaitTemplate(template_text, timeout, continue_on_timeout)
        if occurrence is None:
            return continue_on_timeout
        if ctx.render(template_text).strip().lower() in ("true", "1", "yes", "on"):
            return True
