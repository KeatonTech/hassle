"""Purpose-vocabulary enumeration must accumulate snapshot events, not stop
at the first one (docs/ha-api-notes.md §17.2).

Regression: observed live on 2026-07-21, `trigger_platforms/subscribe` acked
and pushed an initial *partial* snapshot (159 trigger types -- missing all
calendar.*, timer.*, todo.*, zone.* entries) with follow-up events arriving as
lazily-loaded trigger platforms registered; a refresh moments later returned
the settled 179. Taking only the first event made `hassle validate` report a
false `unknown-purpose-type` for `calendar.event_started`.

Two layers, both no-network (R2):
- `HaClient.ws_subscribe_settled_events` against a fake WS that pushes the
  ack, a partial snapshot event, a fuller follow-up event, then goes quiet --
  must return BOTH events (and unsubscribe afterwards).
- `DirectBackend._subscribe_keys` against a fake client -- must return the
  sorted key-union across events, and keep the "unsupported command ->
  empty vocabulary" downgrade for pre-2026.7 HA.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from hassle.backend.client import HaClient
from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError

# -- client layer ---------------------------------------------------------


class _FakeMsg:
    type = aiohttp.WSMsgType.TEXT

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _ScriptedWs:
    """Replays scripted incoming frames keyed off the subscription id, then
    hangs (a settled-but-open socket) so only the settle window can end the
    collection loop."""

    closed = False

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.sent: list[dict[str, Any]] = []
        self._queue: list[dict[str, Any]] | None = None

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)
        if self._queue is None:  # the subscribe command itself
            msg_id = payload["id"]
            self._queue = [
                {"id": msg_id, "type": "result", "success": True},
                *({"id": msg_id, "type": "event", "event": event} for event in self._events),
            ]

    async def receive(self) -> _FakeMsg:
        if self._queue:
            return _FakeMsg(self._queue.pop(0))
        await asyncio.Event().wait()  # quiet stream; cancelled by the settle window
        raise AssertionError("unreachable")


def test_settled_subscribe_accumulates_partial_then_full_snapshot() -> None:
    partial = {"device.turned_on": {}, "state.changed": {}}
    follow_up = {"calendar.event_started": {}, "timer.finished": {}}
    ws = _ScriptedWs([partial, follow_up])

    client = HaClient("http://ha.example", "test-token")

    async def _fake_ensure_ws() -> Any:
        return ws

    client._ensure_ws = _fake_ensure_ws  # type: ignore[method-assign]

    events = asyncio.run(
        client.ws_subscribe_settled_events("trigger_platforms/subscribe", settle_seconds=0.05)
    )

    assert events == [partial, follow_up]
    # The subscription is still torn down after settling.
    assert ws.sent[-1]["type"] == "unsubscribe_events"
    assert ws.sent[-1]["subscription"] == ws.sent[0]["id"]


# -- backend layer --------------------------------------------------------


class _FakeSettledClient:
    def __init__(self, events_by_command: dict[str, list[Any]]) -> None:
        self._events_by_command = events_by_command

    async def ws_subscribe_settled_events(self, type: str, **payload: Any) -> list[Any]:
        if type not in self._events_by_command:
            raise HaApiError(f"{type} not supported", code="unknown_command")
        return self._events_by_command[type]


def _make_backend(client: Any) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    return backend


def test_subscribe_keys_unions_keys_across_snapshot_events() -> None:
    backend = _make_backend(
        _FakeSettledClient(
            {
                "trigger_platforms/subscribe": [
                    {"state.changed": {}, "device.turned_on": {}},
                    # Follow-up repeats one key and adds the late-loading ones.
                    {"state.changed": {}, "calendar.event_started": {}, "timer.finished": {}},
                ],
                "condition_platforms/subscribe": [],
            }
        )
    )

    vocab = asyncio.run(backend._afetch_purpose_vocabulary())  # type: ignore[attr-defined]

    assert vocab.triggers == [
        "calendar.event_started",
        "device.turned_on",
        "state.changed",
        "timer.finished",
    ]
    assert vocab.conditions == []


def test_subscribe_keys_still_degrades_to_empty_on_unsupported_command() -> None:
    # Pre-2026.7 HA rejects the subscription -> empty vocabulary, no raise.
    backend = _make_backend(_FakeSettledClient({}))
    vocab = asyncio.run(backend._afetch_purpose_vocabulary())  # type: ignore[attr-defined]
    assert vocab.triggers == []
    assert vocab.conditions == []
