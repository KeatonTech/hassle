"""The M1-core builder set: ``state`` (trigger+condition), ``service``, ``delay``.

This is the *proof of the pattern*, not the full builder catalog. The
triggers/conditions and actions/control-flow workstreams add the rest by
implementing the protocols in :mod:`hassle_core.compiler.protocols` — they do not
edit this file. Every builder here emits canonical (already plural / ``action:``)
HA dicts so compiler output is byte-stable (R8).
"""

from __future__ import annotations

from typing import Any

from hassle_core.compiler.errors import CompileTimeBranchError
from hassle_core.compiler.spans import capture_span


class _NoBool:
    """Mixin: a runtime expression must never be used in a Python ``if``/``bool()``.

    DESIGN §5.5 trap-catching — ``__bool__`` raises :class:`CompileTimeBranchError`
    with the ``with if_then(...)`` rewrite hint, naming the offending source line.
    """

    def _branch_repr(self) -> str:  # pragma: no cover - overridden
        return repr(self)

    def __bool__(self) -> bool:
        raise CompileTimeBranchError(self._branch_repr(), capture_span(depth=0))


class StateExpr(_NoBool):
    """``state(entity)`` — a state trigger *or* a state condition.

    Dual-purpose (DESIGN §5.3/§5.4): registered via ``when(...)`` it serializes as a
    ``state`` trigger; via ``only_if(...)`` as a ``state`` condition. ``.to(v)`` sets
    the trigger ``to``; ``.is_(v)`` sets the trigger ``from`` and the condition
    ``state``. Chaining returns ``self`` so ``.is_("on").to("off")`` reads naturally.
    """

    def __init__(self, entity_id: str) -> None:
        self._entity_id = entity_id
        self._from: Any = _UNSET
        self._to: Any = _UNSET
        self._state: Any = _UNSET

    def to(self, value: Any) -> StateExpr:
        self._to = value
        return self

    def is_(self, value: Any) -> StateExpr:
        # `is_` means the trigger `from` and the condition `state` (see class doc).
        self._from = value
        self._state = value
        return self

    def to_trigger(self) -> dict[str, Any]:
        body: dict[str, Any] = {"trigger": "state", "entity_id": self._entity_id}
        if self._from is not _UNSET:
            body["from"] = self._from
        if self._to is not _UNSET:
            body["to"] = self._to
        return body

    def to_condition(self) -> dict[str, Any]:
        body: dict[str, Any] = {"condition": "state", "entity_id": self._entity_id}
        if self._state is not _UNSET:
            body["state"] = self._state
        return body

    def _branch_repr(self) -> str:
        return f"state({self._entity_id!r})"


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<unset>"


_UNSET = _Unset()


def state(entity_id: str) -> StateExpr:
    """Build a state trigger/condition for ``entity_id`` (DESIGN §5.3)."""
    return StateExpr(entity_id)


class ServiceAction:
    """A service-call action. Bare kwargs land in ``data``; ``target=`` is explicit.

    Emits canonical ``{"action": "<domain.service>", ...}`` (never ``service:``).
    """

    def __init__(
        self,
        action: str,
        *,
        target: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        **fields: Any,
    ) -> None:
        self._action = action
        self._target = target
        merged: dict[str, Any] = {}
        if data:
            merged.update(data)
        merged.update(fields)
        self._data = merged

    def to_action(self) -> dict[str, Any]:
        body: dict[str, Any] = {"action": self._action}
        if self._target is not None:
            body["target"] = self._target
        if self._data:
            body["data"] = self._data
        return body


class DelayAction:
    """A ``delay`` action. Emits ``{"delay": {<unit>: <value>, ...}}`` (dict form).

    The dict form (rather than an ``HH:MM:SS`` string) is deterministic and is what
    HA accepts natively; it round-trips without ambiguity.
    """

    _UNITS = ("hours", "minutes", "seconds", "milliseconds")

    def __init__(self, **duration: Any) -> None:
        unknown = [k for k in duration if k not in self._UNITS]
        if unknown:
            raise TypeError(
                f"delay() got unexpected unit(s) {unknown}; use {', '.join(self._UNITS)}"
            )
        # Preserve a stable key order (largest unit first) for byte-determinism.
        self._duration = {u: duration[u] for u in self._UNITS if u in duration}

    def to_action(self) -> dict[str, Any]:
        return {"delay": dict(self._duration)}
