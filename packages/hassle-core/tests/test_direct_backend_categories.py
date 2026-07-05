"""DirectBackend fetches the UI category registry for automations/scripts
(DESIGN §7.3, docs/ha-api-notes.md new §22) as part of `fetch_registry_snapshot`.

Unit-tested (no network, R2) by monkeypatching `DirectBackend._client` with a
fake object exposing an async `ws_command`, and calling the private async
`_afetch_registry_snapshot` coroutine directly via `asyncio.run` -- this
exercises the real dispatch logic without needing a live event-loop thread or
a real HA instance (that end-to-end path is `test_m6_*` integration-only).
"""

from __future__ import annotations

import asyncio
from typing import Any

from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError


class _FakeClient:
    def __init__(self, responses: dict[str, Any], *, missing: set[str] = frozenset()) -> None:
        self._responses = responses
        self._missing = missing
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def ws_command(self, type: str, **payload: Any) -> Any:  # noqa: A002
        self.calls.append((type, payload))
        if type in self._missing:
            raise HaApiError(f"{type} not supported", code="unknown_command")
        key = type
        if type == "config/category_registry/list":
            key = f"config/category_registry/list:{payload.get('scope')}"
        return self._responses.get(key, [])

    async def ws_subscribe_first_event(self, type: str, **payload: Any) -> Any:  # noqa: A002
        return {}


def _make_backend(client: _FakeClient) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    return backend


def _run(backend: DirectBackend):
    return asyncio.run(backend._afetch_registry_snapshot())  # type: ignore[attr-defined]


def test_fetch_registry_snapshot_fetches_categories_for_automation_and_script() -> None:
    client = _FakeClient(
        {
            "config/category_registry/list:automation": [
                {"category_id": "lighting", "name": "Lighting", "icon": "mdi:lightbulb"},
            ],
            "config/category_registry/list:script": [
                {"category_id": "chores", "name": "Chores"},
            ],
        }
    )
    snapshot = _run(_make_backend(client))

    assert snapshot.categories["automation"]["lighting"] == "Lighting"
    assert snapshot.categories["script"]["chores"] == "Chores"

    scopes_requested = {
        payload.get("scope")
        for cmd, payload in client.calls
        if cmd == "config/category_registry/list"
    }
    assert scopes_requested == {"automation", "script"}


def test_fetch_registry_snapshot_tolerates_missing_category_registry_command() -> None:
    # Older HA (pre-category-registry) rejects the WS command outright -- must
    # degrade to an empty category map, not raise (mirrors the existing
    # floor_registry guard in the same method).
    client = _FakeClient({}, missing={"config/category_registry/list"})
    snapshot = _run(_make_backend(client))
    assert snapshot.categories == {}


def test_fetch_registry_snapshot_one_scope_failing_does_not_drop_the_other() -> None:
    # Only "automation" is missing/broken on this (hypothetical) instance --
    # "script" categories must still come through.
    client = _FakeClient(
        {"config/category_registry/list:script": [{"category_id": "chores", "name": "Chores"}]},
        missing=set(),
    )

    class _PartialClient(_FakeClient):
        async def ws_command(self, type: str, **payload: Any) -> Any:  # noqa: A002
            if type == "config/category_registry/list" and payload.get("scope") == "automation":
                raise HaApiError("boom")
            return await super().ws_command(type, **payload)

    partial = _PartialClient(client._responses)
    snapshot = _run(_make_backend(partial))
    assert snapshot.categories.get("automation", {}) == {}
    assert snapshot.categories["script"]["chores"] == "Chores"
