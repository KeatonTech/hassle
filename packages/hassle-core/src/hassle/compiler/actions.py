"""User-facing action verbs that record into the active context.

``service(...)`` and ``delay(...)`` build an action and append it to the active
recorder's current action list, capturing the DSL call-site span. Kept separate
from :mod:`hassle.compiler.recording` (which must not depend on builders) and
from :mod:`hassle.compiler.builders` (which must not depend on the recorder):
this module is the thin verb layer that ties the two together.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.builders import DelayAction, ServiceAction
from hassle.compiler.recording import record_action
from hassle.compiler.spans import capture_span


def service(
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
    """Record a service-call action (DESIGN §5.3). Bare kwargs go into ``data``.

    ``response_variable`` and ``continue_on_error`` are emitted as top-level HA
    action fields (not merged into ``data``) — folded in here so ``service()`` is
    the single service-call verb.

    ``metadata=`` (real-world smoke-test addition): the HA UI stamps
    ``"metadata": {}`` on every action it saves; passing it (even as ``{}``)
    round-trips byte-stable (compile(decompile(x)) must equal x for any
    config, docs/internals/ha-api-notes.md). Omitted by
    default for DSL-authored actions that never had one.

    ``data_template=`` (docs/internals/ha-api-notes.md §20):
    the legacy templated-data key, a sibling of ``data`` — never merged into
    it, so it round-trips exactly as HA stores it.

    ``alias=``/``enabled=``: per-step name/toggle,
    same treatment as ``metadata=``/``data_template=``.

    ``target=`` also accepts the bare entity target sugar:
    an ``EntityRef``/``str`` or a list of them, or an ``area()``/``floor()``/``label()``/
    ``device_id()`` target helper object — see :class:`~hassle.compiler.builders.ServiceAction`.
    """
    record_action(
        ServiceAction(
            action,
            target=target,
            data=data,
            data_template=data_template,
            response_variable=response_variable,
            continue_on_error=continue_on_error,
            metadata=metadata,
            alias=alias,
            enabled=enabled,
            **fields,
        ),
        span=capture_span(depth=0),
    )


def delay(*, alias: str | None = None, enabled: bool | None = None, **duration: Any) -> None:
    """Record a ``delay`` action (DESIGN §5.3), e.g. ``delay(minutes=5)``.

    ``alias=``/``enabled=`` (docs/internals/ha-api-notes.md §20): per-step name/toggle,
    keyword-only so they never collide with a duration unit passed via
    ``**duration``.
    """
    record_action(DelayAction(alias=alias, enabled=enabled, **duration), span=capture_span(depth=0))
