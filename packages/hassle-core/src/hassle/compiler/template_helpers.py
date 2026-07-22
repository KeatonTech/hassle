"""Template-helper declarations (DESIGN §5.7 extended + §13's config-entry
plugin) -- the model/builder layer for the ``template`` config-entry domain.

``template_number(name="Active HVAC Zones", state="{{ ... }}", set_value=...,
min=0, max=8, step=1)`` builds a
:class:`~hassle.ir.models.TemplateHelperConfig` for one of the four template
domains (``hassle.ir.TEMPLATE_DOMAINS``, additive to the frozen IR schema) and
returns an :class:`~hassle.compiler.helpers.EntityRef`, exactly like the nine
storage-collection helper builders in :mod:`hassle.compiler.helpers` -- same
"import-and-reference pattern" (DESIGN §5.7), same prebuilt-object
registration path into the active bundle registry.

**Identity (docs/internals/ha-api-notes.md §26.6): there is no ``id=``/``unique_id=``
kwarg.** The real `template` config flow's form schema rejects an
unrecognized ``unique_id`` key outright -- a flow-created entry has no
caller-settable unique id at all. Identity is derived from ``name``
(required), mirroring the nine storage helpers' "id is a slug of name" rule
(``hassle.ir.keys.slugify``) -- except here it's the ONLY identity source;
the object key is ``"<template domain>:<slugify(name)>"``. The HA-assigned
config ``entry_id`` remains transport-side identity only (manifest-only,
docs/internals/backend-protocol.md).

Storage truth: ``state=`` takes a literal Jinja template string (the config
entry's actual stored ``state`` option). Expression-builder values (an `Expr`
built via the runtime-math expression surface) are also accepted -- rendered
to Jinja at declaration time via ``str()`` -- since template strings are what
HA's config entry stores and what the decompiler reproduces (the expression
sugar is one-way).

**Required write-target fields (docs/internals/ha-api-notes.md §26.6):** a template
NUMBER's form schema requires ``set_value`` (the action sequence run when the
entity is set from the UI/a service call -- a template number needs a write
target, since ``state`` alone only computes the displayed value); a template
SELECT likewise requires ``select_option`` (the sequence run when an option
is chosen) alongside ``options`` (the Jinja-or-list of choices).
Sensor/binary_sensor need only ``state`` (they are read-only, no write
target). ``set_value``/``select_option`` accept a single action dict or a
list of action dicts (HA's own action-sequence shape); stored verbatim
(compile(decompile(x)) must equal x for any config -- Hassle's DSL action
builders are automation/script-scoped, not reusable here without a recording
context, so these are raw HA action dicts, matching the ``raw_action``
escape hatch's shape).

**Omitting a required write-target field is a COMPILE-TIME error:**
previously this only surfaced as a bare backend ``ValueError`` at APPLY time
(``hassle.backend.direct``/``hassle.backend.fake``'s
``_check_required_fields``), so ``hassle validate``/``hassle plan`` would pass
a bundle that was guaranteed to fail on push. ``_declare_template_helper``
(below) now raises :class:`~hassle.compiler.errors.MissingTemplateHelperWriteTargetError`
the moment ``template_number``/``template_select`` is called without its
required kwarg -- the backend checks are unchanged and remain a second line
of defense for any non-DSL path that builds a `TemplateHelperConfig` directly.

**``min``/``max``/``step`` are ``float``-coerced (docs/internals/ha-api-notes.md
§26.10):** HA's ``template_number`` form schema types these three fields as
``NumberSelector``, whose validator (``homeassistant/helpers/selector.py``)
unconditionally runs every submitted value through ``vol.Coerce(float)`` --
the config entry's stored options always have these as floats, however they
were submitted. ``template_number`` coerces them at declaration time
(``_coerce_number_field``) so the compiled local IR is byte-identical to the
remote config either way; nothing else across the four template domains has
a numeric field HA coerces (confirmed by reading every
``template_config_flow.py`` schema for number/sensor/binary_sensor/select --
only ``template_number``'s three fields use ``NumberSelector``).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hassle.compiler.errors import (
    CompileError,
    DanglingTemplateHelperDeclarationError,
    MissingTemplateHelperWriteTargetError,
    TemplateHelperDecoratorBodyError,
)
from hassle.compiler.helpers import EntityRef
from hassle.compiler.spans import SourceSpan, capture_span
from hassle.ir import TEMPLATE_DOMAINS
from hassle.ir.keys import slugify
from hassle.ir.models import TemplateHelperConfig

# Write-target fields HA's `template` config-flow form schema requires beyond
# `name`/`state` (docs/internals/ha-api-notes.md §26.6, mirrors `hassle.backend.direct`/
# `hassle.backend.fake`'s `_TEMPLATE_REQUIRED_FIELDS`): a template NUMBER
# needs `set_value` (the action run when the number is written), a template
# SELECT needs `select_option` (the action run when an option is chosen).
# Sensor/binary_sensor are read-only -- no extra required field. Checked here,
# at DSL build time, so an omission is a compile-time `hassle validate`/
# `hassle plan` finding instead of only failing at APPLY time; the backend
# checks (`_check_required_fields`) stay in place as a second line of defense
# for any non-DSL path that builds a `TemplateHelperConfig` directly.
_REQUIRED_WRITE_TARGET_FIELDS: dict[str, str] = {
    "template_number": "set_value",
    "template_select": "select_option",
}

# All TemplateHelperConfig instances built by this module's constructor
# functions, in declaration order, for the lifetime of the process (or since
# the last `reset_declared_template_helpers()`) -- mirrors
# `hassle.compiler.helpers._DECLARED`'s seam for this module's own unit tests.
_DECLARED: list[TemplateHelperConfig] = []


@dataclass
class _PendingDeclaration:
    """Bookkeeping for one ``state=``-omitted (decorator-form-signaling)
    builder call, tracked from creation until either consumed as a decorator
    (``TemplateHelperDeclaration.__call__`` -> ``_finalize``, which flips
    ``consumed``) or swept as dangling at compile end (see
    ``_build_or_defer`` below)."""

    builder: str
    name: str
    span: SourceSpan | None
    consumed: bool = False


# Every pending (state-omitted) declaration created since the last
# `reset_declared_template_helpers()`, in creation order -- the compile-end
# sweep (`check_no_dangling_template_helper_declarations`) walks this for any
# entry still `consumed=False`.
_PENDING: list[_PendingDeclaration] = []


def reset_declared_template_helpers() -> None:
    """Clear the process-wide declared-template-helpers list (tests / repeated compiles)."""
    _DECLARED.clear()
    _PENDING.clear()


def check_no_dangling_template_helper_declarations() -> None:
    """Compile-end sweep: raise
    :class:`~hassle.compiler.errors.DanglingTemplateHelperDeclarationError`
    for the FIRST still-unconsumed pending declaration (deterministic --
    creation order, since compiled output must be byte-stable), or return
    silently if every pending declaration was consumed as a decorator.

    Called from :mod:`hassle.compiler.bundle`'s ``compile_registered`` (the
    shared core both ``compile_bundle`` and any direct caller go through),
    after every registered/prebuilt object has been processed -- so this
    also covers a single-file/fixture compile path (golden error-case
    fixtures included), not just the whole-bundle loader.

    Self-cleaning: the pending list is cleared in a ``finally`` whether the
    sweep raises or not. Without this, a DIRECT ``compile_registered``
    caller (the CLI path is protected by ``compile_bundle``'s
    start-of-compile reset) would leak an unconsumed entry into the next
    compile in the same process, turning one dangling declaration into a
    false positive for every later, clean compile.
    """
    try:
        for pending in _PENDING:
            if not pending.consumed:
                raise DanglingTemplateHelperDeclarationError(
                    pending.builder, pending.name, pending.span
                )
    finally:
        _PENDING.clear()


def declared_template_helpers() -> list[TemplateHelperConfig]:
    """Every template helper declared so far (in declaration order)."""
    return list(_DECLARED)


def _render_state(state: Any) -> Any:
    """Accept either a literal Jinja string or an expression-builder value
    (an `Expr`, which renders via `str()`) -- template strings are the
    storage truth either way (module docstring)."""
    if state is None or isinstance(state, str):
        return state
    return str(state)


def _coerce_number_field(value: Any) -> Any:
    """Coerce a `template_number` `min`/`max`/`step` value to `float`
    (docs/internals/ha-api-notes.md §26.10): HA's `NumberSelector.__call__`
    (`homeassistant/helpers/selector.py`) runs every submitted `min`/`max`/
    `step` value through `vol.Coerce(float)` unconditionally and stores the
    result -- so the config entry's stored options always have these three
    fields as floats, regardless of what was submitted. A DSL author writing
    `min=0` (an `int`, the natural literal) would otherwise produce compiled
    local IR with an `int` where the remote/stored config has a `float`:
    same logical value, different canonical-JSON encoding
    (`hassle.ir.canonical.sha256_hash`: `json.dumps(0) != json.dumps(0.0)`),
    so a byte-stable re-plan would see a hash mismatch and plan UPDATE
    forever instead of NOOP. Coercing here, at compile time, keeps plan
    comparison a plain hash equality with no comparison-time special case
    (DESIGN §8.2). `None` passes through untouched (an omitted field stays
    omitted, `_declare_template_helper` drops `None`s already)."""
    if value is None:
        return None
    return float(value)


def _declare_template_helper(
    domain: str, name: str, *, span: SourceSpan | None, **fields: Any
) -> EntityRef:
    if domain not in TEMPLATE_DOMAINS:
        raise ValueError(
            f"unknown template helper domain {domain!r} "
            f"(expected one of {sorted(TEMPLATE_DOMAINS)})"
        )
    required_field = _REQUIRED_WRITE_TARGET_FIELDS.get(domain)
    if required_field is not None and fields.get(required_field) is None:
        raise MissingTemplateHelperWriteTargetError(domain, name, required_field, span)
    identity = slugify(name)
    body: dict[str, Any] = {
        "name": name,
        **{k: v for k, v in fields.items() if v is not None},
    }
    helper = TemplateHelperConfig.model_validate(body)
    helper.attach_domain(domain)
    _DECLARED.append(helper)
    # Same §12 registration path helpers.py uses: register into the active
    # bundle registry so the compiler lands this in CompileResult.objects.
    from hassle.compiler.registry import current_registry

    current_registry().add_object(helper, span)
    return EntityRef(domain, identity)


# ---------------------------------------------------------------------------
# Decorator form -- `@template_number(name=..., ...)` over a zero-arg
# function returning a `TemplateExpr`/`str` (DESIGN §5.4/§5.7 extension).
#
# `template_number`/`template_sensor`/`template_binary_sensor`/`template_select`
# already take only kwargs (the frozen DSL surface stays the same names, only
# new *usage* of the existing four). Detecting decorator use is done by the
# RETURNED object's shape, not by inspecting the call site: when `state=` is
# omitted, the call returns a `TemplateHelperDeclaration` (an `EntityRef`
# subclass -- so it is still a valid plain string/entity-id value if never
# called) that is ALSO a one-argument callable. Using it as
# `@template_number(...)` immediately calls it with the decorated function,
# at which point the function is invoked ONCE (like `@automation`/`@script`,
# DESIGN §7.2 -- the compiler doesn't defer this; template-helper
# declarations are prebuilt objects, not a recording registration), its
# return value is validated and rendered to Jinja text via `_render_state`,
# and the real `TemplateHelperConfig` is built and registered at THAT point
# -- not at the original `template_number(...)` call.
#
# When `state=` IS given (the call form), the object is built and registered
# immediately; the returned `TemplateHelperDeclaration` is still technically
# callable but calling it would double-register the object, so no decorator
# syntax ever does that in practice.
# ---------------------------------------------------------------------------


def _validate_decorator_body(
    builder: str, name: str, func: Callable[..., Any], span: SourceSpan | None
) -> Any:
    """Run ``func`` (zero args) and return its ``TemplateExpr``/``str`` value,
    or raise :class:`~hassle.compiler.errors.TemplateHelperDecoratorBodyError`
    for any of the three ways a decorator body can misbehave:
    declared parameters, a non-``TemplateExpr``/``str`` return, or (naturally,
    via :class:`~hassle.compiler.errors.NoRecordingContextError` -- calling
    the function here runs it with no active recorder) a recording verb
    (``service``/``when``/``only_if``/...) called from inside it.

    A plain (non-:class:`~hassle.compiler.errors.CompileError`) exception
    raised from inside the function body -- e.g. a user ``ZeroDivisionError``/
    ``ValueError``/assertion -- is chained under
    :class:`TemplateHelperDecoratorBodyError` so the helper's
    ``@template_...(name=..., ...)`` file:line is visible in the
    traceback, not just the bare exception from deep inside the user's
    function; the original exception and traceback are preserved via ``raise
    ... from exc``. Any :class:`~hassle.compiler.errors.CompileError` (e.g.
    ``NoRecordingContextError`` from a recording-verb call) already carries
    its own accurate location and is never re-wrapped.
    """
    sig = inspect.signature(func)
    if sig.parameters:
        param_names = ", ".join(sig.parameters)
        raise TemplateHelperDecoratorBodyError(
            builder,
            name,
            f"the decorated function `{func.__name__}` takes parameter(s) "
            f"({param_names}), but a template-helper decorator body is always "
            f"called with zero arguments.",
            span,
        )
    try:
        result = func()
    except CompileError:
        raise
    except Exception as exc:
        raise TemplateHelperDecoratorBodyError(
            builder,
            name,
            f"the decorated function `{func.__name__}` raised {type(exc).__name__}: {exc}",
            span,
        ) from exc
    from hassle.compiler.templates import TemplateExpr

    if isinstance(result, TemplateExpr) or (
        isinstance(result, str) and not isinstance(result, EntityRef)
    ):
        return result
    raise TemplateHelperDecoratorBodyError(
        builder,
        name,
        f"the decorated function `{func.__name__}` returned {result!r} "
        f"({type(result).__name__}), not a `TemplateExpr`/`str`.",
        span,
    )


class TemplateHelperDeclaration(EntityRef):
    """The value ``template_number(...)``/``template_sensor(...)``/etc. return.

    Behaves exactly like a plain :class:`~hassle.compiler.helpers.EntityRef`
    (a string usable as an entity id) in every case where ``state=`` was
    given -- the object is already fully built and registered by the time
    this is constructed. Additionally callable: ``@template_number(...)`` (no
    ``state=``) applies this as a decorator over a zero-arg function, which
    finalizes the declaration using the function's return value as ``state=``.
    """

    _finalize: Callable[[Callable[..., Any]], Callable[..., Any]] | None

    def __new__(
        cls,
        domain: str,
        identity: str,
        *,
        finalize: Callable[[Callable[..., Any]], Callable[..., Any]] | None = None,
    ) -> TemplateHelperDeclaration:
        # `str.__new__(cls, ...)` (not `EntityRef.__new__`/`super().__new__`)
        # so the constructed instance is a real `TemplateHelperDeclaration`
        # (pyright-strict-clean: no need to re-narrow an `EntityRef`-typed
        # return via `cast`) -- `EntityRef.__new__` itself does exactly this
        # dance (``str.__new__(cls, f"{domain}.{object_id}")``), so this
        # mirrors its own construction, just skipping the intermediate call.
        obj = str.__new__(cls, f"{domain}.{identity}")
        obj.domain = domain
        obj.object_id = identity
        obj._finalize = finalize
        return obj

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        if self._finalize is None:  # pragma: no cover - defensive, see class docstring
            raise TypeError(
                f"{self!r} was already declared with `state=` and is not usable as a "
                f"decorator; remove `state=` to use the decorator form instead."
            )
        return self._finalize(func)


def _build_or_defer(
    domain: str, name: str, state: Any, fields: dict[str, Any]
) -> TemplateHelperDeclaration:
    """Shared entry point for all four public builders: dispatches
    between the call form (``state=`` given -- build + register right
    now, span points at the ``template_number(...)``/etc. call site) and the
    decorator form (``state=`` omitted -- return a callable
    :class:`TemplateHelperDeclaration` whose ``__call__`` finalizes the
    declaration when applied to the decorated function, span points at the
    ``def ...():`` line via the decoration-site capture, matching how
    ``@automation``/``@script`` capture their span in ``registry.py``).
    """
    if state is not None:
        identity_ref = _declare_template_helper(
            domain, name, span=capture_span(depth=2), state=_render_state(state), **fields
        )
        return TemplateHelperDeclaration(identity_ref.domain, identity_ref.object_id)

    # Decorator form: the decoration-site span is captured NOW (at
    # `@template_number(...)` call time), matching `hassle.compiler.registry`'s
    # `automation`/`script` decorators -- not when the function later runs,
    # since `capture_span` looks for a non-``hassle`` frame, and by the time
    # `_finalize` runs (from `__call__`, itself invoked from the module-level
    # `@` syntax) the call stack shape is different (one extra decorator-call
    # frame) but still resolves to the same user line either way. Capturing at
    # `_build_or_defer` time is simplest and correct for both.
    decoration_span = capture_span(depth=2)

    # Track this `state=`-omitted call as PENDING the moment it's created --
    # if it's never applied as a decorator, the compile-end sweep
    # (`check_no_dangling_template_helper_declarations`) must catch it,
    # rather than the call silently doing nothing: a helper that already
    # exists in HA would otherwise vanish from the compiled set and get
    # scheduled for DELETE, silently losing track of it.
    pending = _PendingDeclaration(builder=domain, name=name, span=decoration_span)
    _PENDING.append(pending)

    def _finalize(func: Callable[..., Any]) -> Callable[..., Any]:
        pending.consumed = True
        rendered = _validate_decorator_body(domain, name, func, decoration_span)
        _declare_template_helper(
            domain, name, span=decoration_span, state=_render_state(rendered), **fields
        )
        return func

    identity = slugify(name)
    return TemplateHelperDeclaration(domain, identity, finalize=_finalize)


def template_number(
    *,
    name: str,
    state: Any = None,
    set_value: Any = None,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    unit_of_measurement: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> TemplateHelperDeclaration:
    """Declare a ``template_number`` helper (DESIGN §5.7), e.g.
    ``number.active_hvac_zones``.

    ``set_value`` is REQUIRED by HA's form schema (module docstring): the
    action (a raw HA action dict, or a list of them) run when the number is
    set -- e.g. ``{"action": "input_number.set_value", "target": {...},
    "data": {"value": "{{ value }}"}}``, where ``{{ value }}`` is HA's
    template variable for the submitted value. Omitting it raises
    :class:`~hassle.compiler.errors.MissingTemplateHelperWriteTargetError`
    at compile time (module docstring).

    ``min``/``max``/``step`` are coerced to ``float`` (docs/internals/ha-api-notes.md
    §26.10): HA's form schema (``NumberSelector``) always stores them as
    floats regardless of what's submitted, so a compiled ``int`` literal
    (the natural way to write ``min=0``) would otherwise never byte-match
    the remote config -- a permanent, spurious plan UPDATE (a plan-noop
    requires compile(decompile(x)) == x).

    **Decorator form:** omit ``state=`` and apply the return value as a
    decorator over a zero-arg function returning a ``TemplateExpr``/``str`` --
    ``set_value``/``min``/``max``/``step``/etc. are still passed as decorator
    kwargs exactly as in the call form::

        @template_number(name="Active HVAC Zones", set_value={...})
        def active_hvac_zones():
            return expr(e.input_number.hvac_zone_override)

    Compiles to the IDENTICAL IR as the call form with the equivalent
    ``state=`` Jinja string.
    """
    return _build_or_defer(
        "template_number",
        name,
        state,
        {
            "set_value": set_value,
            "min": _coerce_number_field(min),
            "max": _coerce_number_field(max),
            "step": _coerce_number_field(step),
            "unit_of_measurement": unit_of_measurement,
            "icon": icon,
            **fields,
        },
    )


def template_sensor(
    *,
    name: str,
    state: Any = None,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> TemplateHelperDeclaration:
    """Declare a ``template_sensor`` helper (DESIGN §5.7). Read-only
    (no write-target field -- ``state`` alone is HA's required schema).

    **Decorator form:** see :func:`template_number`'s docstring --
    omit ``state=`` and apply the return value as a decorator instead.
    """
    return _build_or_defer(
        "template_sensor",
        name,
        state,
        {
            "unit_of_measurement": unit_of_measurement,
            "device_class": device_class,
            "icon": icon,
            **fields,
        },
    )


def template_binary_sensor(
    *,
    name: str,
    state: Any = None,
    device_class: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> TemplateHelperDeclaration:
    """Declare a ``template_binary_sensor`` helper (DESIGN §5.7).
    Read-only, like ``template_sensor``.

    **Decorator form:** see :func:`template_number`'s docstring --
    omit ``state=`` and apply the return value as a decorator instead.
    """
    return _build_or_defer(
        "template_binary_sensor",
        name,
        state,
        {
            "device_class": device_class,
            "icon": icon,
            **fields,
        },
    )


def template_select(
    *,
    name: str,
    state: Any = None,
    options: Any = None,
    select_option: Any = None,
    icon: str | None = None,
    **fields: Any,
) -> TemplateHelperDeclaration:
    """Declare a ``template_select`` helper (DESIGN §5.7).

    ``options`` is a Jinja template string rendering to a list (HA's own
    ``template_select`` options field shape) -- a plain Python list literal is
    also accepted for convenience and passed straight through unmodified
    (extra="allow" preserves it verbatim like any other IR field, since
    compile(decompile(x)) must equal x for any config).
    ``select_option`` is REQUIRED by HA's form schema (module docstring): the
    action (or list of actions) run when an option is chosen, analogous to
    ``template_number``'s ``set_value``. Omitting it raises
    :class:`~hassle.compiler.errors.MissingTemplateHelperWriteTargetError`
    at compile time (module docstring).

    **Decorator form:** see :func:`template_number`'s docstring --
    omit ``state=`` and apply the return value as a decorator instead;
    ``options=``/``select_option=`` are still passed as decorator kwargs.
    """
    return _build_or_defer(
        "template_select",
        name,
        state,
        {
            "options": options,
            "select_option": select_option,
            "icon": icon,
            **fields,
        },
    )
