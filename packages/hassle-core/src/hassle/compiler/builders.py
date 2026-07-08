"""The M1-core builder set: ``state`` (trigger+condition), ``service``, ``delay``.

This is the *proof of the pattern*, not the full builder catalog. The
triggers/conditions and actions/control-flow workstreams add the rest by
implementing the protocols in :mod:`hassle.compiler.protocols` — they do not
edit this file. Every builder here emits canonical (already plural / ``action:``)
HA dicts so compiler output is byte-stable (R8).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from hassle.compiler.durations import normalize_duration
from hassle.compiler.errors import CompileTimeBranchError
from hassle.compiler.purpose import normalize_target
from hassle.compiler.spans import capture_span

if TYPE_CHECKING:
    # Type-only (no runtime import -- avoids a builders<->triggers module-load
    # cycle even though none currently exists; `_StateAccessor`'s `>`/`<`
    # methods import `hassle.compiler.triggers.numeric_state` lazily at call
    # time instead, same convention as every other cross-module reference in
    # this file (`hassle.compiler.errors.InclusiveNumericBoundError`, etc.)).
    from hassle.compiler.triggers import NumericStateExpr


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

    ``entity_id`` (and ``.to()``/``.is_()``'s ``value``) accept
    ``str | Sequence[str]`` (real-world smoke-test addition; widened from
    ``str | list[str]`` to ``str | Sequence[str]`` in the task #28
    annotation-truth pass -- ``list[X]`` is invariant, so a decompiled
    bundle's ``state(e.binary_sensor.hall_motion)`` -- an ``EntityRef``/entity
    stub CLASS, a ``str`` subclass but not literally ``str`` -- and
    ``state([e.binary_sensor.a, e.binary_sensor.b])`` -- a ``list`` of THOSE,
    never assignable to an invariant ``list[str]`` parameter even once each
    element is itself ``str``-compatible -- were both real pyright errors
    against genuinely correct code. ``Sequence`` is covariant, so both forms
    typecheck; a bare ``str`` is itself a ``Sequence[str]``, so the
    single-entity form is unaffected): the HA UI always stores these as
    *lists*, even for a single entity/value, and a singleton list must
    round-trip as a list — never normalized to a scalar (I3,
    docs/ha-api-notes.md).
    """

    def __init__(self, entity_id: str | Sequence[str]) -> None:
        self._entity_id = entity_id
        self._from: Any = _UNSET
        self._to: Any = _UNSET
        self._state: Any = _UNSET
        self._options: dict[str, Any] = {}

    @property
    def entity_id(self) -> str | Sequence[str]:
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

    def is_not(self, value: Any) -> _NotStateExpr:
        """``state(x).is_not(v)`` -- condition-only negation (M20, entity-first
        conditions milestone). Mirrors ``.is_()`` exactly (same argument shape,
        including a list ``value``) but wraps the resulting ``state`` condition
        in HA's ``not`` combinator, compiling byte-identical to
        ``not_(state(x).is_(v))`` (``hassle.compiler.conditions.not_``).

        Condition-only (like ``not_`` itself): there is no ``not``-shaped HA
        *trigger*, so this returns a condition-only object rather than
        widening ``StateExpr``'s own dual trigger/condition ``to_trigger``.
        """
        return _NotStateExpr(self.is_(value))

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


class _NotStateExpr(_NoBool):
    """The ``condition: not`` wrapper :meth:`StateExpr.is_not` returns.

    Condition-only (mirrors :class:`~hassle.compiler.conditions._CombinatorExpr`'s
    own ``not_`` shape exactly): ``to_condition()`` is the only serialization
    method, since there is no HA ``not``-shaped trigger to build.
    """

    def __init__(self, inner: StateExpr) -> None:
        self._inner = inner

    def to_condition(self) -> dict[str, Any]:
        return {"condition": "not", "conditions": [self._inner.to_condition()]}

    def _branch_repr(self) -> str:
        return f"{self._inner._branch_repr()}.is_not(...)"  # pyright: ignore[reportPrivateUsage]


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<unset>"


_UNSET = _Unset()


