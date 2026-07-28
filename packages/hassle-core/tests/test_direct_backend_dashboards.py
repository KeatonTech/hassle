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
  `url_path` via `dashboards/list`, cached per connection) sends the FULL
  desired state of exactly `{title, icon, show_in_sidebar, require_admin}`
  -- built from an explicit allowlist, NEVER from `meta`'s own keys, and
  NEVER including `url_path` (HA's real update schema is PREVENT_EXTRA over
  those four fields; `url_path` is deliberately excluded, since a url_path
  change is delete+create, never an in-place rename, I2). Full-state (never
  presence-based) because HA's storage collection MERGES
  (`{**item, **update}`) rather than replacing the item outright, so a
  field only clears when explicitly sent (e.g. `icon: None`) -- see the
  2026-07-27 implementation-finding note in docs/internals/
  dashboards-design.md §4.1. `lovelace/config/save` follows for `config`.
- `delete`: non-default -> `lovelace/dashboards/delete`; default ->
  `lovelace/config/delete`.

This suite is unit-level (no network), mirroring
`test_direct_backend_group_helpers.py`'s pattern. The end-to-end path against
real HA is `tests/integration/test_live_dashboard_crud.py` (integration-only;
DB0 ran it green against HA 2026.7.4 -- ha-api-notes §39.1-§39.8).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError, HaConnectionError

# The registry item's four mutable fields (docs/internals/dashboards-design.md
# §2.2/§4.1) -- HA's real `lovelace/dashboards/update` schema is PREVENT_EXTRA
# over exactly these; `url_path`/`id`/`mode` are never accepted.
_DASHBOARD_UPDATE_FIELDS = frozenset({"title", "icon", "show_in_sidebar", "require_admin"})


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
        # Fidelity with real HA (docs/internals/ha-api-notes.md §39.2, DB0
        # capture `config_null_after_restart`): `lovelace/config`'s handler is
        # `dashboards.get("lovelace") or dashboards[None]` -- when a registry
        # item with url_path "lovelace" exists, `url_path=null` is an ALIAS
        # for THAT dashboard, not a separate store. Modelling this is what
        # makes the double-adoption bug visible to a unit test.
        if url_path is None and any(
            item.get("url_path") == "lovelace" for item in self.dashboards.values()
        ):
            return "lovelace"
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
            fields = {k: v for k, v in payload.items() if k != "dashboard_id"}
            # PREVENT_EXTRA over exactly the four mutable registry fields --
            # `url_path` (rename is delete+create, never in-place) and any
            # other unknown key are real HA rejections (`invalid_format`),
            # not silently accepted. This is the schema-fidelity fix for the
            # BLOCKER finding: the old permissive fake accepted arbitrary
            # keys (including `url_path`), which is why the buggy
            # `_aupdate_dashboard` implementation (forwarding `meta`'s own
            # keys wholesale) went undetected by 30 green tests.
            if "url_path" in fields:
                raise HaApiError(
                    "extra keys not allowed @ data['url_path'] (url_path is not a "
                    "mutable registry field on lovelace/dashboards/update -- a "
                    "url_path change is delete+create, never an in-place rename)",
                    code="invalid_format",
                )
            unknown = set(fields) - _DASHBOARD_UPDATE_FIELDS
            if unknown:
                raise HaApiError(
                    f"extra keys not allowed: {sorted(unknown)}", code="invalid_format"
                )
            item = self.dashboards[dashboard_id]
            # Real HA's storage collection MERGES ({**item, **update})
            # rather than replacing the item outright -- a field only
            # clears when explicitly sent (e.g. icon: None).
            item.update(fields)
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


