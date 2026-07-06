"""M12 test 1 (DirectBackend payload half) -- `attempt_category_writeback`'s
`category_override`, when supplied, reaches `DirectBackend.create_category`
(and so `config/category_registry/create`'s WS payload) as the EXACT string,
never `humanize_slug`'d. `DirectBackend.create_category` itself already just
forwards `name` verbatim (`test_direct_backend_category_writeback.py`'s
`test_create_category_sends_scope_and_name`) -- this test proves the M12
plumbing one level up actually supplies the CATEGORY string as that `name`
argument instead of a slug-derived guess.

Same no-network harness as `test_direct_backend_category_writeback.py`:
`DirectBackend._acreate_category`/`_alist_categories`/`_aassign_category` are
driven directly via `asyncio.run` against a fake WS client -- `attempt_
category_writeback` itself calls the plain sync `list_categories`/
`create_category`/`assign_category` methods, so those are monkeypatched here
to their already-tested `_a*` coroutine counterparts (bypassing
`DirectBackend._run`'s background-thread event loop, which this lightweight
harness never spins up)."""

from __future__ import annotations

import asyncio
from typing import Any

from hassle.backend.direct import DirectBackend
from hassle.sync.category_writeback import attempt_category_writeback


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def ws_command(self, type: str, **payload: Any) -> Any:
        self.calls.append((type, payload))
        if type == "config/category_registry/list":
            return []
        if type == "config/category_registry/create":
            return {"category_id": "new_cat", "name": payload["name"], "icon": None}
        if type == "config/entity_registry/list":
            return [
                {
                    "entity_id": "automation.auto_hvac_1",
                    "unique_id": "auto_hvac_1",
                    "categories": {},
                }
            ]
        if type == "config/entity_registry/update":
            return {"entity_id": payload["entity_id"]}
        return []


def _make_backend(client: _FakeClient) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    backend._reload_timeout = 0.05  # type: ignore[attr-defined]
    backend._reload_interval = 0.01  # type: ignore[attr-defined]
    backend.list_categories = lambda scope: asyncio.run(backend._alist_categories(scope))  # type: ignore[method-assign]
    backend.create_category = lambda scope, name: asyncio.run(  # type: ignore[method-assign]
        backend._acreate_category(scope, name)
    )
    backend.assign_category = lambda kind, identity, scope, category_id: asyncio.run(  # type: ignore[method-assign]
        backend._aassign_category(kind, identity, scope, category_id)
    )
    return backend


def test_direct_backend_create_category_payload_uses_category_global_exactly() -> None:
    client = _FakeClient()
    backend = _make_backend(client)

    result = attempt_category_writeback(
        backend,
        "automation",
        "auto_hvac_1",
        "automations/automatic_hvac.py",
        category_override="Automatic HVAC",
    )

    assert result.warning is None
    ((_cmd, create_payload),) = [
        c for c in client.calls if c[0] == "config/category_registry/create"
    ]
    assert create_payload == {"scope": "automation", "name": "Automatic HVAC"}
