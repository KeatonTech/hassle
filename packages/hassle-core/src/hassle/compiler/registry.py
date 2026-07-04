"""Object registration + the ``@automation`` / ``@script`` decorators (DESIGN §7.2).

Decorating a function *registers* it (records the callable, its declared options,
and the decoration-site span) into the module-level :class:`Registry`. The compiler
later drains the registry and invokes each function inside a :class:`Recorder`.

Registration is process-global but scoped by the bundle loader: :func:`fresh`
swaps in an empty registry around a bundle import so two compiles never bleed into
each other (determinism, R8) and repeated imports in one process stay isolated.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from hassle.compiler.recording import check_options
from hassle.compiler.spans import SourceSpan, capture_span
from hassle.ir.models import IRObject


@dataclass
class RegisteredObject:
    """A function registered by ``@automation``/``@script``, awaiting compilation."""

    kind: str  # "automation" | "script"
    func: Callable[..., Any]
    options: dict[str, Any]
    span: SourceSpan | None
    # The declared id (explicit ``id=`` or the function name default). The object
    # key is ``"<kind>:<declared_id>"``.
    declared_id: str


@dataclass
class PrebuiltObject:
    """An already-built IR object awaiting registration into the CompileResult.

    Unlike :class:`RegisteredObject` there is no function to run inside a
    recorder — helper declarations (DESIGN §5.7) and ``raw_automation`` /
    ``@blueprint_automation`` (DESIGN §5.8) are whole top-level objects. The
    compiler adds these straight to ``CompileResult.objects`` (bundle.py),
    skipping the trigger/condition/action recording model (§12 fix).
    """

    obj: IRObject
    span: SourceSpan | None


def _empty_registered() -> list[RegisteredObject]:
    return []


def _empty_prebuilt() -> list[PrebuiltObject]:
    return []


@dataclass
class Registry:
    objects: list[RegisteredObject] = field(default_factory=_empty_registered)
    prebuilt: list[PrebuiltObject] = field(default_factory=_empty_prebuilt)

    def add(self, obj: RegisteredObject) -> None:
        self.objects.append(obj)

    def add_object(self, obj: IRObject, span: SourceSpan | None) -> None:
        """Register an already-built IR object (helper / raw / blueprint).

        The §12 registration path: no ``func`` is required. The compiler drains
        these alongside the function-shaped registrations and adds them directly
        to the ``CompileResult`` (bundle.py).
        """
        self.prebuilt.append(PrebuiltObject(obj=obj, span=span))


# Default None (ruff B039: no mutable ContextVar default); a fresh Registry is
# created lazily on first access and installed so callers share one instance.
_REGISTRY: ContextVar[Registry | None] = ContextVar("hassle_registry", default=None)


def current_registry() -> Registry:
    reg = _REGISTRY.get()
    if reg is None:
        reg = Registry()
        _REGISTRY.set(reg)
    return reg


def fresh() -> Registry:
    """Install a new empty registry and return it (used by the bundle loader)."""
    reg = Registry()
    _REGISTRY.set(reg)
    return reg


def _register(kind: str, options: dict[str, Any], func: Callable[..., Any]) -> None:
    span = options.pop("__span__", None)
    check_options(kind, options, span)
    declared_id = options.get("id") or func.__name__
    current_registry().add(
        RegisteredObject(
            kind=kind,
            func=func,
            options=dict(options),
            span=span,
            declared_id=str(declared_id),
        )
    )


def automation(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register an automation (DESIGN §5.3). Accepts every HA automation option.

    The undecorated function is returned unchanged, so a bundle can still call it
    (e.g. a test importing the function). Compilation runs it inside a recorder.
    """
    span = capture_span(depth=0)

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        _register("automation", {**options, "__span__": span}, func)
        return func

    return decorate


def script(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a script (DESIGN §5.7). Accepts HA's script options + typed fields."""
    span = capture_span(depth=0)

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        _register("script", {**options, "__span__": span}, func)
        return func

    return decorate
