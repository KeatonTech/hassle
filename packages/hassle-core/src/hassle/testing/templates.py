"""The simulator's Jinja template engine (DESIGN §10.1).

Real jinja2, extended with the subset of HA's template extensions the
simulator supports: ``states()``/``is_state()``/``state_attr()``/``now()``/
``today_at()``/``as_timestamp()``/``iif()``, plus HA's math globals/filters
(``sin``/``cos``/``tan``/``asin``/``acos``/``atan``/``atan2``/``sqrt``/``log``,
``pi``/``e``/``tau``, ``min``/``max``/``abs``/``round`` -- stock jinja2 lacks
these) and ``variables:``/``trigger.*``/``repeat.*`` scope resolution.

Anything outside this subset -- an unregistered HA integration helper,
malformed Jinja syntax, an undefined name -- raises
:class:`~hassle.testing.errors.UnsupportedTemplateError` naming the construct,
never silently evaluating to the wrong thing (DESIGN §10.1).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import jinja2

from hassle.testing.errors import UnsupportedTemplateError

if TYPE_CHECKING:
    from hassle.testing.state import StateStore


def _iif(value: Any, if_true: Any = True, if_false: Any = False, if_none: Any = None) -> Any:
    if value is None and if_none is not None:
        return if_none
    return if_true if value else if_false


def _build_globals_and_filters(
    states: StateStore, clock_now: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    def states_fn(entity_id: str) -> str:
        state = states.get(entity_id)
        return state.state if state is not None else "unknown"

    def is_state_fn(entity_id: str, value: str) -> bool:
        state = states.get(entity_id)
        return state is not None and state.state == value

    def state_attr_fn(entity_id: str, attr: str) -> Any:
        state = states.get(entity_id)
        if state is None:
            return None
        return state.attributes.get(attr)

    def now_fn() -> datetime:
        return clock_now()

    def today_at_fn(time_str: str) -> datetime:
        now = clock_now()
        hour, minute, *rest = (int(p) for p in time_str.split(":"))
        second = rest[0] if rest else 0
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    def as_timestamp_fn(value: datetime) -> float:
        return value.timestamp()

    globals_: dict[str, Any] = {
        "states": states_fn,
        "is_state": is_state_fn,
        "state_attr": state_attr_fn,
        "now": now_fn,
        "today_at": today_at_fn,
        "as_timestamp": as_timestamp_fn,
        "iif": _iif,
        # HA math set (DESIGN §10.1 / MILESTONES M4 deliverables line): stock
        # jinja2 has none of these as bare globals.
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "atan2": math.atan2,
        "sqrt": math.sqrt,
        "log": math.log,
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
        # min/max/abs/round are already Jinja2 builtins as globals, but HA
        # exposes them explicitly too; re-registering is harmless and keeps
        # this table the single source of truth for "the HA math set".
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
    }

    def float_filter(v: Any, default: float = 0.0) -> float:
        return _safe_cast(float, v, default)

    def int_filter(v: Any, default: int = 0) -> int:
        return _safe_cast(int, v, default)

    def round_filter(v: Any, ndigits: int = 0) -> float:
        return round(float(v), ndigits)

    filters: dict[str, Any] = {
        "float": float_filter,
        "int": int_filter,
        "round": round_filter,
        "is_state": is_state_fn,
        "as_timestamp": as_timestamp_fn,
    }
    return globals_, filters


def _safe_cast(caster: Any, value: Any, default: Any) -> Any:
    try:
        return caster(value)
    except (TypeError, ValueError):
        return default


class TemplateEngine:
    """Renders HA-subset Jinja templates against live simulator state."""

    def __init__(self, states: StateStore, clock_now: Any) -> None:
        self._states = states
        self._clock_now = clock_now
        self._env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
        globals_, filters = _build_globals_and_filters(states, clock_now)
        # timedelta arithmetic (DESIGN §10.1): now() - now() etc. must work
        # without extra plumbing -- jinja2's native `-`/`+` on datetimes
        # already produce/accept timedelta objects, so no filter is needed;
        # exposed here only for discoverability/documentation purposes.
        globals_["timedelta"] = timedelta
        self._env.globals.update(globals_)
        self._env.filters.update(filters)

    def render(self, template_text: str, *, extra_context: Mapping[str, Any] | None = None) -> str:
        """Render ``template_text`` (a full ``{{ ... }}`` or plain string).

        Non-template plain strings pass through unchanged (HA behavior: a
        value without ``{{``/``{%`` is not templated at all).
        """
        if "{{" not in template_text and "{%" not in template_text:
            return template_text
        context = dict(extra_context or {})
        try:
            compiled = self._env.from_string(template_text)
        except jinja2.TemplateSyntaxError as exc:
            raise UnsupportedTemplateError(
                "invalid template syntax", template_text, reason=str(exc)
            ) from exc
        try:
            return compiled.render(**context)
        except jinja2.UndefinedError as exc:
            construct = _extract_undefined_name(str(exc))
            raise UnsupportedTemplateError(construct, template_text, reason=str(exc)) from exc
        except jinja2.TemplateRuntimeError as exc:
            raise UnsupportedTemplateError(
                "unsupported template construct", template_text, reason=str(exc)
            ) from exc

    def eval_bool(
        self, template_text: str, *, extra_context: Mapping[str, Any] | None = None
    ) -> bool:
        """Render a template expected to produce a boolean-ish string ('True'/'False')."""
        rendered = self.render(template_text, extra_context=extra_context)
        return rendered.strip().lower() in ("true", "1", "yes", "on")


def _extract_undefined_name(message: str) -> str:
    # jinja2's UndefinedError text is like "'some_name' is undefined" or
    # "'dict object' has no attribute 'some_name'" -- best-effort extraction
    # of the offending identifier so the error names the construct (R6).
    if "'" in message:
        parts = message.split("'")
        if len(parts) >= 2:
            return parts[-2] if message.strip().endswith("undefined") else parts[1]
    return message
