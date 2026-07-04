"""Action primitives beyond the M1-core ``service``/``delay`` pair.

Sibling verb module (docs/m1-internal-api.md §2: "Add sibling builder files;
don't rewrite these"). Builds directly on ``record_action``/``capture_span``;
never imports or edits ``hassle_core.compiler.builders``/``actions``/``recording``
beyond their public seam.
"""

from __future__ import annotations

from typing import Any

from hassle_core.compiler.recording import record_action
from hassle_core.compiler.spans import capture_span


class _RawAction:
    """Adapter: wrap an already-built canonical action dict as an ``ActionBuilder``."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def to_action(self) -> dict[str, Any]:
        return self._body


def stop(message: str | None = None, *, error: bool | None = None) -> None:
    """Record a ``stop`` action (DESIGN §5.5 action primitives).

    Emits ``{"stop": <message>}`` (HA's message-only form) or, when ``error=``
    is given, the extended ``{"stop": <message>, "error": <bool>}`` form.
    """
    body: dict[str, Any] = {"stop": message or ""}
    if error is not None:
        body["error"] = error
    record_action(_RawAction(body), span=capture_span(depth=0))


def variables(**kwargs: Any) -> None:
    """Record a ``variables`` action: ``{"variables": {...}}``."""
    record_action(_RawAction({"variables": dict(kwargs)}), span=capture_span(depth=0))


def event(event_type: str, **event_data: Any) -> None:
    """Record an ``event`` (fire-event) action.

    Emits ``{"event": "<type>", "event_data": {...}}`` (omitting ``event_data``
    when there is none), matching HA's fire-event action schema.
    """
    body: dict[str, Any] = {"event": event_type}
    if event_data:
        body["event_data"] = event_data
    record_action(_RawAction(body), span=capture_span(depth=0))


def service_ext(
    action: str,
    *,
    target: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    response_variable: str | None = None,
    continue_on_error: bool | None = None,
    **fields: Any,
) -> None:
    """Service-call action with the corpus fields the core ``service()`` lacks.

    Same ``data``/kwargs merge behavior as the core builder, plus top-level
    ``response_variable``/``continue_on_error`` (HA action fields, not ``data``
    fields — they must not be merged into ``data``).
    """
    merged: dict[str, Any] = {}
    if data:
        merged.update(data)
    merged.update(fields)
    body: dict[str, Any] = {"action": action}
    if target is not None:
        body["target"] = target
    if merged:
        body["data"] = merged
    if response_variable is not None:
        body["response_variable"] = response_variable
    if continue_on_error is not None:
        body["continue_on_error"] = continue_on_error
    record_action(_RawAction(body), span=capture_span(depth=0))
