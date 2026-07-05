"""The M1-core builder set: ``state`` (trigger+condition), ``service``, ``delay``.

This is the *proof of the pattern*, not the full builder catalog. The
triggers/conditions and actions/control-flow workstreams add the rest by
implementing the protocols in :mod:`hassle.compiler.protocols` — they do not
edit this file. Every builder here emits canonical (already plural / ``action:``)
HA dicts so compiler output is byte-stable (R8).
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.durations import normalize_duration
from hassle.compiler.errors import CompileTimeBranchError
from hassle.compiler.spans import capture_span


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

    The common trigger options (``id=`` / ``enabled=`` / ``variables=`` / ``for_=``,
    DESIGN §5.4) are accepted directly on ``.to()`` / ``.is_()`` / ``.with_options()``
    — there is no separate ``with_trigger_options`` wrapper.

    ``entity_id`` (and ``.to()``/``.is_()``'s ``value``) accept ``str | list[str]``
    (real-world smoke-test addition): the HA UI always stores these as *lists*,
    even for a single entity/value, and a singleton list must round-trip as a
    list — never normalized to a scalar (I3, docs/ha-api-notes.md).
    """

    def __init__(self, entity_id: str | list[str]) -> None:
        self._entity_id = entity_id
        self._from: Any = _UNSET
        self._to: Any = _UNSET
        self._state: Any = _UNSET
        self._options: dict[str, Any] = {}

    @property
    def entity_id(self) -> str | list[str]:
        """The entity id(s) this expression reads (public accessor, DESIGN §5.4)."""
        return self._entity_id

    def with_options(
        self,
        *,
        id: str | None = None,
        enabled: bool | None = None,
        variables: dict[str, Any] | None = None,
        for_: Any = None,
    ) -> StateExpr:
        """Attach common trigger options (DESIGN §5.4). Returns ``self`` for chaining."""
        if id is not None:
            self._options["id"] = id
        if enabled is not None:
            self._options["enabled"] = enabled
        if variables is not None:
            self._options["variables"] = variables
        if for_ is not None:
            self._options["for"] = normalize_duration(for_)
        return self

    def to(
        self,
        value: Any,
        *,
        id: str | None = None,
        enabled: bool | None = None,
        variables: dict[str, Any] | None = None,
        for_: Any = None,
    ) -> StateExpr:
        self._to = value
        return self.with_options(id=id, enabled=enabled, variables=variables, for_=for_)

    def is_(
        self,
        value: Any,
        *,
        id: str | None = None,
        enabled: bool | None = None,
        variables: dict[str, Any] | None = None,
        for_: Any = None,
    ) -> StateExpr:
        # `is_` means the trigger `from` and the condition `state` (see class doc).
        self._from = value
        self._state = value
        return self.with_options(id=id, enabled=enabled, variables=variables, for_=for_)

    def to_trigger(self) -> dict[str, Any]:
        body: dict[str, Any] = {"trigger": "state", "entity_id": self._entity_id}
        if self._from is not _UNSET:
            body["from"] = self._from
        if self._to is not _UNSET:
            body["to"] = self._to
        body.update(self._options)
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


def state(entity_id: str | list[str]) -> StateExpr:
    """Build a state trigger/condition for ``entity_id`` (DESIGN §5.3).

    ``entity_id`` accepts a single entity or a list (real-world smoke-test
    addition: the HA UI always stores this as a list, even for one entity).
    """
    return StateExpr(entity_id)


