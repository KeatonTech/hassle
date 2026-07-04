"""User-facing action verbs that record into the active context.

``service(...)`` and ``delay(...)`` build an action and append it to the active
recorder's current action list, capturing the DSL call-site span. Kept separate
from :mod:`hassle_core.compiler.recording` (which must not depend on builders) and
from :mod:`hassle_core.compiler.builders` (which must not depend on the recorder):
this module is the thin verb layer that ties the two together.
"""

from __future__ import annotations

from typing import Any

from hassle_core.compiler.builders import DelayAction, ServiceAction
from hassle_core.compiler.recording import record_action
from hassle_core.compiler.spans import capture_span


def service(
    action: str,
    *,
    target: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    **fields: Any,
) -> None:
    """Record a service-call action (DESIGN §5.3). Bare kwargs go into ``data``."""
    record_action(
        ServiceAction(action, target=target, data=data, **fields),
        span=capture_span(depth=0),
    )


def delay(**duration: Any) -> None:
    """Record a ``delay`` action (DESIGN §5.3), e.g. ``delay(minutes=5)``."""
    record_action(DelayAction(**duration), span=capture_span(depth=0))