def state(entity_id: str | Sequence[str]) -> StateExpr:
    """Build a state trigger/condition for ``entity_id`` (DESIGN §5.3).

    ``entity_id`` accepts a single entity or a sequence of them (real-world
    smoke-test addition: the HA UI always stores this as a list, even for one
    entity; widened to ``Sequence[str]`` in the task #28 annotation-truth
    pass -- see :class:`StateExpr`'s docstring).
    """
    return StateExpr(entity_id)


class _StateAccessor(_NoBool):  # pyright: ignore[reportUnusedClass]
    # Constructed only from `hassle.compiler.helpers.EntityRef.state` (a
    # cross-module, lazily-imported reference -- same avoidance convention as
    # every other helpers<->builders seam in this file) and referenced
    # directly by this milestone's tests -- never instantiated from within
    # `builders.py` itself, which is the one thing pyright's strict
    # `reportUnusedClass` actually checks for an underscore-prefixed class.
    """``entity.state`` (MILESTONES M20, entity-first conditions) — a
    comparison accessor bound to one entity id, returned by
    :attr:`~hassle.compiler.helpers.EntityRef.state` (a defined property,
    so it wins over M18's service-method ``__getattr__`` — no HA domain has
    a service literally named ``state``).

    Every comparison compiles to the exact same IR the corresponding classic
    builder call would (golden-equivalence, this milestone's test 1):

    - ``==``/``!=``   -> ``state(...).is_(v)`` / ``state(...).is_not(v)``
    - ``>``/``<``     -> ``numeric_state(..., above=v)`` / ``(..., below=v)``
    - ``>=``/``<=``   -> :class:`~hassle.compiler.errors.InclusiveNumericBoundError`
      (HA's ``numeric_state`` has no inclusive bound — see that error's
      docstring for the honest-mapping rationale)
    - ``.in_([...])`` -> ``state(...).is_(["a", "b"])`` (HA's own ``state``
      condition already accepts a list value as OR-membership, verified
      against ``fixtures/configs/automation_condition_state_list_valued_fields.json``)

    ``__eq__``/``__ne__`` are REAL overloads here (unlike ``StateExpr``/
    ``TemplateExpr``, which are ``str`` subclasses that must keep ordinary
    string equality — see ``hassle.compiler.templates``'s "Note on ==/!="):
    this accessor is a bespoke, non-``str`` object that exists ONLY to be
    compared, so overloading ``==``/``!=`` to build a condition cannot
    collide with any pre-existing string-equality use.

    The **``in``-operator trap** (Python semantics, non-negotiable): ``x.state
    in [...]`` dispatches to ``list.__contains__``, which calls ``bool()`` on
    each ``x.state == element`` comparison RESULT to decide membership — no
    ``__eq__`` override can intercept this, since ``__contains__`` always
    coerces via ``__bool__``. The comparison-result object
    (:class:`_StateComparisonExpr`, what ``==``/``!=`` return) refuses
    ``__bool__`` with :class:`~hassle.compiler.errors.InOperatorTrapError`,
    naming ``.in_([...])`` as the fix, so the natural-but-impossible ``in``
    spelling fails loudly rather than silently testing membership against
    whatever ``bool()`` returned. The bare accessor (before any comparison)
    still traps as an ordinary :class:`CompileTimeBranchError` (inherited
    from ``_NoBool``), so ``if entity.state:`` fails loudly too.
    """

    def __init__(self, entity_id: str) -> None:
        self._entity_id = entity_id

    def __eq__(self, other: object) -> _StateComparisonExpr:  # type: ignore[override]
        return _StateComparisonExpr(state(self._entity_id).is_(other), self._entity_id)

    def __ne__(self, other: object) -> _StateComparisonExpr:  # type: ignore[override]
        return _StateComparisonExpr(state(self._entity_id).is_not(other), self._entity_id)

    # A class defining `__eq__` loses the default identity-based `__hash__`
    # (Python sets it to `None` automatically, making instances unhashable).
    # Nothing in this codebase hashes/dict-keys a `_StateAccessor`, but there
    # is no reason to make it a landmine for a future caller either (e.g. a
    # test helper deduplicating accessors in a set) -- explicit opt-back-in to
    # plain identity hashing/equality-by-identity-for-hash-bucketing (the
    # `object.__hash__` default), matching the "hash-story finding" this
    # milestone's spec asked to be documented.
    __hash__ = object.__hash__

    def __gt__(self, other: float) -> NumericStateExpr:
        from hassle.compiler.triggers import numeric_state

        return numeric_state(self._entity_id, above=other)

    def __lt__(self, other: float) -> NumericStateExpr:
        from hassle.compiler.triggers import numeric_state

        return numeric_state(self._entity_id, below=other)

    def __ge__(self, other: float) -> NumericStateExpr:
        from hassle.compiler.errors import InclusiveNumericBoundError

        raise InclusiveNumericBoundError(">=", self._entity_repr(), other, capture_span(depth=0))

    def __le__(self, other: float) -> NumericStateExpr:
        from hassle.compiler.errors import InclusiveNumericBoundError

        raise InclusiveNumericBoundError("<=", self._entity_repr(), other, capture_span(depth=0))

    def in_(self, values: Sequence[Any]) -> StateExpr:
        """``entity.state.in_(["a", "b"])`` -> a ``state`` condition with a
        list value (HA's own OR-membership shape) — the honest, working
        spelling for what ``entity.state in [...]`` cannot be (the
        ``in``-operator trap documented on the class)."""
        return state(self._entity_id).is_(list(values))

    def _entity_repr(self) -> str:
        return self._entity_id

    def _branch_repr(self) -> str:
        return f"{self._entity_id}.state"


