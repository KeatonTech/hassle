"""``@shared_script`` + ``param()`` (DESIGN §5.6/§5.7, MILESTONES M1 test 3).

``@shared_script`` builds on the core's existing ``script()`` registration
(``hassle.compiler.registry.script`` -- already handled end-to-end by
``compile_registered``/``compile_bundle``, docs/m1-internal-api.md's table does
not list ``registry.py`` as off-limits and ``script()`` is exactly the seam:
"a new builder family is just ... expose thin constructor functions"). It adds:

- **fields from the signature**: a shared script's Python parameters become the
  script's ``fields`` block (HA's typed-input UI), with Python defaults mapped
  to field ``default``.
- **the function's own parameters ARE real runtime field references**
  (MILESTONES M19): compiling a shared-script body binds EACH signature
  parameter whose name is a declared field to its ``param(name)`` marker (a
  ``TemplateExpr``) -- regardless of its declared Python default -- so
  ``tag=tag`` inside the body means exactly the same thing as
  ``tag=param("tag")`` (M19 test 1/4: byte-identical IR, both forms stay
  valid). ``param(name)`` remains the explicit spelling (back-compat, F3) and
  is what the bound parameter is *set to*; the bound marker is a
  :class:`_BoundParamMarker` (a ``TemplateExpr`` subclass) so
  ``range()``/``bool()``/``int()`` misuse on it raises the specialized
  :class:`SharedScriptParamMisuseError` (M19 test 2) naming the
  :func:`param_default` escape hatch, rather than the generic
  ``PythonMathMisuseError``/``CompileTimeBranchError``/bare ``TypeError`` a
  plain ``TemplateExpr`` would raise for the same misuse anywhere else.
  ``param()`` outside an active shared-script body, or naming a parameter
  absent from the signature, raises a what/where/fix error (R6, unchanged).
  A signature parameter that is NOT one of the declared fields (e.g. a body
  helper arg, only possible when ``fields=`` was given explicitly and is a
  strict subset of the signature) is left to its ordinary Python default --
  only field-named parameters are bound.
- **``param_default(name)``** (MILESTONES M19): the escape hatch for
  deliberate compile-time metaprogramming on a shared-script parameter (the
  ``for _ in range(...)`` unroll pattern) -- returns the field's DECLARED
  default (from the signature, or ``fields=``'s own ``"default"`` key when
  given explicitly), a plain Python value, never a ``TemplateExpr``. Valid
  only inside an active shared-script body; naming an absent field gets the
  same :class:`UnknownParamError` treatment as :func:`param`.
- **the caller side**: the name bound to ``flash_lights`` after decoration is
  *not* the original function (which the compiler already invokes once via the
  ``script()`` registration to build the ``ScriptConfig``) -- it is a wrapper
  that, when called from inside another automation/script body, records a
  ``script.turn_on``-style call action (matching the corpus script fixtures'
  stored shape: a plain service-call action, ``fixtures/configs/script_*.json``
  are invoked as ``{"action": "script.<object_id>"}`` shorthand -- see
  ``automation_parallel_action.json``) instead of re-running the body. Compile-
  time Python values passed at the call site become the call's ``data``.
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

# Each active field's DECLARED default (from the signature, or fields=''s own
# "default" key when given explicitly) -- the source `param_default()` reads
# from (MILESTONES M19). A field with no declared default at all is simply
# absent from this dict; `param_default()` on it is a hard R6 error (there is
# no compile-time value to hand back, unlike param()'s runtime marker, which
# never needs one).
_ACTIVE_DEFAULTS: ContextVar[dict[str, Any] | None] = ContextVar(
    "hassle_shared_script_defaults", default=None
)


class SharedScriptParamMisuseError(CompileError):
    """Python control flow / numeric coercion was used on a bound
    shared-script parameter (MILESTONES M19 test 2).

    Since M19, EVERY signature parameter that names a declared field is
    bound to its ``param(name)`` marker when the compiler invokes a
    ``@shared_script`` body -- not the Python default -- so ``range(times)``,
    ``if tag:``, ``int(times)``, etc. on a bound parameter can't honestly
    work at compile time (the marker has no runtime value until it renders
    inside Home Assistant). This is the SAME class of trap
    ``CompileTimeBranchError``/``PythonMathMisuseError`` set for a raw
    ``TemplateExpr`` elsewhere in the DSL (DESIGN §5.5), specialized here
    because the fix is different: a shared-script body has an actual declared
    default to fall back on, so the escape hatch is ``param_default(name)``,
    not a ``with if_then(...):`` rewrite or `hassle.compiler.math_expr`.
    """

    def __init__(self, name: str, python_op: str, span: SourceSpan | None) -> None:
        self.name = name
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"You used Python's `{python_op}` on the shared-script parameter `{name}`"
            f"{where}. Since M19, `{name}` inside this body is bound to its runtime "
            f"`param({name!r})` marker (regardless of its declared default), so it has "
            f"no compile-time value to give `{python_op}` -- it is Jinja text under "
            f"construction, not a number or a boolean, until it renders inside Home "
            f"Assistant. Fix: for deliberate compile-time metaprogramming (e.g. "
            f"unrolling a `for _ in range(...):` loop a fixed number of times), use "
            f"`param_default({name!r})` instead -- it returns `{name}`'s DECLARED "
            f"default, a plain Python value, not the runtime marker."
        )


class _BoundParamMarker(TemplateExpr):
    """A ``param(name)`` marker bound to a shared-script body's OWN signature
    parameter (MILESTONES M19) -- a ``TemplateExpr`` subclass so it composes
    with the whole expression surface exactly like :func:`param`'s return
    value, but with ``range()``/``bool()``/``int()`` misuse raising the
    specialized :class:`SharedScriptParamMisuseError` (naming the
    ``param_default()`` escape hatch) instead of the generic
    ``CompileTimeBranchError``/``PythonMathMisuseError`` a plain
    :class:`TemplateExpr` raises for the same misuse everywhere else in the
    DSL. Never constructed directly by DSL authors -- :func:`param` returns a
    plain :class:`TemplateExpr`; only :func:`shared_script`'s own
    ``compiled_body`` wrapper creates one, when binding the signature.
    """

    _param_name: str

    def __new__(cls, name: str) -> _BoundParamMarker:
        obj = cast("_BoundParamMarker", super().__new__(cls, name))
        obj._param_name = name
        return obj

    def __bool__(self) -> bool:
        raise SharedScriptParamMisuseError(self._param_name, "if/bool()", capture_span(depth=0))

    def __index__(self) -> int:
        # `range(x)`/`list[x]`/... call `__index__`, not `__int__` -- Python's
        # own error for a plain TemplateExpr here ("cannot be interpreted as
        # an integer") never names file:line or a fix (see the module-level
        # deviation note in the class docstring); this is the shared-script
        # boundary specialization the R6 error hooks.
        raise SharedScriptParamMisuseError(self._param_name, "range()/int()", capture_span(depth=0))

    def __int__(self) -> int:
        raise SharedScriptParamMisuseError(self._param_name, "int()", capture_span(depth=0))

    def __float__(self) -> float:
        raise SharedScriptParamMisuseError(self._param_name, "float()", capture_span(depth=0))

    def __round__(self, ndigits: int | None = None) -> float:
        raise SharedScriptParamMisuseError(self._param_name, "round()", capture_span(depth=0))

    def __trunc__(self) -> int:
        raise SharedScriptParamMisuseError(self._param_name, "math.trunc()", capture_span(depth=0))


class NoParamContextError(CompileError):
    """``param()``/``param_default()`` was called outside any ``@shared_script`` body."""

    def __init__(self, name: str, span: SourceSpan | None, *, fn: str = "param") -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`{fn}({name!r})` was called outside any `@shared_script` body{where}. "
            f"`{fn}()` reads one of the enclosing shared script's own fields, so it "
            f"only makes sense inside a function decorated with `@shared_script`. "
            f"Fix: call `{fn}(...)` only from within a `@shared_script`-decorated "
            f"function, or use a plain Python value here."
        )


class UnknownParamError(CompileError):
    """``param(name)``/``param_default(name)`` named a parameter absent from
    the shared script's signature."""

    def __init__(
        self, name: str, known: list[str], span: SourceSpan | None, *, fn: str = "param"
    ) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        known_str = ", ".join(known) if known else "(none)"
        super().__init__(
            f"`{fn}({name!r})`{where} does not match any parameter of this "
            f"`@shared_script` function. Its fields are: {known_str}. Fix: correct "
            f"the spelling, or add `{name}` as a parameter of the decorated function "
            f"so it becomes a script field."
        )