def test_list_remote_propagates_non_config_not_found_ha_api_error() -> None:
    """Should-fix 2 regression: `_afetch_dashboard_config` must only ever
    swallow `config_not_found` -- a WIDER `except HaApiError` (that also
    catches, say, a transient server error) would silently turn it into
    "dashboard missing from list_remote", which the planner reads as
    remote-deleted -> an I6-shaped false drop/conflict. Pins the CURRENT
    (correct) narrow catch against ever silently widening."""

    class _FailingConfigClient(_FakeClient):
        async def ws_command(self, type: str, **payload: Any) -> Any:
            if type == "lovelace/config" and payload.get("url_path") == "climate-control":
                raise HaApiError("transient failure", code="unknown_error")
            return await super().ws_command(type, **payload)

    client = _FailingConfigClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "mode": "storage",
            }
        },
        configs={},
    )
    backend = _make_backend(client)

    with pytest.raises(HaApiError, match="transient failure"):
        asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]


def test_list_remote_propagates_connection_error() -> None:
    """Should-fix 2 regression: a connection-level failure (never HA-coded,
    so never mistakable for `config_not_found`) must propagate out of
    `list_remote` rather than being absorbed into "no dashboards"."""

    class _ConnDropClient(_FakeClient):
        async def ws_command(self, type: str, **payload: Any) -> Any:
            if type == "lovelace/config":
                raise HaConnectionError("socket dropped mid-fetch")
            return await super().ws_command(type, **payload)

    client = _ConnDropClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "mode": "storage",
            }
        },
        configs={},
    )
    backend = _make_backend(client)

    with pytest.raises(HaConnectionError):
        asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]


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
    # `config/save` is the only WRITE. The read that precedes it is the
    # migrated-default guard (ha-api-notes §39.2): on an instance where HA has
    # already moved the default dashboard to `url_path: "lovelace"`, saving
    # through `url_path=null` would overwrite it, so the registry is checked
    # first. Here there is no such item, so the save proceeds.
    assert call_types == ["lovelace/dashboards/list", "lovelace/config/save"]
    save_payload = client.calls[-1][1]
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


def test_update_sends_full_allowlisted_registry_state_never_url_path() -> None:
    """BLOCKER regression: the payload must be built from an explicit
    allowlist of the four mutable registry fields, NEVER from `meta`'s own
    keys -- `meta` always carries `url_path` too, and forwarding it verbatim
    would 400 against real HA (`invalid_format`, since a url_path change is
    delete+create, never an in-place rename). Also pins should-fix 1 (full
    desired state, not presence-based): `icon` absent from the local `meta`
    must still be sent explicitly as `None` (clearing it), and
    `show_in_sidebar`/`require_admin` must be sent with their source-informed
    defaults (True/False) rather than omitted."""
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "icon": "mdi:fire",
                "show_in_sidebar": True,
                "require_admin": False,
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
                # No icon/show_in_sidebar/require_admin -- the caller's
                # local `meta` only ever carries what the DSL declared.
                "meta": {"url_path": "climate-control", "title": "Climate V2"},
                "config": {"views": [{"title": "New"}]},
            },
        )
    )

    update_payload = next(p for t, p in client.calls if t == "lovelace/dashboards/update")
    assert update_payload["dashboard_id"] == "dash_1"
    assert update_payload["title"] == "Climate V2"
    # BLOCKER: url_path must never be forwarded (the fake client would raise
    # HaApiError if it were, catching a regression at the schema level too).
    assert "url_path" not in update_payload
    assert set(update_payload) == {
        "dashboard_id",
        "title",
        "icon",
        "show_in_sidebar",
        "require_admin",
    }
    # Should-fix 1: full desired state, not presence-based.
    assert update_payload["icon"] is None
    assert update_payload["show_in_sidebar"] is True
    assert update_payload["require_admin"] is False

    save_payload = next(p for t, p in client.calls if t == "lovelace/config/save")
    assert save_payload["url_path"] == "climate-control"
    assert save_payload["config"] == {"views": [{"title": "New"}]}


def test_update_clears_icon_when_locally_deleted() -> None:
    """Should-fix 1, end to end: an icon set remotely but absent from the
    local edit must actually clear -- convergent full-state update, not a
    silent no-op that would re-plan the same update forever."""
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
        configs={"climate-control": {"views": []}},
    )
    backend = _make_backend(client)

    asyncio.run(
        backend._aupdate_dashboard(  # type: ignore[attr-defined]
            "climate-control",
            {
                "meta": {"url_path": "climate-control", "title": "Climate"},
                "config": {"views": []},
            },
        )
    )

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]
    assert result["climate-control"]["meta"]["icon"] is None


