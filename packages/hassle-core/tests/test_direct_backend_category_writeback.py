"""M11 -- `DirectBackend`'s category write-back surface: `create_category` /
`assign_category` (additive, not part of the frozen `Backend` Protocol F2,
same pattern as `entry_id_for`/`fetch_registry_snapshot`).

Unit-tested (no network, R2) the same way `test_direct_backend_categories.py`
tests `_afetch_registry_snapshot`: monkeypatch `DirectBackend._client` with a
fake exposing an async `ws_command`, and drive the private async coroutine
directly via `asyncio.run`.

Shapes (docs/ha-api-notes.md §30 -- inferred from HA core's
`homeassistant/components/config/category_registry.py` and
`entity_registry.py`, NOT live-verified in this PR; see §30's caveat):

- `config/category_registry/create` -- `{scope, name}` -> `{category_id, name,
  icon}` (same row shape as `.../list`).
- `config/entity_registry/update` -- `{entity_id, categories}` where
  `categories` is the FULL per-scope dict to store (HA's entity registry
  update replaces `categories` wholesale, so a caller preserving another
  scope's existing assignment must merge client-side first).
"""

from __future__ import annotations

import asyncio
from typing import Any

from hassle.backend.direct import DirectBackend


class _FakeClient:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def ws_command(self, type: str, **payload: Any) -> Any:
        self.calls.append((type, payload))
        if type == "config/entity_registry/list":
            return self._responses.get("config/entity_registry/list", [])
        if type == "config/category_registry/create":
            return {
                "category_id": self._responses.get("new_category_id", "new_cat"),
                "name": payload["name"],
                "icon": None,
            }
        if type == "config/entity_registry/update":
            return {"entity_id": payload["entity_id"]}
        return self._responses.get(type, [])


def _make_backend(client: _FakeClient) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    # `_aassign_category` bounded-polls for the entity-registry row (same
    # settle-wait class as `_await_config_entity`, §17.7) -- a fast budget
    # here keeps the "not found" test from actually waiting out a real
    # timeout while still exercising the same code path.
    backend._reload_timeout = 0.05  # type: ignore[attr-defined]
    backend._reload_interval = 0.01  # type: ignore[attr-defined]
    return backend


def test_create_category_sends_scope_and_name() -> None:
    client = _FakeClient({"new_category_id": "cat_hvac"})
    backend = _make_backend(client)

    category_id = asyncio.run(backend._acreate_category("automation", "Automatic HVAC"))  # type: ignore[attr-defined]

    assert category_id == "cat_hvac"
    ((_cmd, payload),) = [c for c in client.calls if c[0] == "config/category_registry/create"]
    assert payload == {"scope": "automation", "name": "Automatic HVAC"}


def test_assign_category_looks_up_entity_by_unique_id_and_updates() -> None:
    client = _FakeClient(
        {
            "config/entity_registry/list": [
                {
                    "entity_id": "automation.auto_hvac_1",
                    "unique_id": "auto_hvac_1",
                    "categories": {},
                }
            ]
        }
    )
    backend = _make_backend(client)

    asyncio.run(backend._aassign_category("automation", "auto_hvac_1", "automation", "cat_hvac"))  # type: ignore[attr-defined]

    ((_cmd, payload),) = [c for c in client.calls if c[0] == "config/entity_registry/update"]
    assert payload["entity_id"] == "automation.auto_hvac_1"
    assert payload["categories"] == {"automation": "cat_hvac"}


def test_assign_category_merges_with_existing_other_scope_categories() -> None:
    """I6: assigning the automation-scope category must never silently drop
    an already-present assignment under a different scope on the same entity
    row (categories are stored/replaced wholesale by HA's entity registry
    update, per this module's docstring)."""
    client = _FakeClient(
        {
            "config/entity_registry/list": [
                {
                    "entity_id": "script.take_out_trash",
                    "unique_id": "take_out_trash",
                    "categories": {"other_scope": "unrelated"},
                }
            ]
        }
    )
    backend = _make_backend(client)

    asyncio.run(backend._aassign_category("script", "take_out_trash", "script", "cat_chores"))  # type: ignore[attr-defined]

    ((_cmd, payload),) = [c for c in client.calls if c[0] == "config/entity_registry/update"]
    assert payload["categories"] == {"other_scope": "unrelated", "script": "cat_chores"}


def test_assign_category_raises_when_entity_not_found() -> None:
    client = _FakeClient({"config/entity_registry/list": []})
    backend = _make_backend(client)

    try:
        asyncio.run(backend._aassign_category("automation", "nope", "automation", "cat_x"))  # type: ignore[attr-defined]
    except LookupError:
        pass
    else:
        raise AssertionError("expected a LookupError when no entity-registry row matches")


class _SettlingClient(_FakeClient):
    """The entity-registry row appears only after `appears_after` calls to
    `config/entity_registry/list` -- models the async settle gap
    `_aassign_category`'s bounded poll exists to cover (docs/ha-api-notes.md
    §30 addendum, §17.7's `_await_config_entity` precedent)."""

    def __init__(self, row: dict[str, Any], *, appears_after: int) -> None:
        super().__init__()
        self._row = row
        self._appears_after = appears_after
        self._list_calls = 0

    async def ws_command(self, type: str, **payload: Any) -> Any:
        if type == "config/entity_registry/list":
            self._list_calls += 1
            self.calls.append((type, payload))
            return [self._row] if self._list_calls > self._appears_after else []
        return await super().ws_command(type, **payload)


def test_assign_category_polls_until_entity_registry_row_appears() -> None:
    row = {
        "entity_id": "automation.auto_hvac_1",
        "unique_id": "auto_hvac_1",
        "categories": {},
    }
    client = _SettlingClient(row, appears_after=2)
    backend = _make_backend(client)

    asyncio.run(backend._aassign_category("automation", "auto_hvac_1", "automation", "cat_hvac"))  # type: ignore[attr-defined]

    ((_cmd, payload),) = [c for c in client.calls if c[0] == "config/entity_registry/update"]
    assert payload["entity_id"] == "automation.auto_hvac_1"
    assert client._list_calls > 2  # actually polled more than once before succeeding
