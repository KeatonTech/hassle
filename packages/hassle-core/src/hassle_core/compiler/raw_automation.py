"""``@raw_automation`` / ``@blueprint_automation`` (DESIGN §5.8) -- model/builder
layer only; see the contract-gap note below for what is NOT wired up.

**Deviation from DESIGN §5.8 (recorded in docs/ha-api-notes.md):** the design
text shows::

    @raw_automation(id="1687201958261")
    LEGACY_DEVICE_AUTOMATION = {...}

A decorator applied directly above a variable assignment is not valid Python
syntax (``@x`` only applies to a following ``def``/``class``); the design's
own paragraph after it calls this the "raw dict assignment form", implying two
forms were intended. This module implements both as valid Python: a decorator
over a zero-arg function returning the dict (mirroring ``@automation``'s own
shape, so it would slot into the same registration model if the pipeline gap
below were closed), and a plain-call form taking the dict directly.

**Scope note (contract gap, reported to the orchestrator/human) -- same root
cause as ``helpers.py``:** a raw/blueprint automation is a whole bundle-level
*object* (it must appear in ``CompileResult.objects`` under
``"automation:<id>"``), not a trigger/condition/action *inside* one. Getting a
new top-level object into ``CompileResult.objects`` requires either a new
``Registry``/``RegisteredObject`` registration path (``registry.py``) or a new
branch in ``compile_registered`` (``bundle.py``) that skips the "run a
function, record trigger/condition/action calls into it" recorder model and
calls ``CompileResult.add()`` directly with a pre-built ``AutomationConfig``.
Both are outside this workstream's editable files (docs/m1-internal-api.md
marks ``bundle.py`` "No"; ``registry.py`` has no seam for a non-function
registration today). This module therefore builds and validates the IR object
correctly (:func:`build_raw_automation` / :func:`build_blueprint_automation`,
plus the JSON-serializability error, M1 test 5) and tracks declarations
(:func:`declared_raw_automations`, mirroring ``helpers.py``'s pattern), but
nothing here wires them into ``compile_bundle(...).objects`` yet.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

from hassle_core.compiler.errors import CompileError
from hassle_core.compiler.spans import SourceSpan, capture_span
from hassle_core.ir import normalize_ha
from hassle_core.ir.models import AutomationConfig

F = TypeVar("F", bound=Callable[[], dict[str, Any]])

# Every AutomationConfig built by this module, in declaration order (mirrors
# helpers.py's `_DECLARED` -- the seam a future pipeline change would drain).
_DECLARED: list[AutomationConfig] = []


class RawAutomationNotJSONSerializableError(CompileError):
    """A ``raw_automation``/``@blueprint_automation`` body contains a value
    that cannot round-trip as JSON (M1 test 5 / scope item 6)."""

    def __init__(self, automation_id: str, detail: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"The raw automation `{automation_id}`{where} contains a value that is not "
            f"JSON-serializable ({detail}). Every HA config is stored as JSON, so a raw "
            f"body must contain only JSON-compatible values (str/int/float/bool/None/"
            f"list/dict). Fix: replace the offending value with a JSON-compatible "
            f"equivalent (e.g. an ISO date string instead of a `datetime`, or a plain "
            f"number instead of a custom object)."
        )


def reset_declared_raw_automations() -> None:
    """Clear the process-wide declared list (tests / repeated compiles)."""
    _DECLARED.clear()


def declared_raw_automations() -> list[AutomationConfig]:
    """Every raw/blueprint automation declared so far (in declaration order)."""
    return list(_DECLARED)


def _check_json_serializable(
    automation_id: str, body: dict[str, Any], span: SourceSpan | None
) -> None:
    try:
        json.dumps(body)
    except (TypeError, ValueError) as exc:
        raise RawAutomationNotJSONSerializableError(automation_id, str(exc), span) from exc


def _build(automation_id: str, body: dict[str, Any], span: SourceSpan | None) -> AutomationConfig:
    _check_json_serializable(automation_id, body, span)
    full_body = {"id": automation_id, **body}
    normalized = normalize_ha(full_body, kind="automation")
    obj = AutomationConfig.model_validate(normalized)
    _DECLARED.append(obj)
    return obj


def build_raw_automation(*, id: str, **body: Any) -> AutomationConfig:
    """Build (and validate) a raw automation's ``AutomationConfig`` from a
    verbatim dict body -- the "dict assignment form" (DESIGN §5.8).

    Legacy singular keys (``trigger``/``condition``/``action``, ``service:``)
    are normalized exactly as HA itself would on storage (``normalize_ha``,
    already applied here). Not yet wired into ``compile_bundle`` -- see the
    module docstring's contract-gap note.
    """
    span = capture_span(depth=0)
    return _build(id, body, span)


def raw_automation(*, id: str) -> Callable[[F], F]:
    """Decorator form: ``@raw_automation(id=...)`` over a zero-arg function
    returning the raw dict body (see the module docstring's deviation note
    for why this is a function, not a bare variable assignment).
    """
    span = capture_span(depth=0)

    def decorate(func: F) -> F:
        body = func()
        _build(id, body, span)
        return func

    return decorate


def blueprint_automation(
    *, id: str, use_blueprint: str, inputs: dict[str, Any] | None = None
) -> AutomationConfig:
    """``@blueprint_automation(id=..., use_blueprint="author/file.yaml", inputs={...})``
    (DESIGN §5.8).

    Maps the DSL's ergonomic ``inputs=`` to the stored JSON shape
    ``use_blueprint: {"path": ..., "input": ...}`` (singular ``input`` --
    docs/ha-api-notes.md §10.5, quirk #4). A blueprint automation stores only
    ``use_blueprint``, no ``triggers/conditions/actions`` (the blueprint is
    applied at runtime by HA). Not yet wired into ``compile_bundle`` -- see
    the module docstring's contract-gap note.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"use_blueprint": {"path": use_blueprint, "input": dict(inputs or {})}}
    return _build(id, body, span)