def test_update_rejects_meta_missing_title() -> None:
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

    with pytest.raises(ValueError, match="title"):
        asyncio.run(
            backend._aupdate_dashboard(  # type: ignore[attr-defined]
                "climate-control",
                {"meta": {"url_path": "climate-control"}, "config": {"views": []}},
            )
        )


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


# -- DB0 live findings (docs/internals/ha-api-notes.md §39.2/§39.3) -----------
#
# Both regressions below were found by running the DB0 runbook against a live
# HA 2026.7.4 and are recorded, with captures, in ha-api-notes.md §39.


def test_list_remote_does_not_double_adopt_the_migrated_default_dashboard() -> None:
    """§39.2 (BLOCKER): HA 2026.x migrates the legacy default dashboard
    (`.storage/lovelace`) into a REAL registry item with `url_path:
    "lovelace"`, and `lovelace/config(url_path=null)` keeps serving that same
    dashboard. `_alist_dashboards` must therefore NOT also emit its synthetic
    `"default"` entry: one HA dashboard would become two Hassle objects that
    silently overwrite each other's config on every push.
    """
    client = _FakeClient(
        dashboards={
            "lovelace": {
                "id": "lovelace",
                "url_path": "lovelace",
                "title": "Overview",
                "icon": "mdi:view-dashboard",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            }
        },
        configs={"lovelace": {"views": [{"title": "Legacy Default"}]}},
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]

    assert set(result) == {"lovelace"}
    assert "default" not in result
    assert result["lovelace"]["config"] == {"views": [{"title": "Legacy Default"}]}


def test_list_remote_skips_default_probe_for_a_yaml_mode_lovelace_item() -> None:
    """§39.2 (invariant I1): with `lovelace: mode: yaml`, the default
    dashboard appears in `dashboards/list` as a `mode: "yaml"` item at
    `url_path: "lovelace"` AND `lovelace/config(url_path=null)` serves
    ui-lovelace.yaml's content. The mode filter alone does not save us -- the
    separate default probe would adopt a YAML-mode dashboard Hassle must never
    manage.
    """
    client = _FakeClient(
        dashboards={
            "__yaml__": {
                "url_path": "lovelace",
                "title": "Overview",
                "icon": "mdi:view-dashboard",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "yaml",
                "filename": "ui-lovelace.yaml",
            }
        },
        configs={"lovelace": {"title": "YAML Home", "views": [{"title": "YAML View"}]}},
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]

    assert result == {}


def test_list_remote_still_probes_the_default_when_no_lovelace_item_exists() -> None:
    """The pre-migration shape stays supported: no `lovelace` registry item
    means `url_path=null` really is its own store (§2.1's original reading).
    """
    client = _FakeClient(
        dashboards={
            "dash_1": {
                "id": "dash_1",
                "url_path": "climate-control",
                "title": "Climate",
                "mode": "storage",
            }
        },
        configs={
            "climate-control": {"views": []},
            "__default__": {"views": [{"title": "Home"}]},
        },
    )
    backend = _make_backend(client)

    result = asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]

    assert set(result) == {"climate-control", "default"}
    assert result["default"]["meta"] is None


def test_create_default_dashboard_refuses_when_a_lovelace_item_exists() -> None:
    """§39.2, second order: on a migrated instance a bundle still spelling
    `@dashboard(default=True)` would `config/save(url_path=null)` -- silently
    overwriting the `lovelace` dashboard, and re-planning the same create
    forever (list_remote never reports "default" there). It must fail loudly
    with a fix instruction instead.
    """
    client = _FakeClient(
        dashboards={
            "lovelace": {
                "id": "lovelace",
                "url_path": "lovelace",
                "title": "Overview",
                "mode": "storage",
            }
        },
        configs={"lovelace": {"views": []}},
    )
    backend = _make_backend(client)

    with pytest.raises(ValueError, match="url_path='lovelace'"):
        asyncio.run(
            backend._acreate_dashboard(  # type: ignore[attr-defined]
                {"meta": None, "config": {"views": [{"title": "Home"}]}}
            )
        )
    assert not any(t == "lovelace/config/save" for t, _ in client.calls)


