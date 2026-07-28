"""Arrangement helpers for the `run --live` integration suite (real HA).

A live test may assume nothing about the instance it runs against except
what it arranges itself. That is stricter than "every CI container is
fresh": the integration suite is also run twice against one long-lived
instance, and the `ha` fixture's wipe does not make a re-run identical to a
first run. A storage-collection `input_boolean` is a `RestoreEntity` -- when
a helper is deleted and re-created under an `entity_id` the instance has
seen before, HA restores the state the previous run left it in rather than
coming up at the fresh-instance default of `"off"`
(docs/internals/ha-api-notes.md §29 addendum, round 4). Anything a test
needs, it therefore SETS and then OBSERVES.

The helpers live in this module rather than inline in `test_run_live.py` so
the unit suite can regression-test the contract without a live HA:
`packages/hassle-cli/tests/test_run_live_isolation.py` loads this file by
path and drives it against stub backends that model both live failure modes
(a restored `"on"` state; an entity that never appears in `/api/states`).
"""

from __future__ import annotations

import time
from typing import Any, Protocol

# Generous enough for a real HA to add an entity and process a service call,
# short enough that a genuinely broken arrangement fails fast.
SETTLE_TIMEOUT = 10.0
POLL_INTERVAL = 0.25


class LiveBackend(Protocol):
    """The slice of `DirectBackend` these helpers use."""

    def create(self, kind: str, config: dict[str, Any]) -> str: ...
    def call_service(self, domain: str, service: str, **data: Any) -> Any: ...
    def states(self) -> list[dict[str, Any]]: ...


def entity_state(ha: LiveBackend, entity_id: str) -> str | None:
    """The entity's current state, or `None` if it is not in `/api/states`."""
    for state in ha.states():
        if state.get("entity_id") == entity_id:
            return str(state["state"])
    return None


def await_entity(ha: LiveBackend, entity_id: str, *, timeout: float = SETTLE_TIMEOUT) -> str:
    """Block until `entity_id` exists in `/api/states`; return its state.

    Creating a helper through the storage-collection API returns as soon as
    the collection item is stored -- the entity appears a moment later. A
    service call at an entity that does not exist yet is silently no-op'd by
    HA, so every arrangement waits here first.
    """
    deadline = time.monotonic() + timeout
    while True:
        state = entity_state(ha, entity_id)
        if state is not None:
            return state
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{entity_id} never appeared in /api/states within {timeout}s -- the helper "
                "was created but its entity never materialized (the live symptom is a bare "
                '"Entity not found"). Nothing downstream can be arranged against it.'
            )
        time.sleep(POLL_INTERVAL)


def await_state(
    ha: LiveBackend, entity_id: str, expected: str, *, timeout: float = SETTLE_TIMEOUT
) -> str:
    """Block until `entity_id` is observably in `expected`; return it.

    Settle-proof for every precondition a live test depends on: a failure
    later in the test can then never be ambiguous between "the behavior
    under test is broken" and "the arrangement never landed".
    """
    deadline = time.monotonic() + timeout
    actual = None
    while True:
        actual = entity_state(ha, entity_id)
        if actual == expected:
            return actual
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{entity_id} never reached {expected!r} within {timeout}s "
                f"(last observed: {actual!r})"
            )
        time.sleep(POLL_INTERVAL)


def arrange_input_boolean(
    ha: LiveBackend, *, name: str, state: str, timeout: float = SETTLE_TIMEOUT
) -> str:
    """Create an `input_boolean` helper in `state`; return its entity id.

    `state` is SET explicitly even when it matches HA's fresh-instance
    default: that default only holds for an `entity_id` the instance has
    never used before (see the module docstring), which is exactly the
    assumption that made this suite non-self-isolating on a second run.
    """
    if state not in ("on", "off"):
        raise ValueError(f"input_boolean state must be 'on' or 'off', got {state!r}")
    object_id = ha.create("input_boolean", {"name": name})
    entity_id = f"input_boolean.{object_id}"
    await_entity(ha, entity_id, timeout=timeout)
    ha.call_service("input_boolean", f"turn_{state}", entity_id=entity_id)
    await_state(ha, entity_id, state, timeout=timeout)
    return entity_id


def arrange_counter(ha: LiveBackend, *, name: str, timeout: float = SETTLE_TIMEOUT) -> str:
    """Create a `counter` helper; return its entity id once it reads numeric.

    A counter's value is likewise restored on a re-used `entity_id`, so tests
    compare it against a reading taken before the phase under test rather
    than against a hard-coded starting value -- which means the first
    readable value has to be a number, not `"unknown"`. Waiting for that here
    keeps a slow start from surfacing as a `ValueError` out of
    `counter_value` mid-assertion.
    """
    object_id = ha.create("counter", {"name": name})
    entity_id = f"counter.{object_id}"
    deadline = time.monotonic() + timeout
    while True:
        state = await_entity(ha, entity_id, timeout=timeout)
        if _as_int(state) is not None:
            return entity_id
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{entity_id} never reported a numeric value within {timeout}s "
                f"(last observed: {state!r})"
            )
        time.sleep(POLL_INTERVAL)


def counter_value(ha: LiveBackend, entity_id: str) -> int:
    """The counter's current value.

    Both failure modes raise `AssertionError` naming the entity, never a bare
    `ValueError` from `int()` -- a counter reading `"unknown"` is a broken
    arrangement, and it should say so.
    """
    state = entity_state(ha, entity_id)
    if state is None:
        raise AssertionError(f"{entity_id} not found in /api/states")
    value = _as_int(state)
    if value is None:
        raise AssertionError(f"{entity_id} reads {state!r}, not a numeric counter value")
    return value


def _as_int(state: str) -> int | None:
    try:
        return int(state)
    except ValueError:
        return None