class NoDeclaredDefaultError(CompileError):
    """``param_default(name)`` named a field with no declared default at all
    (MILESTONES M19): there is no compile-time value to hand back -- unlike
    :func:`param`, which always has something to reference at runtime (the
    field itself), :func:`param_default` needs an actual Python value, and a
    field declared with no ``"default"`` key (an explicit ``fields=`` entry,
    or a bare ``name`` positional with no ``=...``) never had one.
    """

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        self.name = name
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`param_default({name!r})`{where}: `{name}` has no declared default -- "
            f'its `@shared_script` field spec has no `"default"` key (or its '
            f"signature parameter has no `=...`), so there is no compile-time value "
            f"for `param_default()` to return. Fix: give `{name}` a declared default "
            f'(a signature default, or a `"default"` key in `fields=`), or use '
            f"`param({name!r})` for the runtime reference instead."
        )


def param(name: str) -> TemplateExpr:
    """Reference a ``@shared_script``'s own field at runtime: ``{{ name }}``.

    Valid only inside the function body of a ``@shared_script`` (while the
    compiler is building its sequence); the name must be one of the function's
    parameters (M1 test 5: `param()` referencing an unknown name is a snapshot-
    tested error).

    Returns a :class:`_BoundParamMarker` (MILESTONES M19 test 4: back-compat
    -- ``param(name)`` stays valid and is exactly equivalent to the bound
    signature parameter of the same name), so ``range()``/``bool()``/``int()``
    misuse on the RESULT of an explicit ``param(...)`` call gets the same
    specialized :class:`SharedScriptParamMisuseError` a bound bare parameter
    would, naming the same ``param_default()`` escape hatch.
    """
    span = capture_span(depth=0)
    fields = _ACTIVE_FIELDS.get()
    if fields is None:
        raise NoParamContextError(name, span)
    if name not in fields:
        raise UnknownParamError(name, sorted(fields), span)
    return _BoundParamMarker(name)