def test_list_remote_rejects_a_registry_item_colliding_with_the_default_sentinel() -> None:
    """§39.3: `lovelace/dashboards/create` accepts `allow_single_word: true`,
    which bypasses the hyphen rule -- so a real dashboard at the literal
    `url_path: "default"` IS creatable, and dashboards-design.md §3.1's
    "collision-free by construction" does not hold. Two different dashboards
    must never quietly share the identity `"default"`.
    """
    client = _FakeClient(
        dashboards={
            "default": {
                "id": "default",
                "url_path": "default",
                "title": "Literally Default",
                "mode": "storage",
            }
        },
        configs={
            "default": {"views": [{"title": "Not the default dashboard"}]},
            "__default__": {"views": [{"title": "The real default dashboard"}]},
        },
    )
    backend = _make_backend(client)

    with pytest.raises(ValueError, match="default"):
        asyncio.run(backend._alist_dashboards())  # type: ignore[attr-defined]


def test_create_default_refuses_for_a_yaml_mode_lovelace_item_too() -> None:
    """DB0 review finding S2: the create guard must use the SAME all-items
    scan `_alist_dashboards` uses. `_alist_dashboards_ids_only` filters
    `mode != "storage"` first, so a YAML-mode `lovelace` item never reaches
    `_dashboard_ids` -- and a bundle still spelling `@dashboard(default=True)`
    would fall through to `config/save(url_path=null)`, which real HA refuses
    with an opaque `Not supported` (ha-api-notes §39.2's
    `yaml_mode_default_save_rejected`) on every single push.
    """
    client = _FakeClient(
        dashboards={
            "__yaml__": {
                "url_path": "lovelace",
                "title": "Overview",
                "mode": "yaml",
                "filename": "ui-lovelace.yaml",
            }
        },
        configs={"lovelace": {"views": []}},
    )
    backend = _make_backend(client)

    with pytest.raises(ValueError, match="url_path='lovelace'"):
        asyncio.run(
            backend._acreate_dashboard(  # type: ignore[attr-defined]
                {"meta": None, "config": {"views": [{"title": "Home"}]}}
            )
        )
    assert not any(t == "lovelace/config/save" for t, _ in client.calls)


def test_create_refuses_has_own_lovelace_url_path_before_calling_ha() -> None:
    """ha-api-notes §39.11: `lovelace` cannot be created through the public
    API at ALL. `DashboardsCollection._process_create_data` has two gates --
    the hyphen rule (bypassable with `allow_single_word: True`, which is how
    HA's own migration creates it) AND `async_panel_exists`, which
    `_async_ensure_default_panel` guarantees is always true for `lovelace`.
    Hassle must say so itself rather than surfacing HA's confusing
    `url_already_exists` for a dashboard `list_remote` just reported absent.
    """
    client = _FakeClient()
    backend = _make_backend(client)

    with pytest.raises(ValueError, match="reserves that URL"):
        asyncio.run(
            backend._acreate_dashboard(  # type: ignore[attr-defined]
                {
                    "meta": {"url_path": "lovelace", "title": "Overview"},
                    "config": {"views": []},
                }
            )
        )
    assert not any(t == "lovelace/dashboards/create" for t, _ in client.calls)


def test_create_still_works_for_an_ordinary_hyphenated_url_path() -> None:
    client = _FakeClient()
    backend = _make_backend(client)
    identity = asyncio.run(
        backend._acreate_dashboard(  # type: ignore[attr-defined]
            {
                "meta": {"url_path": "climate-control", "title": "Climate"},
                "config": {"views": []},
            }
        )
    )
    assert identity == "climate-control"
    ordinary = next(p for t, p in client.calls if t == "lovelace/dashboards/create")
    assert "allow_single_word" not in ordinary