class _StateComparisonExpr(_NoBool):
    """The condition-builder object ``entity.state == v`` / ``!= v`` returns
    (MILESTONES M20). Wraps a real ``StateExpr``/``_NotStateExpr`` — its
    ``to_condition()`` delegates directly, so it compiles byte-identical to
    the equivalent classic builder form (this milestone's test 1).

    A dedicated wrapper (rather than returning the inner ``StateExpr``/
    ``_NotStateExpr`` directly) so the ``in``-operator trap and the
    trigger/condition non-confusion story (test 3) both have one exact type
    to reason about: this object is CONDITION-ONLY (no ``to_trigger``), so
    passing it to ``when(...)`` fails with a plain, honest
    ``AttributeError`` on the missing method rather than silently compiling
    as some unrelated trigger shape.
    """

    def __init__(self, inner: StateExpr | _NotStateExpr, entity_id: str) -> None:
        self._inner = inner
        self._entity_id = entity_id

    def __bool__(self) -> bool:
        # The in-operator trap (see class + _StateAccessor docstrings): this
        # is the object `list.__contains__` actually calls `bool()` on for
        # `x.state in [...]`, so THIS `__bool__` is where the dedicated
        # `.in_([...])`-naming message belongs -- not the generic
        # `CompileTimeBranchError` a bare `if_then(...)` rewrite hint would
        # give (misleading here: this specific value came from `==`/`!=`, but
        # the exact same trap fires for `in`, which is the far more likely
        # cause of an accidental `bool()` call on a comparison result).
        from hassle.compiler.errors import InOperatorTrapError

        raise InOperatorTrapError(self._branch_repr(), capture_span(depth=0))

    def to_condition(self) -> dict[str, Any]:
        return self._inner.to_condition()

    def _branch_repr(self) -> str:
        return f"{self._entity_id}.state"


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

    ``target=`` also accepts the bare entity target sugar (``ux/dsl-ergonomics``, item 3,
    DESIGN §5.3/§7.3): a bare entity ref/string or a list of them (``{"entity_id": ...}``), or
    an ``area()``/``floor()``/``label()``/``device_id()`` target helper object (``{"area_id":
    ...}`` etc.) — normalized to HA's stored target dict shape by
    :func:`~hassle.compiler.purpose.normalize_target`. An already-built dict passes through
    unchanged (the pre-existing behavior).
    """

    def __init__(
        self,
        action: str,
        *,
        target: Any = None,
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
        self._target = normalize_target(target)
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
