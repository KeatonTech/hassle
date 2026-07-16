"""MILESTONES M21 test 2 (unit half) -- `DirectBackend`'s config-entry
group-helper read-back/create/update, verified at the unit level against a
fake `_client` that reproduces the real HA wire shapes docs/ha-api-notes.md
§38 records -- mirrors `test_direct_backend_template_helpers.py` (M10).

**CI-corrected (PR #35, HA stable + dev, §38.1 amended): the group
options-flow schema does NOT include `name`, same as template (§26.7
finding 2).** The original implementation read the owner's live capture note
("options flows re-present the same form ... with current values as
suggested values") as "the exact same schema, `name` included" -- CI found
real HA 400s an options-flow submission that carries `name`
(`{"errors": {"base": ["extra keys not allowed @ data['name']"]}}`), on both
`stable` and `dev`. So, exactly like template's `_aupdate_template_helper`,
`_aupdate_group_helper` strips `name` before submitting to the options flow,
and `_alist_group_helpers`'s read-back gets `name` back from `title` (the
flow's create-time correlator) -- the options-flow's suggested values never
carry it at all.

This suite is unit-level (no network, R2): it monkeypatches
`DirectBackend._client` with a fake object exposing async `ws_command`/
`rest_post`/`rest_delete`, and calls the private async `_alist_group_helpers`/
`_aupdate_group_helper` coroutines directly via `asyncio.run`. The end-to-end
path against real HA is `tests/integration/test_live_group_flow.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError


class _FakeClient:
    """Models the REAL wire shapes docs/ha-api-notes.md §38 records:

    - `config_entries/get` (WS): `ConfigEntry.as_json_fragment`-shaped dicts
      -- `entry_id`/`domain`/`title`/... but never `options`/`data`.
    - `config/entity_registry/list` (WS): rows with `entity_id`/
      `config_entry_id`, used to resolve which of the twelve group flavors an
      entry is (§38.2: the flavor equals the created entity's own domain).
    - `POST /api/config/config_entries/options/flow` (REST): starts an
      options flow, returning a form step whose `data_schema` carries each
      field's current value as `description.suggested_value` -- EXCLUDING
      `name` (CI-corrected, §38.1: same as template).
    - `POST /api/config/config_entries/options/flow/{flow_id}` (REST): the
      form submission. 400s (`HaApiError`) if `name` is among the submitted
      keys, mirroring the real schema rejection.
    - `DELETE /api/config/config_entries/options/flow/{flow_id}` (REST):
      cancels the flow.
    """

    def __init__(self, entries: dict[str, dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        self._entries = entries
        self._entities = entities
        self.rest_calls: list[tuple[str, str, Any]] = []
        self.cancelled_flow_ids: list[str] = []
        self._flow_counter = 0
        self._entry_counter = 0
        self._flows: dict[str, str] = {}

    async def ws_command(self, type: str, **payload: Any) -> Any:
        if type == "config_entries/get":
            return [
                {"entry_id": entry_id, "domain": "group", "title": data["title"]}
                for entry_id, data in self._entries.items()
            ]
        if type == "config/entity_registry/list":
            return self._entities
        raise HaApiError(f"unexpected ws_command {type!r}")

    async def rest_post(self, path: str, json: Any = None, *, expect: str = "json") -> Any:
        self.rest_calls.append(("POST", path, json))
        if path == "/api/config/config_entries/flow":
            self._flow_counter += 1
            flow_id = f"flow_{self._flow_counter}"
            return {
                "type": "menu",
                "flow_id": flow_id,
                "handler": "group",
                "step_id": "user",
                "menu_options": ["binary_sensor", "cover", "light", "sensor", "switch"],
            }
        if path.startswith("/api/config/config_entries/flow/"):
            flow_id = path.rsplit("/", 1)[1]
            if isinstance(json, dict) and "next_step_id" in json:
                return {
                    "type": "form",
                    "flow_id": flow_id,
                    "step_id": json["next_step_id"],
                    "data_schema": [],
                }
            self._entry_counter += 1
            entry_id = f"entry_{self._entry_counter}"
            title = str(json["name"])
            self._entries[entry_id] = {"title": title, "options": dict(json)}
            return {
                "type": "create_entry",
                "flow_id": flow_id,
                "handler": "group",
                "result": {"entry_id": entry_id, "domain": "group", "title": title},
            }
        if path == "/api/config/config_entries/options/flow":
            entry_id = str(json["handler"])
            if entry_id not in self._entries:
                raise HaApiError(f"POST {path}: unknown entry {entry_id}")
            self._flow_counter += 1
            flow_id = f"flow_{self._flow_counter}"
            self._flows[flow_id] = entry_id
            options = self._entries[entry_id]["options"]
            # `name` is NEVER part of the group options-flow schema
            # (CI-corrected, §38.1: same as template, §26.7 finding 2) --
            # excluded from suggested values.
            data_schema = [
                {"name": key, "description": {"suggested_value": value}}
                for key, value in options.items()
                if key != "name"
            ]
            return {
                "type": "form",
                "flow_id": flow_id,
                "step_id": "cover",
                "data_schema": data_schema,
            }
        if path.startswith("/api/config/config_entries/options/flow/"):
            flow_id = path.rsplit("/", 1)[1]
            entry_id = self._flows[flow_id]
            if isinstance(json, dict) and "name" in json:
                raise HaApiError(
                    f"HA returned 400 for POST {path}: "
                    '{"errors":{"base":["extra keys not allowed @ data[\'name\']"]}}'
                )
            # Merge (not replace) -- mirrors real HA keeping `name` untouched
            # across an update that never resubmits it (§38.1, CI-corrected).
            self._entries[entry_id]["options"] = {
                **self._entries[entry_id]["options"],
                **(json or {}),
            }
            return {"type": "create_entry", "flow_id": flow_id, "result": {}}
        raise HaApiError(f"unexpected rest_post {path!r}")

    async def rest_delete(self, path: str) -> Any:
        self.rest_calls.append(("DELETE", path, None))
        if path.startswith("/api/config/config_entries/options/flow/"):
            flow_id = path.rsplit("/", 1)[1]
            self.cancelled_flow_ids.append(flow_id)
            return {"message": "Flow aborted"}
        if path.startswith("/api/config/config_entries/entry/"):
            entry_id = path.rsplit("/", 1)[1]
            self._entries.pop(entry_id, None)
            return {"require_restart": False}
        raise HaApiError(f"unexpected rest_delete {path!r}")


def _make_backend(client: _FakeClient) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    backend._group_entry_ids = {}  # type: ignore[attr-defined]
    return backend


def test_create_group_helper_extracts_entry_id_from_nested_result_key() -> None:
    client = _FakeClient(entries={}, entities=[])
    backend = _make_backend(client)

    identity = asyncio.run(
        backend._acreate_group_helper(  # type: ignore[attr-defined]
            "group_cover",
            {"name": "Entryway Top", "entities": ["cover.a", "cover.b"], "hide_members": False},
        )
    )

    assert identity == "entryway_top"
    cached_entry_id = backend._group_entry_ids[("group_cover", "entryway_top")]  # type: ignore[attr-defined]
    assert cached_entry_id == "entry_1"
    assert not cached_entry_id.startswith("flow_")


def test_create_group_sensor_missing_type_raises_before_any_wire_call() -> None:
    client = _FakeClient(entries={}, entities=[])
    backend = _make_backend(client)

    with pytest.raises(ValueError, match="type"):
        asyncio.run(
            backend._acreate_group_helper(  # type: ignore[attr-defined]
                "group_sensor",
                {"name": "No Type", "entities": ["sensor.a"], "hide_members": False},
            )
        )
    assert client.rest_calls == []


def test_list_remote_reads_back_name_and_options_via_options_flow_suggested_values() -> None:
    client = _FakeClient(
        entries={
            "entry_1": {
                "title": "Entryway Top",
                "options": {
                    "name": "Entryway Top",
                    "entities": ["cover.a", "cover.b"],
                    "hide_members": False,
                },
            }
        },
        entities=[{"entity_id": "cover.entryway_top", "config_entry_id": "entry_1"}],
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_group_helpers("group_cover"))  # type: ignore[attr-defined]

    assert "entryway_top" in result
    stored = result["entryway_top"]
    assert stored["name"] == "Entryway Top"
    assert stored["entities"] == ["cover.a", "cover.b"]
    assert stored["hide_members"] is False

    assert client.cancelled_flow_ids == ["flow_1"]


def test_list_remote_ignores_entries_of_a_different_group_flavor() -> None:
    client = _FakeClient(
        entries={
            "entry_1": {
                "title": "A Cover Group",
                "options": {
                    "name": "A Cover Group",
                    "entities": ["cover.a"],
                    "hide_members": False,
                },
            },
            "entry_2": {
                "title": "A Light Group",
                "options": {
                    "name": "A Light Group",
                    "entities": ["light.a"],
                    "hide_members": False,
                },
            },
        },
        entities=[
            {"entity_id": "cover.a_cover_group", "config_entry_id": "entry_1"},
            {"entity_id": "light.a_light_group", "config_entry_id": "entry_2"},
        ],
    )
    backend = _make_backend(client)

    covers = asyncio.run(backend._alist_group_helpers("group_cover"))  # type: ignore[attr-defined]
    assert set(covers) == {"a_cover_group"}


def test_update_strips_name_before_submitting_to_options_flow() -> None:
    # CI-corrected (PR #35, docs/ha-api-notes.md §38.1 amended): the group
    # options-flow schema does NOT include `name` -- `update()` still takes
    # a full config dict (F2 unchanged) but must never forward `name` to the
    # options-flow submission.
    client = _FakeClient(
        entries={
            "entry_1": {
                "title": "Top",
                "options": {"name": "Top", "entities": ["cover.a"], "hide_members": False},
            }
        },
        entities=[{"entity_id": "cover.top", "config_entry_id": "entry_1"}],
    )
    backend = _make_backend(client)
    backend._group_entry_ids[("group_cover", "top")] = "entry_1"  # type: ignore[attr-defined]

    asyncio.run(
        backend._aupdate_group_helper(  # type: ignore[attr-defined]
            "group_cover",
            "top",
            {"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True},
        )
    )

    form_submission = next(
        json
        for method, path, json in client.rest_calls
        if method == "POST" and path == "/api/config/config_entries/options/flow/flow_1"
    )
    assert "name" not in form_submission
    assert form_submission["entities"] == ["cover.a", "cover.b"]

    # `name` survives untouched, never having been resubmitted.
    assert client._entries["entry_1"]["options"]["name"] == "Top"
    assert client._entries["entry_1"]["options"]["hide_members"] is True


def test_update_missing_required_field_still_checked_before_any_wire_call() -> None:
    client = _FakeClient(entries={}, entities=[])
    backend = _make_backend(client)
    backend._group_entry_ids[("group_sensor", "avg")] = "entry_1"  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="type"):
        asyncio.run(
            backend._aupdate_group_helper(  # type: ignore[attr-defined]
                "group_sensor",
                "avg",
                {"name": "Avg", "entities": ["sensor.a"], "hide_members": False},
            )
        )
    assert client.rest_calls == []


def test_delete_removes_entry_and_is_idempotent() -> None:
    client = _FakeClient(
        entries={
            "entry_1": {
                "title": "Top",
                "options": {"name": "Top", "entities": ["cover.a"], "hide_members": False},
            }
        },
        entities=[{"entity_id": "cover.top", "config_entry_id": "entry_1"}],
    )
    backend = _make_backend(client)
    backend._group_entry_ids[("group_cover", "top")] = "entry_1"  # type: ignore[attr-defined]

    asyncio.run(backend._adelete_group_helper("group_cover", "top"))  # type: ignore[attr-defined]
    assert ("group_cover", "top") not in backend._group_entry_ids  # type: ignore[attr-defined]

    # Idempotent -- deleting again (already gone) does not raise.
    asyncio.run(backend._adelete_group_helper("group_cover", "top"))  # type: ignore[attr-defined]