def param_default(name: str) -> Any:
    """The escape hatch for deliberate compile-time metaprogramming on a
    shared-script parameter (MILESTONES M19): returns ``name``'s DECLARED
    default -- from the signature's own default, or ``fields=``'s
    ``"default"`` key when given explicitly -- a plain Python value, NEVER a
    ``TemplateExpr``. This is what makes the classic ``for _ in range(...):``
    unroll pattern still expressible after M19 bound every signature
    parameter to its runtime marker: ``param_default("times")`` sidesteps the
    binding entirely and hands back the actual compile-time default.

    Valid only inside an active ``@shared_script`` body; naming a field
    absent from the signature is the same :class:`UnknownParamError`
    :func:`param` raises for the same mistake (R6). Naming a field that IS
    declared but has no default at all (bare ``name=None`` with no
    ``"default"`` key in an explicit ``fields=`` entry) is a
    :class:`NoDeclaredDefaultError` instead -- a distinct mistake (nothing to
    correct the spelling of; the field just never had a compile-time value).
    """
    span = capture_span(depth=0)
    fields = _ACTIVE_FIELDS.get()
    if fields is None:
        raise NoParamContextError(name, span, fn="param_default")
    if name not in fields:
        raise UnknownParamError(name, sorted(fields), span, fn="param_default")
    defaults = _ACTIVE_DEFAULTS.get()
    if defaults is None or name not in defaults:
        raise NoDeclaredDefaultError(name, span)
    return defaults[name]


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
    truth when supplied -- ``ux/shared-script-rich-fields``)."""

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

    Matches the corpus's stored shape for calling a script (a plain
    service-call action targeting ``script.<object_id>``; see
    ``fixtures/configs/automation_parallel_action.json``'s
    ``{"service": "script.greet_guest"}``, normalized to ``action:`` by
    ``normalize_ha``). Compile-time call args become ``data`` so HA passes
    them as the script's fields at runtime, matching the ``script.turn_on``
    call-with-variables shape.

    F3-additive (``ux/shared-script-calls``, owner feedback): also carries
    the same ``metadata``/``alias``/``enabled`` step options every other
    action shape accepts, so the decompiler's function-call rewrite (a
    caller's ``{"action": "script.<id>", "metadata": {...}}`` action becomes
    ``<fn_name>(<data kwargs>, metadata={...})``) recompiles to the exact
    same stored shape -- a UI-saved action's ``metadata: {}`` (even empty,
    docs/ha-api-notes.md §19.1) and any step ``alias``/``enabled`` must
    round-trip through the call, not just ``data``.
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

    ``known_field_names`` (``ux/shared-script-rich-fields``): when supplied
    (a ``@shared_script(fields=...)`` was given explicitly), it is the
    SUPERSET source of truth for which kwarg names are legal -- checked
    before signature binding, so an author who added a Python parameter but
    forgot to also list it in ``fields=`` gets a clear error naming the
    script's actual declared fields, rather than an unrelated ``TypeError``
    (or, worse, silently binding against a parameter HA never told the field
    is real). ``None`` (no explicit ``fields=``) means the signature itself
    is the only source of truth, exactly as before this widening.
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
    - **``fields=`` (F3-additive, ``ux/shared-script-rich-fields``, owner
      feedback):** when supplied explicitly, it is stored VERBATIM as the
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
        active_defaults: dict[str, Any]
        if isinstance(explicit_fields, dict):
            # Verbatim wins (byte-stability by construction) -- never merged
            # with the signature-derived shape, so decompile -> recompile
            # reproduces the exact same fields= literal.
            explicit_fields_dict = cast("dict[str, Any]", explicit_fields)
            active_field_names = frozenset(explicit_fields_dict)
            active_defaults = {
                name: spec["default"]
                for name, spec in explicit_fields_dict.items()
                if isinstance(spec, dict) and "default" in spec
            }
        elif signature_fields:
            script_options["fields"] = signature_fields
            active_field_names = frozenset(signature_fields)
            active_defaults = {
                name: spec["default"]
                for name, spec in signature_fields.items()
                if "default" in spec
            }
        else:
            active_field_names = frozenset()
            active_defaults = {}

        # M19: every signature parameter whose name is a declared field is
        # bound to its `param(name)` marker BEFORE the body runs, regardless
        # of its declared Python default -- `tag=tag` inside the body means
        # exactly `tag=param("tag")` (test 1/4). A signature parameter that
        # is NOT a declared field (only possible when `fields=` was given
        # explicitly and doesn't cover every Python parameter) is left
        # unbound -- ordinary `bind_partial`/`apply_defaults` fills it from
        # its own Python default, same as before M19.
        bound_param_names = tuple(
            name for name in inspect.signature(func).parameters if name in active_field_names
        )

        @functools.wraps(func)
        def compiled_body(*args: Any, **kwargs: Any) -> Any:
            fields_token = _ACTIVE_FIELDS.set(active_field_names)
            defaults_token = _ACTIVE_DEFAULTS.set(active_defaults)
            try:
                bound_kwargs = dict(kwargs)
                for name in bound_param_names:
                    bound_kwargs.setdefault(name, param(name))
                return func(*args, **bound_kwargs)
            finally:
                _ACTIVE_DEFAULTS.reset(defaults_token)
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
