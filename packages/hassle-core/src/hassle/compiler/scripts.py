"""``@shared_script`` + ``param()`` (DESIGN §5.6/§5.7, MILESTONES M1 test 3).

``@shared_script`` builds on the core's existing ``script()`` registration
(``hassle.compiler.registry.script`` -- already handled end-to-end by
``compile_registered``/``compile_bundle``, docs/m1-internal-api.md's table does
not list ``registry.py`` as off-limits and ``script()`` is exactly the seam:
"a new builder family is just ... expose thin constructor functions"). It adds:

- **fields from the signature**: a shared script's Python parameters become the
  script's ``fields`` block (HA's typed-input UI), with Python defaults mapped
  to field ``default``.
- **``param(name)``**: inside the function body (which the compiler runs once,
  exactly like a plain ``@script``, to *build* the sequence), ``param("times")``
  is not the compile-time Python default -- it is a runtime reference to the
  script's own field, i.e. the Jinja read ``{{ times }}`` (a ``TemplateExpr``,
  so it composes with the template builder's operators). ``param()`` outside an
  active shared-script body, or naming a parameter absent from the signature,
  raises a what/where/fix error (R6).
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
from typing import Any

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


class NoParamContextError(CompileError):
    """``param()`` was called outside any ``@shared_script`` body."""

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`param({name!r})` was called outside any `@shared_script` body{where}. "
            f"`param()` reads one of the enclosing shared script's own fields at "
            f"runtime, so it only makes sense inside a function decorated with "
            f"`@shared_script`. Fix: call `param(...)` only from within a "
            f"`@shared_script`-decorated function, or use a plain Python value here."
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
    parameters (M1 test 5: `param()` referencing an unknown name is a snapshot-
    tested error).
    """
    span = capture_span(depth=0)
    fields = _ACTIVE_FIELDS.get()
    if fields is None:
        raise NoParamContextError(name, span)
    if name not in fields:
        raise UnknownParamError(name, sorted(fields), span)
    return TemplateExpr(name)


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
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Bind a caller's compile-time args/kwargs against ``func``'s signature,
    applying declared defaults, and return the {field: value} data map."""
    sig = inspect.signature(func)
    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def shared_script(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a real HA script AND make the decorated name a call-site verb.

    ``@shared_script(id=..., alias=..., icon=...)`` on ``func``:

    - derives HA ``fields`` from ``func``'s parameters (defaults -> field
      default) and registers ``func`` via the core's ``script(**options)`` --
      the compiler invokes ``func`` exactly once (like any other ``@script``)
      to build the sequence, with the active-fields context set so `param()`
      resolves inside it;
    - returns a *wrapper* (not ``func`` itself) so that calling
      ``flash_lights(...)`` from another automation/script body never re-runs
      the body -- it records a ``ScriptCallAction`` instead (DESIGN §5.6: "callers
      compile to `script.turn_on` / `script.flash_lights`").
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        object_id = str(options.get("id") or func.__name__)
        fields = _fields_from_signature(func)
        script_options = dict(options)
        if fields:
            script_options["fields"] = fields

        @functools.wraps(func)
        def compiled_body(*args: Any, **kwargs: Any) -> Any:
            token = _ACTIVE_FIELDS.set(frozenset(fields))
            try:
                return func(*args, **kwargs)
            finally:
                _ACTIVE_FIELDS.reset(token)

        _register_script(**script_options)(compiled_body)

        @functools.wraps(func)
        def caller(
            *args: Any,
            metadata: dict[str, Any] | None = None,
            alias: Any = None,
            enabled: Any = None,
            **kwargs: Any,
        ) -> None:
            data = _bind_call_args(func, args, kwargs)
            record_action(
                ScriptCallAction(object_id, data, metadata=metadata, alias=alias, enabled=enabled),
                span=capture_span(depth=0),
            )

        return caller

    return decorate
