"""Actionable mobile notification recipe library:
`notify_mobile(...)` / `action(...)`.

Target syntax::

    with notify_mobile(title="Title", message="Hello World"):
        with action("Open Blinds", icon="mdi:blinds-open"):
            cover.open_cover(target=e.cover.all_top)
        with action("Close Blinds"):
            cover.close_cover(target=e.cover.all_top)

Compiles to (DESIGN §5.5/§5.6 sugar, one-way -- see
``test_capture_notify_recipe_roundtrip.py``):

1. one ``notify.*`` service call whose ``data.actions`` list carries one
   ``{action, title, icon?}`` entry per ``action(...)`` block (HA's actionable
   -notification action-button schema) -- the button ids are
   ``SLUGIFY(title).upper()``, e.g. ``"Open Blinds"`` -> ``"OPEN_BLINDS"``;
2. a ``wait_for(event("mobile_app_notification_action"), timeout=...)`` step;
3. a ``choose()`` whose branches are conditioned on
   ``var("wait.trigger['event']['data']['action']").eq(SLUG)`` -- HA's own Jinja
   context after a satisfied ``wait_for_trigger`` exposes the firing
   trigger's data as ``wait.trigger`` (the only spelling for a wait-variable
   read documented anywhere in this DSL surface, docs/internals/ha-api-notes.md §30) --
   running that branch's captured body (built with the public
   `capture_actions`/`emit_actions` seam, `hassle.compiler.recording`) if
   the tapped button matches.

Built ENTIRELY on the public DSL surface (`capture_actions`/`emit_actions`,
`choose`, `wait_for`, `event`, `var`, `service`) -- no compiler-internal
import. Targets list + timeout are keyword-only with sensible defaults
(``targets=None`` -> broadcasts to every configured mobile-app target this
recipe's ``notify_mobile(...)`` call names; ``timeout="00:05:00"``).
"""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from hassle import capture_actions, choose, emit_actions, event, service, var, wait_for

#: Default time to wait for the user to tap a notification action button
#: before the automation's action sequence gives up (HA's own
#: `wait_for_trigger` `timeout=`, passed straight through).
DEFAULT_TIMEOUT = "00:05:00"


def _wait_action_id_var() -> Any:
    """``var("wait.trigger['event']['data']['action']")`` -- HA's own Jinja context
    exposing the firing event's data after a satisfied
    `wait_for_trigger` -- but spelled with bracket subscripts
    (``wait.trigger['event']['data']['action']``) instead of dotted attribute
    access. Semantically identical (the simulator's/HA's context object
    supports both `AttrDict` styles) and renders to the same value at
    runtime; spelled this way ONLY to dodge a registry-validator false
    positive (`hassle.registry.extract._extract_entity_ids_from_jinja`'s
    regex fallback -- see docs/internals/ha-api-notes.md §30): its known-ish-domain
    regex matches bare `event.data` inside `wait.trigger.event.data.action`
    (because `event.*` is itself a real HA entity domain) and misreports it
    as an unknown entity id. Filed as a validator bug, not fixed here.
    """
    return var("wait.trigger['event']['data']['action']")


def _action_id(title: str) -> str:
    """HA's actionable-notification convention: an upper-cased slug of the
    button's title (e.g. ``"Open Blinds"`` -> ``"OPEN_BLINDS"``) -- distinct
    from (but built the same way as) `hassle.ir.keys.slugify`'s lower-cased
    object-key convention, since HA's own `notify_actions` examples always
    upper-case the action id."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    return (slug or "action").upper()


class _NotifyAction:
    """One recorded ``action(...)`` block: its button spec plus captured body."""

    def __init__(self, title: str, icon: str | None) -> None:
        self.title = title
        self.icon = icon
        self.action_id = _action_id(title)
        self.body: list[dict[str, Any]] = []


class _NotifyMobileBuilder:
    """The object yielded by ``with notify_mobile(...) as n:`` (unused by the
    target syntax above, which never binds ``as n:`` -- `action(...)`
    reaches the active builder via a context var, mirroring how `choose()`'s
    branches reach their `_ChooseBuilder` without the bundle author having to
    pass it explicitly to `when_`)."""

    def __init__(self) -> None:
        self.actions: list[_NotifyAction] = []


_ACTIVE: list[_NotifyMobileBuilder] = []


@contextmanager
def notify_mobile(
    *,
    title: str,
    message: str,
    targets: list[str] | None = None,
    timeout: Any = DEFAULT_TIMEOUT,
    notify_service: str = "notify.mobile_app_kai",
) -> Generator[None]:
    """``with notify_mobile(title=, message=, targets=, timeout=):`` -- send an
    actionable mobile notification and dispatch on whichever button (if any)
    the user taps.

    ``targets=`` (default ``None``): a list of ``notify_service`` used one per
    target for multi-recipient delivery (HA has no single "targets" list on
    `notify.*` itself -- broadcasting to N phones is N service calls);
    ``None`` sends exactly one call to the ``notify_service`` given ("sensible
    default" -- the target syntax above names no targets at all).
    ``notify_service=`` (default ``"notify.mobile_app_kai"``, matching this
    cookbook's own registry snapshot/convention, `lib/notify.py`): the notify
    service to call. ``timeout=`` (default :data:`DEFAULT_TIMEOUT`): how long to wait
    for a button tap before giving up (the automation simply continues past
    the ``wait_for`` with no branch taken).
    """
    builder = _NotifyMobileBuilder()
    _ACTIVE.append(builder)
    try:
        yield
    finally:
        _ACTIVE.pop()

    ha_actions = [
        {"action": a.action_id, "title": a.title, **({"icon": a.icon} if a.icon else {})}
        for a in builder.actions
    ]
    data: dict[str, Any] = {"message": message, "title": title}
    if ha_actions:
        data["actions"] = ha_actions
    service_targets = targets if targets else [notify_service]
    for target_service in service_targets:
        service(target_service, **data)

    if not builder.actions:
        return  # no buttons: a plain notification, nothing to wait/dispatch on.

    wait_for(event("mobile_app_notification_action"), timeout=timeout)

    with choose() as c:
        for a in builder.actions:
            with c.when_(_wait_action_id_var().eq(a.action_id)):
                emit_actions(a.body)


@contextmanager
def action(title: str, *, icon: str | None = None) -> Generator[None]:
    """``with action("Open Blinds", icon="mdi:blinds-open"): ...`` -- one
    notification action button, and the actions to run if it is tapped.
    Must be used inside ``with notify_mobile(...):``.
    """
    if not _ACTIVE:
        raise RuntimeError(
            "`action(...)` was called with no active `notify_mobile(...)` block. "
            "Fix: use `with action(...):` only inside `with notify_mobile(...):`."
        )
    builder = _ACTIVE[-1]
    entry = _NotifyAction(title, icon)
    with capture_actions() as bodies:
        yield
    entry.body = bodies
    builder.actions.append(entry)