class ServiceAction:
    """A service-call action. Bare kwargs land in ``data``; ``target=`` is explicit.

    Emits canonical ``{"action": "<domain.service>", ...}`` (never ``service:``).
    ``response_variable`` and ``continue_on_error`` are HA *action* fields (they
    live at the top level, not inside ``data``); passing them keeps this the one
    service-call builder (no separate ``service_ext``).

    ``metadata=`` (real-world smoke-test addition, docs/ha-api-notes.md §19): the
    HA UI stamps ``"metadata": {}`` on every action it saves. It is emitted
    whenever passed, **including when empty** — a real UI-authored config always
    carries it, so eliding an empty ``metadata`` would hash-drift every such
    action on every decompile+recompile cycle (I3). ``None`` (the default) omits
    the field entirely, for DSL-authored actions that never had one.

    ``data_template=`` (residue-coverage round 2, docs/ha-api-notes.md §20): the
    legacy templated-data key. HA still stores it verbatim on a real UI-authored
    action; it is a *sibling* of ``data``, never folded into it — a real config
    may carry ``data_template`` alone, ``data`` alone, or (rarely) both, and each
    round-trips exactly as stored (I3).

    ``alias=``/``enabled=`` (residue-coverage round 2): the UI names and toggles
    individual steps. Both are additive, top-level action fields, same treatment
    as ``metadata=``/``data_template=`` — omitted by default, emitted verbatim
    when passed (including ``enabled=False``).
    """

    def __init__(
        self,
        action: str,
        *,
        target: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        data_template: dict[str, Any] | None = None,
        response_variable: str | None = None,
        continue_on_error: bool | None = None,
        metadata: dict[str, Any] | None = None,
        alias: str | None = None,
        enabled: bool | None = None,
        **fields: Any,
    ) -> None:
        self._action = action
        self._target = target
        self._data_template = data_template
        self._response_variable = response_variable
        self._continue_on_error = continue_on_error
        self._metadata = metadata
        self._alias = alias
        self._enabled = enabled
        merged: dict[str, Any] = {}
        if data:
            merged.update(data)
        merged.update(fields)
        self._data = merged
        # Presence, not truthiness (same rule as metadata): the UI stores
        # `"data": {}` on field-less calls; eliding it on recompile would
        # hash-drift the action and raw the containing block (I3).
        self._data_present = data is not None or bool(fields)

    def to_action(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self._alias is not None:
            body["alias"] = self._alias
        body["action"] = self._action
        if self._metadata is not None:
            body["metadata"] = self._metadata
        if self._target is not None:
            body["target"] = self._target
        if self._data_present:
            body["data"] = self._data
        if self._data_template is not None:
            body["data_template"] = self._data_template
        if self._response_variable is not None:
            body["response_variable"] = self._response_variable
        if self._continue_on_error is not None:
            body["continue_on_error"] = self._continue_on_error
        if self._enabled is not None:
            body["enabled"] = self._enabled
        return body


class DelayAction:
    """A ``delay`` action. Emits ``{"delay": {<unit>: <value>, ...}}`` (dict form).

    The dict form (rather than an ``HH:MM:SS`` string) is deterministic and is what
    HA accepts natively; it round-trips without ambiguity.

    ``alias=``/``enabled=`` (residue-coverage round 2, docs/ha-api-notes.md §20):
    the UI names and toggles individual steps, including a bare ``delay``. Same
    additive treatment as :class:`ServiceAction`'s — keyword-only so they never
    collide with a duration unit passed via ``**duration``.
    """

    _UNITS = ("hours", "minutes", "seconds", "milliseconds")

    def __init__(
        self, *, alias: str | None = None, enabled: bool | None = None, **duration: Any
    ) -> None:
        unknown = [k for k in duration if k not in self._UNITS]
        if unknown:
            raise TypeError(
                f"delay() got unexpected unit(s) {unknown}; use {', '.join(self._UNITS)}"
            )
        # Preserve a stable key order (largest unit first) for byte-determinism.
        self._duration = {u: duration[u] for u in self._UNITS if u in duration}
        self._alias = alias
        self._enabled = enabled

    def to_action(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self._alias is not None:
            body["alias"] = self._alias
        body["delay"] = dict(self._duration)
        if self._enabled is not None:
            body["enabled"] = self._enabled
        return body
