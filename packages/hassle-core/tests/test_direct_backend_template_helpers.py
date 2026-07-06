"""MILESTONES M10 test 1 (round-3 CI regression) — `DirectBackend`'s
config-entry template-helper read-back/update, verified at the unit level
against a fake `_client` that faithfully reproduces the real HA wire shapes
CI round 3 uncovered (docs/ha-api-notes.md §26.7):

- `config_entries/get` (WS) never carries an entry's options at all --
  `ConfigEntry.as_json_fragment` has no `options`/`data` key
  (`homeassistant/config_entries.py`). The round-2 code assumed
  `entry.get("options", {})` would have the submitted fields; it never does
  against real HA, producing `KeyError: 'name'` / `KeyError: 'state'` on
  read-back (CI round 3, `test_m10_template_flow.py`).
- The options-flow's first form step is the only place options ever appear
  on the wire, as `data_schema` entries' `description.suggested_value`
  (mirrors what the UI's edit dialog itself reads to pre-populate its form,
  I1).
- The options-flow schema never includes `name` for any template domain
  (`generate_schema(domain, flow_type="options")` never adds it) -- an
  UPDATE that resubmits `name` gets `400 {"errors": {"base": ["extra keys
  not allowed @ data['name']"]}}` from real HA (CI round 3).

This suite is unit-level (no network, R2): it monkeypatches
`DirectBackend._client` with a fake object exposing async `ws_command`/
`rest_post`/`rest_delete`, and calls the private async `_alist_template_
helpers`/`_aupdate_template_helper` coroutines directly via `asyncio.run` --
same pattern as `test_direct_backend_categories.py`. The end-to-end path
against real HA is `test_m10_template_flow.py` (integration-only).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError

_SET_VALUE = {"action": "input_number.set_value", "data": {"value": "{{ value }}"}}


class _FakeClient:
    """Models the REAL wire shapes docs/ha-api-notes.md §26/§26.7 record:

    - `config_entries/get` (WS): returns `ConfigEntry.as_json_fragment`-shaped
      dicts -- `entry_id`/`domain`/`title`/... but NEVER `options`/`data`.
    - `config/entity_registry/list` (WS): rows with `entity_id`/
      `config_entry_id`, used to resolve which of the 4 template sub-kinds an
      entry is.
    - `POST /api/config/config_entries/options/flow` (REST): starts an
      options flow, returning a form step whose `data_schema` carries each
      field's current value as `description.suggested_value` -- the ONLY
      place options appear on the wire (§26.7).
    - `POST /api/config/config_entries/options/flow/{flow_id}` (REST): the
      form submission. 400s (`HaApiError`) if `name` is among the submitted
      keys, mirroring the real schema rejection.
    - `DELETE /api/config/config_entries/options/flow/{flow_id}` (REST):
      cancels the flow (what read-back must do after harvesting suggested
      values, so as not to leave a flow needlessly in progress).
    """

    def __init__(self, entries: dict[str, dict[str, Any]], entities: list[dict[str, Any]]) -> None:
        # entry_id -> {"title": ..., "options": {...}} (the TRUE server-side
        # state; "options" is never exposed via config_entries/get, only via
        # an options-flow's suggested values).
        self._entries = entries
        self._entities = entities
        self.rest_calls: list[tuple[str, str, Any]] = []
        self.cancelled_flow_ids: list[str] = []
        self._flow_counter = 0
        self._flows: dict[str, str] = {}  # flow_id -> entry_id

    async def ws_command(self, type: str, **payload: Any) -> Any:
        if type == "config_entries/get":
            return [
                {
                    "entry_id": entry_id,
                    "domain": "template",
                    "title": data["title"],
                }
                for entry_id, data in self._entries.items()
            ]
        if type == "config/entity_registry/list":
            return self._entities
        raise HaApiError(f"unexpected ws_command {type!r}")

    async def rest_post(self, path: str, json: Any = None, *, expect: str = "json") -> Any:
        self.rest_calls.append(("POST", path, json))
        if path == "/api/config/config_entries/options/flow":
            entry_id = str(json["handler"])
            if entry_id not in self._entries:
                raise HaApiError(f"POST {path}: unknown entry {entry_id}")
            self._flow_counter += 1
            flow_id = f"flow_{self._flow_counter}"
            self._flows[flow_id] = entry_id
            options = self._entries[entry_id]["options"]
            data_schema = [
                {"name": key, "description": {"suggested_value": value}}
                for key, value in options.items()
                # The options-flow schema never includes `name` (§26.7
                # finding 2) -- it is create-only, derived into `title`.
                if key != "name"
            ]
            return {
                "type": "form",
                "flow_id": flow_id,
                "step_id": "number",
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
            # Merge (not replace) -- mirrors real HA keeping name/template_type
            # untouched across an update that never resubmits them (§26.7
            # finding 3).
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
        raise HaApiError(f"unexpected rest_delete {path!r}")


def _make_backend(client: _FakeClient) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    backend._template_entry_ids = {}  # type: ignore[attr-defined]
    return backend


def test_list_remote_reads_back_name_and_options_via_options_flow_suggested_values() -> None:
    # Regression for CI round 3's `KeyError: 'name'` / `KeyError: 'state'`:
    # `config_entries/get` alone never has enough to reconstruct the stored
    # config (docs/ha-api-notes.md §26.7).
    client = _FakeClient(
        entries={
            "entry_1": {
                "title": "Active HVAC Zones",
                "options": {
                    "name": "Active HVAC Zones",
                    "template_type": "number",
                    "state": "{{ 3 }}",
                    "min": 0,
                    "max": 8,
                    "set_value": _SET_VALUE,
                },
            }
        },
        entities=[{"entity_id": "number.active_hvac_zones", "config_entry_id": "entry_1"}],
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_template_helpers("template_number"))  # type: ignore[attr-defined]

    assert "active_hvac_zones" in result
    stored = result["active_hvac_zones"]
    assert stored["name"] == "Active HVAC Zones"
    assert stored["state"] == "{{ 3 }}"
    assert stored["min"] == 0
    assert stored["max"] == 8

    # Read-back must not leave the options flow open (mirrors closing the
    # UI's edit dialog without saving).
    assert client.cancelled_flow_ids == ["flow_1"]


def test_list_remote_ignores_entries_of_a_different_template_sub_kind() -> None:
    client = _FakeClient(
        entries={
            "entry_1": {"title": "A Number", "options": {"name": "A Number", "state": "{{ 1 }}"}},
            "entry_2": {"title": "A Sensor", "options": {"name": "A Sensor", "state": "{{ 1 }}"}},
        },
        entities=[
            {"entity_id": "number.a_number", "config_entry_id": "entry_1"},
            {"entity_id": "sensor.a_sensor", "config_entry_id": "entry_2"},
        ],
    )
    backend = _make_backend(client)

    numbers = asyncio.run(backend._alist_template_helpers("template_number"))  # type: ignore[attr-defined]
    assert set(numbers) == {"a_number"}


def test_update_strips_name_before_submitting_to_options_flow() -> None:
    # Regression for CI round 3's 400: `"extra keys not allowed @
    # data['name']"`. update() still takes a full config dict (F2 unchanged)
    # but must never forward `name` to the options-flow submission.
    client = _FakeClient(
        entries={
            "entry_1": {
                "title": "Zones",
                "options": {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE},
            }
        },
        entities=[{"entity_id": "number.zones", "config_entry_id": "entry_1"}],
    )
    backend = _make_backend(client)
    backend._template_entry_ids[("template_number", "zones")] = "entry_1"  # type: ignore[attr-defined]

    asyncio.run(
        backend._aupdate_template_helper(  # type: ignore[attr-defined]
            "template_number",
            "zones",
            {"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE},
        )
    )

    # The submitted body to the options-flow's form step must not contain `name`.
    form_submission = next(
        json
        for method, path, json in client.rest_calls
        if method == "POST" and path == "/api/config/config_entries/options/flow/flow_1"
    )
    assert "name" not in form_submission
    assert form_submission["state"] == "{{ 2 }}"

    # `name` survives untouched, never having been resubmitted (§26.7 finding 3).
    assert client._entries["entry_1"]["options"]["name"] == "Zones"


def test_update_missing_required_field_still_checked_before_any_wire_call() -> None:
    client = _FakeClient(entries={}, entities=[])
    backend = _make_backend(client)
    backend._template_entry_ids[("template_number", "zones")] = "entry_1"  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="set_value"):
        asyncio.run(
            backend._aupdate_template_helper(  # type: ignore[attr-defined]
                "template_number", "zones", {"name": "Zones", "state": "{{ 2 }}"}
            )
        )
    # Never even reached the wire (fails fast, before any wasted round-trip).
    assert client.rest_calls == []
