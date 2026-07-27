"""`DirectBackend`'s dashboard-kind dispatch (docs/internals/dashboards-design.md
§4.1), verified at the unit level against a fake `_client` exposing async
`ws_command` only -- unlike the config-entry helper families, every dashboard
command in §2.2's table is WebSocket, never REST.

Mapping under test:

- `list_remote`: `lovelace/dashboards/list` -> for each registry item (and the
  default) `lovelace/config` -> composed `{"meta": ..., "config": ...}`
  envelopes. A `config_not_found` error omits that dashboard entirely (the
  never-customized-default case, §2.1). YAML-mode items (`mode != "storage"`)
  are filtered out (I1: not ours to manage).
- `create`: non-default -> `lovelace/dashboards/create` then
  `lovelace/config/save`; default (`meta: null`) -> `config/save(url_path=null)`
  only, no registry call at all.
- **Partial-create rollback** (§4.1): if `config/save` fails after
  `dashboards/create` succeeded, the just-created registry item is deleted
  before the original error is re-raised.
- `update`: `lovelace/dashboards/update` (dashboard_id resolved from
  `url_path` via `dashboards/list`, cached per connection) and/or
  `lovelace/config/save`.
- `delete`: non-default -> `lovelace/dashboards/delete`; default ->
  `lovelace/config/delete`.

This suite is unit-level (no network), mirroring
`test_direct_backend_group_helpers.py`'s pattern. The end-to-end path against
real HA is `tests/integration/test_live_dashboard_crud.py` (integration-only,
DB0-pending).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError


class _FakeClient:
    """Models the WS shapes docs/internals/dashboards-design.md §2.2 records:

    - `lovelace/dashboards/list` (WS): registry items, `{id, url_path, title,
      icon, show_in_sidebar, require_admin, mode}`.
    - `lovelace/config` (WS): `{url_path | null, force?}` -> the view config,
      or a `config_not_found`-coded `HaApiError` if never saved.
    - `lovelace/config/save` (WS): `{url_path | null, config}`.
    - `lovelace/config/delete` (WS): `{url_path | null}` -- reverts to
      auto-generated.
    - `lovelace/dashboards/create` (WS): `{url_path, title, icon?,
      show_in_sidebar?, require_admin?, mode: "storage"}` -> `{id: ...}`.
    - `lovelace/dashboards/update` / `lovelace/dashboards/delete` (WS):
      `{dashboard_id, ...}`.
    """

    def __init__(
        self,
        dashboards: dict[str, dict[str, Any]] | None = None,
        configs: dict[str, Any] | None = None,
    ) -> None:
        # dashboard_id -> registry item (incl. "id"/"mode").
        self.dashboards: dict[str, dict[str, Any]] = dashboards or {}
        # url_path (None spelled as the string sentinel "__default__") -> config.
        self.configs: dict[str, Any] = configs or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._id_counter = 0
        self.fail_config_save = False

    def _config_key(self, url_path: str | None) -> str:
        return "__default__" if url_path is None else url_path

    async def ws_command(self, type: str, **payload: Any) -> Any:
        self.calls.append((type, payload))
        if type == "lovelace/dashboards/list":
            return list(self.dashboards.values())
        if type == "lovelace/config":
            key = self._config_key(payload.get("url_path"))
            if key not in self.configs:
                raise HaApiError("Config not found", code="config_not_found")
            return self.configs[key]
        if type == "lovelace/config/save":
            if self.fail_config_save:
                raise HaApiError("failed to save config", code="unknown_error")
            key = self._config_key(payload.get("url_path"))
            self.configs[key] = payload["config"]
            return {}
        if type == "lovelace/config/delete":
            key = self._config_key(payload.get("url_path"))
            self.configs.pop(key, None)
            return {}
        if type == "lovelace/dashboards/create":
            self._id_counter += 1
            dashboard_id = f"dash_{self._id_counter}"
            item = {"id": dashboard_id, "mode": "storage", **payload}
            self.dashboards[dashboard_id] = item
            return {"id": dashboard_id}
        if type == "lovelace/dashboards/update":
            dashboard_id = str(payload["dashboard_id"])
            item = self.dashboards[dashboard_id]
            for k, v in payload.items():
                if k != "dashboard_id":
                    item[k] = v
            return {}
        if type == "lovelace/dashboards/delete":
            dashboard_id = str(payload["dashboard_id"])
            self.dashboards.pop(dashboard_id, None)
            return {}
        raise HaApiError(f"unexpected ws_command {type!r}")


def _make_backend(client: _FakeClient) -> DirectBackend:
    backend = DirectBackend.__new__(DirectBackend)
    backend._client = client  # type: ignore[attr-defined]
    backend._dashboard_ids = {}  # type: ignore[attr-defined]
    return backend


# -- list_remote --------------------------------------------------------------


def test_list_remote_composes_envelope_from_registry_and_config() -> None:
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "icon": "mdi:thermostat",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            }
        },
        configs={"climate-control": {"views": [{"title": "Overview"}]}},
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]

    assert set(result) == {"climate-control"}
    envelope = result["climate-control"]
    assert envelope["meta"]["title"] == "Climate"
    assert envelope["meta"]["url_path"] == "climate-control"
    assert "id" not in envelope["meta"]
    assert "mode" not in envelope["meta"]
    assert envelope["config"] == {"views": [{"title": "Overview"}]}


def test_list_remote_omits_dashboard_with_config_not_found() -> None:
    # A registry item with no saved config yet -- HA's config_not_found is
    # the analogue of "absent from list_remote" (§2.1).
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "never-saved",
                "title": "Never Saved",
                "mode": "storage",
            }
        },
        configs={},
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]
    assert "never-saved" not in result


def test_list_remote_filters_yaml_mode_dashboards() -> None:
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "yaml-one",
                "title": "YAML",
                "mode": "yaml",
            }
        },
        configs={"yaml-one": {"views": []}},
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]
    assert "yaml-one" not in result


def test_list_remote_includes_default_dashboard_with_null_meta() -> None:
    client = _FakeClient(dashboards={}, configs={"__default__": {"views": [{"title": "Home"}]}})
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]
    assert result["default"]["meta"] is None
    assert result["default"]["config"] == {"views": [{"title": "Home"}]}


def test_list_remote_omits_default_when_never_saved() -> None:
    client = _FakeClient(dashboards={}, configs={})
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]
    assert "default" not in result


# -- create -------------------------------------------------------------------


def test_create_non_default_calls_dashboards_create_then_config_save() -> None:
    client = _FakeClient()
    backend = _make_backend(client)

    identity = asyncio.run(
        backend._acreate_dashboard(  # type: ignore[attr-defined]
            {
                "meta": {"url_path": "climate-control", "title": "Climate", "icon": "mdi:fire"},
                "config": {"views": [{"title": "Overview"}]},
            }
        )
    )

    assert identity == "climate-control"
    call_types = [call for call, _ in client.calls]
    assert "lovelace/dashboards/create" in call_types
    assert "lovelace/config/save" in call_types
    create_payload = next(p for t, p in client.calls if t == "lovelace/dashboards/create")
    assert create_payload["url_path"] == "climate-control"
    assert create_payload["mode"] == "storage"
    save_payload = next(p for t, p in client.calls if t == "lovelace/config/save")
    assert save_payload["url_path"] == "climate-control"
    assert save_payload["config"] == {"views": [{"title": "Overview"}]}


def test_create_default_only_calls_config_save() -> None:
    client = _FakeClient()
    backend = _make_backend(client)

    identity = asyncio.run(
        backend._acreate_dashboard(  # type: ignore[attr-defined]
            {"meta": None, "config": {"views": [{"title": "Home"}]}}
        )
    )

    assert identity == "default"
    call_types = [call for call, _ in client.calls]
    assert "lovelace/dashboards/create" not in call_types
    assert call_types == ["lovelace/config/save"]
    save_payload = client.calls[0][1]
    assert save_payload["url_path"] is None


def test_create_partial_failure_rolls_back_registry_item() -> None:
    client = _FakeClient()
    client.fail_config_save = True
    backend = _make_backend(client)

    with pytest.raises(HaApiError):
        asyncio.run(
            backend._acreate_dashboard(  # type: ignore[attr-defined]
                {
                    "meta": {"url_path": "climate-control", "title": "Climate"},
                    "config": {"views": []},
                }
            )
        )

    # The registry item created before the failed config/save must be gone.
    assert client.dashboards == {}
    call_types = [call for call, _ in client.calls]
    assert "lovelace/dashboards/create" in call_types
    assert "lovelace/dashboards/delete" in call_types
    # And the internal id cache must not retain the rolled-back identity.
    assert ("climate-control") not in backend._dashboard_ids  # type: ignore[attr-defined]


# -- update ---------------------------------------------------------------------


def test_update_resolves_dashboard_id_and_calls_update_and_save() -> None:
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "mode": "storage",
            }
        },
        configs={"climate-control": {"views": []}},
    )
    backend = _make_backend(client)

    asyncio.run(
        backend._aupdate_dashboard(  # type: ignore[attr-defined]
            "climate-control",
            {
                "meta": {"url_path": "climate-control", "title": "Climate V2"},
                "config": {"views": [{"title": "New"}]},
            },
        )
    )

    update_payload = next(p for t, p in client.calls if t == "lovelace/dashboards/update")
    assert update_payload["dashboard_id"] == "dash_1"
    assert update_payload["title"] == "Climate V2"
    save_payload = next(p for t, p in client.calls if t == "lovelace/config/save")
    assert save_payload["url_path"] == "climate-control"
    assert save_payload["config"] == {"views": [{"title": "New"}]}


def test_update_caches_dashboard_id_across_calls() -> None:
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "mode": "storage",
            }
        },
        configs={"climate-control": {"views": []}},
    )
    backend = _make_backend(client)
    backend._dashboard_ids["climate-control"] = "dash_1"  # type: ignore[attr-defined]

    asyncio.run(
        backend._aupdate_dashboard(  # type: ignore[attr-defined]
            "climate-control",
            {"meta": {"url_path": "climate-control", "title": "V2"}, "config": {"views": []}},
        )
    )

    call_types = [call for call, _ in client.calls]
    assert "lovelace/dashboards/list" not in call_types


def test_update_default_dashboard_only_saves_config() -> None:
    client = _FakeClient(dashboards={}, configs={"__default__": {"views": []}})
    backend = _make_backend(client)

    asyncio.run(
        backend._aupdate_dashboard(  # type: ignore[attr-defined]
            "default", {"meta": None, "config": {"views": [{"title": "New Home"}]}}
        )
    )

    call_types = [call for call, _ in client.calls]
    assert "lovelace/dashboards/update" not in call_types
    assert call_types == ["lovelace/config/save"]
    save_payload = client.calls[0][1]
    assert save_payload["url_path"] is None


# -- delete -----------------------------------------------------------------


def test_delete_non_default_calls_dashboards_delete() -> None:
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "mode": "storage",
            }
        },
        configs={"climate-control": {"views": []}},
    )
    backend = _make_backend(client)

    asyncio.run(backend._adelete_dashboard("climate-control"))  # type: ignore[attr-defined]

    delete_payload = next(p for t, p in client.calls if t == "lovelace/dashboards/delete")
    assert delete_payload["dashboard_id"] == "dash_1"
    assert "climate-control" not in backend._dashboard_ids  # type: ignore[attr-defined]


def test_delete_default_calls_config_delete() -> None:
    client = _FakeClient(dashboards={}, configs={"__default__": {"views": []}})
    backend = _make_backend(client)

    asyncio.run(backend._adelete_dashboard("default"))  # type: ignore[attr-defined]

    call_types = [call for call, _ in client.calls]
    assert call_types == ["lovelace/config/delete"]
    assert client.calls[0][1]["url_path"] is None


# -- explicit-fallthrough guard (docs/internals/dashboards-design.md §4.1 last bullet) --


def test_alist_helpers_asserts_kind_is_a_helper_domain() -> None:
    """Regression for the DB1 review finding: kind registration and
    DirectBackend support must be inseparable -- an unregistered kind must
    fail loudly at the dispatch layer (an `AssertionError` naming the kind),
    never send a nonexistent `<kind>/list` WS command."""
    client = _FakeClient()
    backend = _make_backend(client)

    with pytest.raises(AssertionError):
        asyncio.run(backend._alist_helpers("dashboard"))  # type: ignore[attr-defined]
    assert client.calls == []
