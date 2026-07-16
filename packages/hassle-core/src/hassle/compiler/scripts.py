"""``@shared_script`` + ``param()`` (DESIGN §5.6/§5.7).

``@shared_script`` builds on the core's existing ``script()`` registration
(``hassle.compiler.registry.script``, already handled end-to-end by
``compile_registered``/``compile_bundle``). It adds:

- **fields from the signature**: a shared script's Python parameters become the
  script's ``fields`` block (HA's typed-input UI), with Python defaults mapped
  to field ``default``.
- **the function's own parameters ARE real runtime field references**:
  compiling a shared-script body binds EACH signature parameter whose name is
  a declared field to its ``param(name)`` marker (a ``TemplateExpr``) --
  regardless of its declared Python default -- so ``tag=tag`` inside the body
  means exactly the same thing as ``tag=param("tag")``. ``param(name)``
  remains the explicit spelling and is what the bound parameter is *set to*;
  the bound marker is a :class:`_BoundParamMarker` (a ``TemplateExpr``
  subclass) so ``range()``/``bool()``/``int()`` misuse on it raises the
  specialized :class:`SharedScriptParamMisuseError`, rather than the generic
  ``PythonMathMisuseError``/``CompileTimeBranchError``/bare ``TypeError`` a
  plain ``TemplateExpr`` would raise for the same misuse anywhere else --
  teaching the honest alternatives instead of an escape hatch that would bake
  a stale value in. See docs/internals/compiler.md for why a
  compile-time-default helper was rejected here and what the honest runtime
  and compile-time alternatives are. ``param()`` outside an active
  shared-script body, or naming a parameter absent from the signature, raises
  a what/where/fix error. A signature parameter that is NOT one of the
  declared fields (e.g. a body helper arg, only possible when ``fields=`` was
  given explicitly and is a strict subset of the signature) is left to its
  ordinary Python default -- only field-named parameters are bound.
- **the caller side**: the name bound to ``flash_lights`` after decoration is
  *not* the original function (which the compiler already invokes once via the
  ``script()`` registration to build the ``ScriptConfig``) -- it is a wrapper
  that, when called from inside another automation/script body, records a
  ``script.turn_on``-style call action (a plain service-call action targeting
  ``script.<object_id>``, matching how a UI-saved automation calls a script)
  instead of re-running the body. Compile-time Python values passed at the
  call site become the call's ``data``.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, cast

from hassle.compiler.errors import CompileError
from hassle.compiler.recording import record_action
from hassle.compiler.registry import script as _register_script
from hassle.compiler.spans import SourceSpan, capture_span
from hassle.compiler.templates import TemplateExpr

# ---------------------------------------------------------------------------
# param()
# ---------------------------------------------------------------------------

# The set of field names valid for `param()` inside the shared-script body
# currently being compiled (None when no shared-script body is active).
_ACTIVE_FIELDS: ContextVar[frozenset[str] | None] = ContextVar(
    "hassle_shared_script_fields", default=None
)


class SharedScriptParamMisuseError(CompileError):
    """Python control flow / numeric coercion / container introspection was
    used on a bound shared-script parameter.

    Every signature parameter that names a declared field is bound to its
    ``param(name)`` marker when the compiler invokes a ``@shared_script``
    body -- not the Python default -- so ``range(times)``, ``if tag:``,
    ``int(times)``, ``for x in items:``, ``"a" in tag``, ``len(tag)``,
    ``tag[0]``, etc. on a bound parameter can't honestly work at compile time
    (the marker has no runtime value until it renders inside Home Assistant
    -- and, being a ``str`` subclass, would otherwise silently do the wrong
    thing: iterate/index/measure the literal ``"{{ name }}"`` Jinja text
    instead of raising at all). This is the same class of trap
    ``CompileTimeBranchError``/``PythonMathMisuseError`` set for a raw
    ``TemplateExpr`` elsewhere in the DSL (DESIGN §5.5), specialized here to
    teach the honest alternatives instead of naming an escape hatch that
    would bake a stale compile-time value into the compiled sequence while
    the HA field still exists. See docs/internals/compiler.md for the
    rejected compile-time-default design and the full rationale.
    """

    def __init__(self, name: str, python_op: str, fix: str, span: SourceSpan | None) -> None:
        self.name = name
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"You used Python's `{python_op}` on the shared-script parameter `{name}`"
            f"{where}. Inside a `@shared_script` body, `{name}` is bound to its runtime "
            f"`param({name!r})` marker (regardless of its declared default), so it has "
            f"no compile-time value to give `{python_op}` -- it is Jinja text under "
            f"construction, not a real number/boolean/container, until it renders "
            f"inside Home Assistant. Fix: {fix}"
        )


# Per-operation-family fix text -- the blessed runtime alternative differs by
# WHAT the misuse was trying to do: `range()`/`bool()`/numeric coercion wants
# a runtime count/condition, `for`/`in`/`len`/indexing wants a runtime
# iteration/membership check. `{name}` is substituted with the actual
# parameter name at raise time.
_FIX_NUMERIC_OR_BOOLEAN = (
    "if you need a runtime count/condition, use a runtime construct HA itself "
    "supports, e.g. `with repeat_count({name}):` (accepts the marker directly "
    "and honors whatever the caller passes); if you actually need a "
    "compile-time value, `{name}` was never a real HA field -- use a "
    "module-level constant or a `@macro` argument instead."
)
_FIX_ITERATION_OR_CONTAINER = (
    "if you need runtime iteration, use `with repeat_for_each({name}):` (a "
    "bare template string passes through verbatim, honoring whatever the "
    "caller passes); if you need a runtime membership/length check, express "
    "it as a runtime condition/template (`.eq()`/`.in_()`/`template(...)`) "
    "evaluated inside Home Assistant, not Python; if you actually need a "
    "compile-time value, `{name}` was never a real HA field -- use a "
    "module-level constant or a `@macro` argument instead."
)


class _BoundParamMarker(TemplateExpr):
    """A ``param(name)`` marker bound to a shared-script body's OWN signature
    parameter -- a ``TemplateExpr`` subclass so it composes with the whole
    expression surface exactly like :func:`param`'s return value, but with
    ``range()``/``bool()``/``int()`` misuse (and container misuse:
    ``for``/``in``/``len``/indexing) raising the specialized
    :class:`SharedScriptParamMisuseError` (teaching the honest
    runtime-construct/compile-time-constant alternatives) instead of the
    generic ``CompileTimeBranchError``/``PythonMathMisuseError`` a plain
    :class:`TemplateExpr` raises for the numeric/boolean misuse everywhere
    else in the DSL. The container misuse is untrapped on a plain
    ``TemplateExpr``/``param()`` result used outside a shared-script body --
    a str subclass sails those through silently wrong (e.g.
    ``for x in items:`` would iterate the literal ``"{{ items }}"``
    characters); that gap is pre-existing and out of scope here. Never
    constructed directly by DSL authors -- :func:`param` returns one of these
    too (same traps apply); only :func:`shared_script`'s own
    ``compiled_body`` wrapper creates one when binding the signature, and
    :func:`param` itself.

    ``__str__``/``__repr__``/``_as_operand``/composition (``+``, ``.eq()``,
    ``concat(...)``, ...) are deliberately NOT trapped -- string rendering
    and the whole template-builder operator surface must keep working
    exactly like a plain :class:`TemplateExpr` (no internal codegen/rendering
    path calls ``len()``/``iter()``/``in``/indexing on a compiler-side
    template value -- every consumer uses ``str()``/``.to_template()``/
    ``._as_operand()``, JSON serialization treats a ``str`` as an opaque
    leaf, and f-string interpolation goes through ``__str__``, untouched
    here).
    """

    _param_name: str

    def __new__(cls, name: str) -> _BoundParamMarker:
        obj = cast("_BoundParamMarker", super().__new__(cls, name))
        obj._param_name = name
        return obj

    def _numeric_or_boolean_misuse(self, python_op: str) -> SharedScriptParamMisuseError:
        fix = _FIX_NUMERIC_OR_BOOLEAN.format(name=self._param_name)
        return SharedScriptParamMisuseError(self._param_name, python_op, fix, capture_span(depth=0))

    def _container_misuse(self, python_op: str) -> SharedScriptParamMisuseError:
        fix = _FIX_ITERATION_OR_CONTAINER.format(name=self._param_name)
        return SharedScriptParamMisuseError(self._param_name, python_op, fix, capture_span(depth=0))

    def __bool__(self) -> bool:
        raise self._numeric_or_boolean_misuse("if/bool()")

    def __index__(self) -> int:
        # `range(x)`/`list[x]`/... call `__index__`, not `__int__` -- Python's
        # own error for a plain TemplateExpr here ("cannot be interpreted as
        # an integer") never names file:line or a fix; this is the
        # shared-script boundary specialization of the what/where/fix error.
        raise self._numeric_or_boolean_misuse("range()/int()")

    def __int__(self) -> int:
        raise self._numeric_or_boolean_misuse("int()")

    def __float__(self) -> float:
        raise self._numeric_or_boolean_misuse("float()")

    def __round__(self, ndigits: int | None = None) -> float:
        raise self._numeric_or_boolean_misuse("round()")

    def __trunc__(self) -> int:
        raise self._numeric_or_boolean_misuse("math.trunc()")

    # -- container dunders: a `str` subclass sails `for x in marker:` /
    # `"a" in marker` / `len(marker)` / `marker[0]` through silently wrong
    # (iterating/indexing/measuring the literal Jinja text) rather than
    # raising at all -- trapped here the same way the numeric/boolean dunders
    # are, teaching the runtime-iteration (`repeat_for_each`) / runtime-
    # condition alternative instead.
    def __iter__(self) -> Any:
        raise self._container_misuse("for ... in")

    def __contains__(self, item: object) -> bool:
        raise self._container_misuse("in")

    def __len__(self) -> int:
        raise self._container_misuse("len()")

    def __getitem__(self, key: Any) -> Any:
        raise self._container_misuse("[...]")


class NoParamContextError(CompileError):
    """``param()`` was called outside any ``@shared_script`` body."""

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`param({name!r})` was called outside any `@shared_script` body{where}. "
            f"`param()` reads one of the enclosing shared script's own fields, so it "
            f"only makes sense inside a function decorated with `@shared_script`. "
            f"Fix: call `param(...)` only from within a `@shared_script`-decorated "
            f"function, or use a plain Python value here."
        )


class UnknownParamError(CompileError):
    """``param(name)`` named a parameter absent from the shared script's signature."""

    def __init__(self, name: str, known: list[str], span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        known_str = ", ".join(known) if known else "(none)"
        super().__init__(
            f"`param({name!r})`{where} does not match any parameter of this "
            f"`@shared_script` function. Its fields are: {known_str}. Fix: correct "
            f"the spelling, or add `{name}` as a parameter of the decorated function "
            f"so it becomes a script field."
        )


def param(name: str) -> TemplateExpr:
    """Reference a ``@shared_script``'s own field at runtime: ``{{ name }}``.

    Valid only inside the function body of a ``@shared_script`` (while the
    compiler is building its sequence); the name must be one of the function's
    parameters (``param()`` referencing an unknown name is a snapshot-tested
    error).

    Returns a :class:`_BoundParamMarker` (``param(name)`` stays valid and is
    exactly equivalent to the bound signature parameter of the same name), so
    ``range()``/``bool()``/``int()`` misuse on the RESULT of an explicit
    ``param(...)`` call gets the same specialized
    :class:`SharedScriptParamMisuseError` a bound bare parameter would --
    teaching the honest runtime-construct (``repeat_count(...)``) or
    compile-time-constant (a module constant / ``@macro`` argument)
    alternatives.
    """
    span = capture_span(depth=0)
    fields = _ACTIVE_FIELDS.get()
    if fields is None:
        raise NoParamContextError(name, span)
    if name not in fields:
        raise UnknownParamError(name, sorted(fields), span)
    return _BoundParamMarker(name)


def field_default(value: Any) -> TemplateExpr:
    """Typed default helper for a ``@shared_script`` signature parameter
    annotated ``TemplateExpr``: ``def f(tag: TemplateExpr = field_default("")): ...``.

    A shared-script body's own parameters are runtime template markers, not
    their declared Python default's type (see :func:`param` above), so the
    body-true annotation for any field is ``TemplateExpr`` -- this helper is
    the identity function at runtime (returns ``value`` unchanged, so the
    generated HA ``fields`` block sees the real declared default) but is
    typed as returning ``TemplateExpr``, so the parameter's default
    expression type-checks against its annotation. See
    docs/internals/compiler.md for the full typing rationale.
    """
    return value


# ---------------------------------------------------------------------------
# @shared_script
# ---------------------------------------------------------------------------


def _fields_from_signature(func: Callable[..., Any]) -> dict[str, Any]:
    """Build an HA ``fields`` block from ``func``'s parameters (defaults ->
    field ``default``)."""
    fields: dict[str, Any] = {}
    for name, p in inspect.signature(func).parameters.items():
        field: dict[str, Any] = {}
        if p.default is not inspect.Parameter.empty:
            field["default"] = p.default
        fields[name] = field
    return fields


class UnknownFieldError(CompileError):
    """A caller passed a kwarg that is not one of the target script's
    declared field names (``fields=``'s keys are the superset source of
    truth when supplied)."""

    def __init__(
        self, name: str, object_id: str, known: list[str], span: SourceSpan | None
    ) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        known_str = ", ".join(known) if known else "(none)"
        super().__init__(
            f"call to `{object_id}({name}=...)`{where} passes a field the script "
            f"doesn't declare. Its fields are: {known_str}. Fix: correct the spelling, "
            f"or add `{name}` to the script's `fields=` (and as a parameter of the "
            f"decorated function)."
        )


class ScriptCallAction:
    """A shared script invocation, recorded at the caller's DSL call site.

    Matches how HA stores calling a script: a plain service-call action
    targeting ``script.<object_id>``, normalized to ``action:``. Compile-time
    call args become ``data`` so HA passes them as the script's fields at
    runtime, matching the ``script.turn_on`` call-with-variables shape.

    Also carries the same ``metadata``/``alias``/``enabled`` step options
    every other action shape accepts, so the decompiler's function-call
    rewrite (a caller's ``{"action": "script.<id>", "metadata": {...}}``
    action becomes ``<fn_name>(<data kwargs>, metadata={...})``) recompiles
    to the exact same stored shape -- a UI-saved action's ``metadata: {}``
    (even empty, docs/ha-api-notes.md §19.1) and any step
    ``alias``/``enabled`` must round-trip through the call, not just
    ``data``.
    """

    def __init__(
        self,
        object_id: str,
        data: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
        alias: Any = None,
        enabled: Any = None,
    ) -> None:
        self._object_id = object_id
        self._data = data
        self._metadata = metadata
        self._alias = alias
        self._enabled = enabled

    def to_action(self) -> dict[str, Any]:
        body: dict[str, Any] = {"action": f"script.{self._object_id}"}
        if self._data:
            body["data"] = dict(self._data)
        if self._alias is not None:
            body["alias"] = self._alias
        if self._enabled is not None:
            body["enabled"] = self._enabled
        if self._metadata is not None:
            body["metadata"] = dict(self._metadata)
        return body


def _bind_call_args(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    object_id: str,
    known_field_names: frozenset[str] | None,
    span: SourceSpan | None,
) -> dict[str, Any]:
    """Bind a caller's compile-time args/kwargs against ``func``'s signature,
    applying declared defaults, and return the {field: value} data map.

    ``known_field_names``: when supplied (a ``@shared_script(fields=...)``
    was given explicitly), it is the superset source of truth for which
    kwarg names are legal -- checked before signature binding, so an author
    who added a Python parameter but forgot to also list it in ``fields=``
    gets a clear error naming the script's actual declared fields, rather
    than an unrelated ``TypeError`` (or, worse, silently binding against a
    parameter HA never told the field is real). ``None`` (no explicit
    ``fields=``) means the signature itself is the only source of truth.
    """
    if known_field_names is not None:
        for name in kwargs:
            if name not in known_field_names:
                raise UnknownFieldError(name, object_id, sorted(known_field_names), span)
    sig = inspect.signature(func)
    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def shared_script(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a real HA script AND make the decorated name a call-site verb.

    ``@shared_script(id=..., alias=..., icon=..., fields=...)`` on ``func``:

    - derives HA ``fields`` from ``func``'s parameters (defaults -> field
      default) and registers ``func`` via the core's ``script(**options)`` --
      the compiler invokes ``func`` exactly once (like any other ``@script``)
      to build the sequence, with the active-fields context set so `param()`
      resolves inside it;
    - **``fields=``:** when supplied explicitly, it is stored VERBATIM as the
      script's ``fields`` block instead of the signature-derived one --
      byte-stability by construction, since real HA-UI-authored scripts carry
      full field metadata (``name``/``description``/``selector``/...) the
      signature alone can never reconstruct. The signature stays the
      ergonomic call-site layer regardless: every parameter is still a real
      Python name (typically ``None``-defaulted for a rich field, since HA-
      side requiredness lives in the metadata, not in whether the compiler
      can invoke the body with zero arguments to build its sequence).
      ``fields=``'s keys become the superset source of truth for call-site
      kwarg validation (see :func:`_bind_call_args`) and for ``param()``
      (the active-fields context below uses ``fields=``'s keys when given,
      so ``param()`` can reference any declared field, not just ones that
      happen to also be Python parameters).
    - returns a *wrapper* (not ``func`` itself) so that calling
      ``flash_lights(...)`` from another automation/script body never re-runs
      the body -- it records a ``ScriptCallAction`` instead (DESIGN §5.6: "callers
      compile to `script.turn_on` / `script.flash_lights`").
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        object_id = str(options.get("id") or func.__name__)
        explicit_fields = options.get("fields")
        signature_fields = _fields_from_signature(func)
        script_options = dict(options)
        active_field_names: frozenset[str]
        if isinstance(explicit_fields, dict):
            # Verbatim wins (byte-stability by construction) -- never merged
            # with the signature-derived shape, so decompile -> recompile
            # reproduces the exact same fields= literal.
            active_field_names = frozenset(cast("dict[str, Any]", explicit_fields))
        elif signature_fields:
            script_options["fields"] = signature_fields
            active_field_names = frozenset(signature_fields)
        else:
            active_field_names = frozenset()

        # Every signature parameter whose name is a declared field is bound
        # to its `param(name)` marker BEFORE the body runs, regardless of its
        # declared Python default -- `tag=tag` inside the body means exactly
        # `tag=param("tag")`. A signature parameter that is NOT a declared
        # field (only possible when `fields=` was given explicitly and
        # doesn't cover every Python parameter) is left unbound -- ordinary
        # `bind_partial`/`apply_defaults` fills it from its own Python
        # default.
        bound_param_names = tuple(
            name for name in inspect.signature(func).parameters if name in active_field_names
        )

        @functools.wraps(func)
        def compiled_body(*args: Any, **kwargs: Any) -> Any:
            fields_token = _ACTIVE_FIELDS.set(active_field_names)
            try:
                bound_kwargs = dict(kwargs)
                for name in bound_param_names:
                    bound_kwargs.setdefault(name, param(name))
                return func(*args, **bound_kwargs)
            finally:
                _ACTIVE_FIELDS.reset(fields_token)

        _register_script(**script_options)(compiled_body)

        # known_field_names is None (skip the superset check, signature-only
        # validation) unless fields= was given explicitly -- a plain
        # signature-derived shared_script keeps its pre-existing behavior
        # exactly (Python's own TypeError on an unknown kwarg).
        known_field_names = active_field_names if isinstance(explicit_fields, dict) else None

        @functools.wraps(func)
        def caller(
            *args: Any,
            metadata: dict[str, Any] | None = None,
            alias: Any = None,
            enabled: Any = None,
            **kwargs: Any,
        ) -> None:
            span = capture_span(depth=0)
            data = _bind_call_args(
                func,
                args,
                kwargs,
                object_id=object_id,
                known_field_names=known_field_names,
                span=span,
            )
            record_action(
                ScriptCallAction(object_id, data, metadata=metadata, alias=alias, enabled=enabled),
                span=span,
            )

        return caller

    return decorate
