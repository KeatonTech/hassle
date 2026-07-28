"""`DirectBackend` — the real HA transport behind the frozen `Backend` protocol.

`DirectBackend` is the synchronous face of :class:`hassle.backend.client.HaClient`.
The sync engine (plan/apply, DESIGN §8) and the CLI are synchronous, but the
HA transport is async (aiohttp), so `DirectBackend` owns a dedicated asyncio loop
running on a daemon thread and bridges every call through it. This keeps a single
long-lived WebSocket connection alive across many sync calls, while presenting the
four plain `Backend` methods (`list_remote`/`create`/`update`/`delete`) the sync
engine expects — so `apply_plan` drives real HA unchanged.

It also exposes non-`Backend` concerns that live on the transport, not the sync
seam (docs/internals/backend-protocol.md "Deliberately out of scope"): registry snapshot fetch,
server-side `validate_config`, trace access, template render, the HA version
check, and the 2026.7 purpose-vocabulary enumeration.

Per-kind mapping to HA's APIs (DESIGN §4, docs/internals/ha-api-notes.md):

- **automations** — config REST, keyed by `id`; enumerate via `/api/states`
  (`attributes.id`), fetch/write/delete `/api/config/automation/config/{id}`.
- **scripts** — config REST, keyed by object_id (from `script.<object_id>`).
- **helpers** (9 storage-collection domains) — WS `{domain}/list|create|update|
  delete`; update/delete key the item as `{domain}_id` (quirk #1).
- **template helpers** (4 config-entry domains) — listing is WS
  (`config_entries/get`); create/update/delete are REST
  (`/api/config/config_entries/flow[/{flow_id}]`, `/api/config/
  config_entries/options/flow[/{flow_id}]`, `DELETE /api/config/
  config_entries/entry/{entry_id}`) — docs/internals/ha-api-notes.md §26: these three
  do not exist as WS commands on real HA. Identity is derived from `name`
  (§26.6: the flow's form schema rejects an unrecognized `unique_id` key
  outright, so there is no settable unique id at all). See
  docs/internals/backend.md for the full wire-format rationale.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from types import TracebackType
from typing import Any, cast

from hassle.backend.client import HaClient
from hassle.backend.errors import HaApiError
from hassle.backend.version import version_warning
from hassle.ir.keys import (
    DASHBOARD_KIND,
    GROUP_DOMAINS,
    HELPER_DOMAINS,
    OBJECT_KINDS,
    TEMPLATE_DOMAINS,
)
from hassle.ir.keys import slugify as _slugify
from hassle.registry.snapshot import PurposeVocabulary, RegistrySnapshot

# Sentinel distinguishing "HA returned config_not_found" (never-saved
# dashboard, docs/internals/dashboards-design.md §2.1) from a legitimately
# empty/falsy config body -- `None`/`{}` are both valid stored configs.
_CONFIG_NOT_FOUND = object()

# The dashboard registry item's mutable fields (docs/internals/
# dashboards-design.md §2.2/§4.1, DB5 2026-07-27 implementation finding):
# HA's real `lovelace/dashboards/update` schema is PREVENT_EXTRA over exactly
# these four -- `url_path` is deliberately excluded (a url_path change is
# delete+create, never an in-place rename, I2) and `id`/`mode` never travel
# in a write payload at all. The update PAYLOAD must be built from this
# explicit allowlist, NEVER by copying `meta`'s own keys wholesale (`meta`
# always carries `url_path` too, and forwarding it verbatim 400s against
# real HA with `invalid_format`).
_DASHBOARD_REGISTRY_FIELDS = ("title", "icon", "show_in_sidebar", "require_admin")

# Hassle's identity for the DEFAULT dashboard (docs/internals/
# dashboards-design.md §3.1). Spelled here rather than imported from
# `hassle.compiler.dashboards.decorators` (which owns the DSL-side constant):
# `hassle.backend` must not depend on `hassle.compiler`
# (`tests/test_package_layering.py`).
DEFAULT_IDENTITY = "default"

# HA's OWN url_path for the default dashboard once it has a registry item
# (`homeassistant/components/lovelace`'s `DOMAIN`). Two independent HA
# behaviors key off this exact string, both captured in
# docs/internals/ha-api-notes.md §39.2:
#   - `_async_migrate_default_config` (storage mode) moves a legacy
#     `.storage/lovelace` into a real registry item at this url_path;
#   - the YAML-mode shim registers ui-lovelace.yaml at this url_path;
# and `lovelace/config`'s handler resolves `url_path=null` to
# `dashboards.get("lovelace") or dashboards[None]`, making `null` an ALIAS for
# this item whenever it exists.
_DEFAULT_DASHBOARD_URL_PATH = "lovelace"

# Defaults HA's dashboard registry schema assigns when a field is omitted on
# create -- VERIFIED against HA 2026.7.4 (docs/internals/ha-api-notes.md
# §39.1's captures: every `dashboards/create` that omitted them came back
# `show_in_sidebar: true, require_admin: false`). Sent EXPLICITLY on
# every UPDATE, never omitted: HA's storage collection MERGES
# (`{**item, **update}`) rather than replacing the item outright, so a
# presence-based payload can never clear/revert a field back to its default
# -- the stale remote value would linger forever, `_advance_manifest` would
# record that unchanged remote as the new base, and every subsequent
# `hassle push` would silently re-plan the same no-op update forever
# (docs/internals/dashboards-design.md §4.1's 2026-07-27 finding).
_DASHBOARD_FIELD_DEFAULTS: dict[str, Any] = {
    "show_in_sidebar": True,
    "require_admin": False,
}


def _dashboard_registry_payload(meta: dict[str, Any]) -> dict[str, Any]:
    """The FULL desired state of the registry item's mutable fields, built
    from `_DASHBOARD_REGISTRY_FIELDS` -- never from `meta`'s own keys (see
    the module-level comment above for why). `icon` is sent explicitly as
    `None` when absent from `meta` (clearing it, convergent update);
    `show_in_sidebar`/`require_admin` fall back to their source-informed
    defaults rather than being omitted."""
    if not meta.get("title"):
        raise ValueError(
            "dashboard config's meta has no 'title' (required for lovelace/dashboards/update)"
        )
    payload: dict[str, Any] = {"title": meta["title"], "icon": meta.get("icon")}
    for field_name in ("show_in_sidebar", "require_admin"):
        payload[field_name] = meta.get(field_name, _DASHBOARD_FIELD_DEFAULTS[field_name])
    assert set(payload) == set(_DASHBOARD_REGISTRY_FIELDS)
    assert "url_path" not in payload
    return payload


# The template integration's config-flow menu step_id per domain
# (docs/internals/ha-api-notes.md §26.1); verified against a real HA instance by
# `test_live_template_flow.py`.
_TEMPLATE_FLOW_TYPE = {
    "template_number": "number",
    "template_sensor": "sensor",
    "template_binary_sensor": "binary_sensor",
    "template_select": "select",
}

# Fields HA's form schema requires beyond `name`/`state`
# (docs/internals/ha-api-notes.md §26.6): a template number needs a write target
# (`set_value`); a template select needs both the option list (`options`) and
# its write target (`select_option`). Sensor/binary_sensor are read-only.
_TEMPLATE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "template_number": ("set_value",),
    "template_sensor": (),
    "template_binary_sensor": (),
    "template_select": ("options", "select_option"),
}

# The `group` integration's config-flow menu step_id per flavor
# (docs/internals/ha-api-notes.md §38.1) -- captured against a live HA instance. Unlike
# template, the step_id per flavor equals the flavor name itself (§38.2).
_GROUP_FLOW_TYPE = {
    "group_binary_sensor": "binary_sensor",
    "group_button": "button",
    "group_cover": "cover",
    "group_event": "event",
    "group_fan": "fan",
    "group_light": "light",
    "group_lock": "lock",
    "group_media_player": "media_player",
    "group_notify": "notify",
    "group_sensor": "sensor",
    "group_switch": "switch",
    "group_valve": "valve",
}

# `name`/`entities`/`hide_members` are always supplied by the DSL builders'
# own required-kwarg signatures; the only field HA's form schema requires
# that isn't already covered by the DSL signature is `type` on `group_sensor`
# (docs/internals/ha-api-notes.md §38.1) -- mirrors `_TEMPLATE_REQUIRED_FIELDS` covering
# only the EXTRA fields beyond what every domain already shares.
_GROUP_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    domain: ("type",) if domain == "group_sensor" else () for domain in GROUP_DOMAINS
}


class DirectBackend:
    """Synchronous `Backend` talking to a real HA instance over REST + WS."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        reload_timeout: float = 10.0,
        reload_interval: float = 0.1,
        **client_opts: Any,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="hassle-directbackend", daemon=True
        )
        self._thread.start()
        self._client = HaClient(url, token, **client_opts)
        self._ha_version: str | None = None
        self._reload_timeout = reload_timeout
        self._reload_interval = reload_interval
        # (kind, name-derived identity) -> HA-assigned entry_id, discovered
        # via list_remote/create and consumed by update/delete (which
        # address the entry by entry_id, not identity -- docs/internals/ha-api-notes.md
        # §26, §26.6). Process-local cache; a fresh DirectBackend rebuilds it
        # from `_alist_template_helpers` on first list_remote.
        self._template_entry_ids: dict[tuple[str, str], str] = {}
        # Same cache, for the group-helper domains -- a SEPARATE dict (never
        # folded into `_template_entry_ids`), mirroring FakeBackend's split
        # (`hassle.backend.fake`'s own `_group_entry_ids` docstring).
        self._group_entry_ids: dict[tuple[str, str], str] = {}
        # (url_path, or the sentinel "default") -> HA-assigned dashboard_id,
        # discovered via list_remote/create and consumed by update/delete
        # (docs/internals/dashboards-design.md §4.1: `dashboard_id` stays
        # transport-internal -- there is a stable user-visible correlator,
        # `url_path`, so this is a process-local cache, never a manifest
        # field, mirroring `_template_entry_ids`/`_group_entry_ids` above).
        self._dashboard_ids: dict[str, str] = {}

    # -- lifecycle / bridge ------------------------------------------------

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def __enter__(self) -> DirectBackend:
        # Eagerly validate auth + capture the HA version, like `hassle login`
        # (DESIGN §4): a bad token surfaces here as HaAuthError. If that probe
        # fails, __exit__ is never called, so tear down the loop thread + session
        # here rather than leak them on the very failure this probe exists to catch.
        try:
            config: dict[str, Any] = self._run(self._client.rest_get("/api/config"))
            self._ha_version = str(config.get("version", ""))
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._run(self._client.close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
            self._loop.close()

    # -- version -----------------------------------------------------------

    @property
    def ha_version(self) -> str:
        if self._ha_version is None:
            config = self._run(self._client.rest_get("/api/config"))
            self._ha_version = str(config.get("version", ""))
        return self._ha_version

    def version_warning(self) -> str | None:
        return version_warning(self.ha_version)

    # -- Backend protocol --------------------------------------------------

    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
        self._require_kind(kind)
        if kind == "automation":
            return self._run(self._alist_automations())
        if kind == "script":
            return self._run(self._alist_scripts())
        if kind in TEMPLATE_DOMAINS:
            return self._run(self._alist_template_helpers(kind))
        if kind in GROUP_DOMAINS:
            return self._run(self._alist_group_helpers(kind))
        if kind == DASHBOARD_KIND:
            return self._run(self._alist_dashboards())
        return self._run(self._alist_helpers(kind))

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self._require_kind(kind)
        if kind == "automation":
            return self._run(self._awrite_automation(config))
        if kind == "script":
            return self._run(self._awrite_script(config))
        if kind in TEMPLATE_DOMAINS:
            return self._run(self._acreate_template_helper(kind, config))
        if kind in GROUP_DOMAINS:
            return self._run(self._acreate_group_helper(kind, config))
        if kind == DASHBOARD_KIND:
            return self._run(self._acreate_dashboard(config))
        return self._run(self._acreate_helper(kind, config))

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        self._require_kind(kind)
        if kind == "automation":
            self._run(self._awrite_automation({**config, "id": identity}))
        elif kind == "script":
            self._run(self._awrite_script({**config, "id": identity}))
        elif kind in TEMPLATE_DOMAINS:
            self._run(self._aupdate_template_helper(kind, identity, config))
        elif kind in GROUP_DOMAINS:
            self._run(self._aupdate_group_helper(kind, identity, config))
        elif kind == DASHBOARD_KIND:
            self._run(self._aupdate_dashboard(identity, config))
        else:
            self._run(self._aupdate_helper(kind, identity, config))

    def delete(self, kind: str, identity: str) -> None:
        self._require_kind(kind)
        if kind == "automation":
            self._run(self._adelete_config("automation", identity))
        elif kind == "script":
            self._run(self._adelete_config("script", identity))
        elif kind in TEMPLATE_DOMAINS:
            self._run(self._adelete_template_helper(kind, identity))
        elif kind in GROUP_DOMAINS:
            self._run(self._adelete_group_helper(kind, identity))
        elif kind == DASHBOARD_KIND:
            self._run(self._adelete_dashboard(identity))
        else:
            self._run(self._adelete_helper(kind, identity))

    def entry_id_for(self, kind: str, identity: str) -> str | None:
        """Additive, non-`Backend`-Protocol lookup (docs/internals/backend-protocol.md §3.1):
        the config entry_id for a template/group-helper kind, `None` for any
        other kind or an identity DirectBackend hasn't seen this process."""
        if kind in GROUP_DOMAINS:
            return self._group_entry_ids.get((kind, identity))
        return self._template_entry_ids.get((kind, identity))

    # -- config-REST reload settling --------------------------------------
    #
    # The config REST API (automations/scripts) writes the YAML file and then
    # *auto-reloads asynchronously* — the entity appears ~300 ms after POST and
    # disappears ~1 s after DELETE (docs/internals/ha-api-notes.md §2). So a create/update/
    # delete returns before the change is observable via `/api/states`. To keep
    # the `Backend` contract synchronous (a later `list_remote` must see the
    # write), we block until the reload settles. This is bounded polling in the
    # transport layer — not core-logic wall-clock (the determinism rule is
    # about compiler/sim logic, not I/O waits).

    async def _await_config_entity(self, kind: str, identity: str, *, present: bool) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._reload_timeout
        while True:
            if (await self._config_entity_exists(kind, identity)) == present:
                return
            if loop.time() >= deadline:
                return  # best-effort: don't hang the CLI on a slow reload
            await asyncio.sleep(self._reload_interval)

    async def _config_entity_exists(self, kind: str, identity: str) -> bool:
        states = await self._client.rest_get("/api/states")
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if kind == "automation":
                if entity_id.startswith("automation.") and (
                    state.get("attributes", {}).get("id") == identity
                ):
                    return True
            elif entity_id == f"script.{identity}":
                return True
        return False

    async def _adelete_config(self, kind: str, identity: str) -> None:
        await self._client.rest_delete(f"/api/config/{kind}/config/{identity}")
        await self._await_config_entity(kind, identity, present=False)

    # -- automations (config REST) ----------------------------------------

    async def _alist_automations(self) -> dict[str, dict[str, Any]]:
        states = await self._client.rest_get("/api/states")
        out: dict[str, dict[str, Any]] = {}
        for state in states:
            if not str(state.get("entity_id", "")).startswith("automation."):
                continue
            config_id = state.get("attributes", {}).get("id")
            if config_id is None:
                continue  # YAML-defined automation without an id: not Hassle-managed
            config = await self._client.rest_get(f"/api/config/automation/config/{config_id}")
            out[str(config_id)] = config
        return out

    async def _awrite_automation(self, config: dict[str, Any]) -> str:
        identity = str(config.get("id"))
        if not identity or identity == "None":
            raise ValueError("automation config has no 'id' (required for the config REST path)")
        await self._client.rest_post(f"/api/config/automation/config/{identity}", json=config)
        await self._await_config_entity("automation", identity, present=True)
        return identity

    # -- scripts (config REST) --------------------------------------------

    async def _alist_scripts(self) -> dict[str, dict[str, Any]]:
        states = await self._client.rest_get("/api/states")
        out: dict[str, dict[str, Any]] = {}
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if not entity_id.startswith("script."):
                continue
            object_id = entity_id.split(".", 1)[1]
            config = await self._client.rest_get(f"/api/config/script/config/{object_id}")
            out[object_id] = config
        return out

    async def _awrite_script(self, config: dict[str, Any]) -> str:
        object_id = str(config.get("id") or _slugify(str(config.get("alias", "script"))))
        # Scripts are keyed by object_id in the path, not by an `id` field in the
        # body (docs/internals/ha-api-notes.md §3) — strip it before POSTing.
        body = {k: v for k, v in config.items() if k != "id"}
        await self._client.rest_post(f"/api/config/script/config/{object_id}", json=body)
        await self._await_config_entity("script", object_id, present=True)
        return object_id

    # -- helpers (WebSocket storage collections) --------------------------
    #
    # These four are the GENERIC storage-collection fallthrough every other
    # branch in list_remote/create/update/delete falls past. Each asserts
    # `kind in HELPER_DOMAINS` (docs/internals/dashboards-design.md §4.1's
    # last bullet, a DB1 review finding): a kind added to `OBJECT_KINDS`
    # without an explicit dispatch branch above must fail loudly HERE, at the
    # dispatch layer -- an `AssertionError` naming the offending kind --
    # rather than silently sending a nonexistent `<kind>/list`-style WS
    # command against real HA and aborting pull/plan/push with a confusing
    # "Unknown command" error far from the actual bug (adding the kind
    # without wiring its backend support).

    async def _alist_helpers(self, kind: str) -> dict[str, dict[str, Any]]:
        assert kind in HELPER_DOMAINS, (
            f"_alist_helpers called for non-helper kind {kind!r} -- a kind must have an "
            "explicit DirectBackend dispatch branch, never fall through to the generic "
            "storage-collection commands"
        )
        items = await self._client.ws_command(f"{kind}/list")
        return {str(item["id"]): item for item in items}

    async def _acreate_helper(self, kind: str, config: dict[str, Any]) -> str:
        assert kind in HELPER_DOMAINS, (
            f"_acreate_helper called for non-helper kind {kind!r} -- a kind must have an "
            "explicit DirectBackend dispatch branch, never fall through to the generic "
            "storage-collection commands"
        )
        # HA assigns the id from the name slug; it rejects a caller-supplied id.
        payload = {k: v for k, v in config.items() if k != "id"}
        result = await self._client.ws_command(f"{kind}/create", **payload)
        return str(result["id"])

    async def _aupdate_helper(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        assert kind in HELPER_DOMAINS, (
            f"_aupdate_helper called for non-helper kind {kind!r} -- a kind must have an "
            "explicit DirectBackend dispatch branch, never fall through to the generic "
            "storage-collection commands"
        )
        payload = {k: v for k, v in config.items() if k != "id"}
        await self._client.ws_command(f"{kind}/update", **{f"{kind}_id": identity}, **payload)

    async def _adelete_helper(self, kind: str, identity: str) -> None:
        assert kind in HELPER_DOMAINS, (
            f"_adelete_helper called for non-helper kind {kind!r} -- a kind must have an "
            "explicit DirectBackend dispatch branch, never fall through to the generic "
            "storage-collection commands"
        )
        await self._client.ws_command(f"{kind}/delete", **{f"{kind}_id": identity})

    # -- config-entry template helpers (docs/internals/ha-api-notes.md §26) ----------
    #
    # Create/update/delete go through HA's config-entry flow REST views, not
    # WebSocket commands (only listing, `config_entries/get`, is WS). Object
    # identity is derived from `name` (slugified) rather than a settable
    # unique id, which the flow schema rejects outright. Reading back a
    # config entry's options opens-then-cancels an options flow (there is no
    # direct GET for entry options); `name` must never be resubmitted through
    # that flow, but survives untouched server-side regardless. The
    # create-flow response's `entry_id` lives under a nested `result` key,
    # with no silent fallback if it's missing. See docs/internals/backend.md
    # for the full wire-format rationale.

    async def _config_entry_entity_domains(self) -> dict[str, str]:
        """`entry_id -> HA entity domain` for EVERY config entry regardless of
        integration, by cross-referencing the entity registry (docs/
        ha-api-notes.md §26.6). Shared, unmodified, by both
        `_alist_template_helpers` and `_alist_group_helpers` -- see
        docs/internals/backend.md for why this is preferred over the
        options-flow `step_id` and why it isn't integration-specific.
        """
        entities = await self._client.ws_command("config/entity_registry/list")
        out: dict[str, str] = {}
        for entity in entities:
            config_entry_id = entity.get("config_entry_id")
            entity_id = str(entity.get("entity_id", ""))
            if not config_entry_id or "." not in entity_id:
                continue
            out[str(config_entry_id)] = entity_id.split(".", 1)[0]
        return out

    async def _acurrent_template_options(self, entry_id: str) -> dict[str, Any]:
        """The stored options of a template config entry, read back via an
        options-flow's suggested values (docs/internals/ha-api-notes.md §26.7 -- there
        is no admin API that returns entry options directly). Opens an
        options flow, harvests `data_schema`'s `description.suggested_value`
        per field, then cancels the flow (mirrors a user opening then closing
        the edit dialog without saving -- never commits a write)."""
        flow = await self._client.rest_post(
            "/api/config/config_entries/options/flow", json={"handler": entry_id}
        )
        flow_id = flow["flow_id"]
        try:
            options: dict[str, Any] = {}
            data_schema: list[dict[str, Any]] = flow.get("data_schema") or []
            for field in data_schema:
                name = field.get("name")
                description = field.get("description")
                if name is None or not isinstance(description, dict):
                    continue
                if "suggested_value" in description:
                    options[str(name)] = description["suggested_value"]
            return options
        finally:
            # Cancel rather than commit -- this is a read, not a write
            # (docs/internals/ha-api-notes.md §26.7). Best-effort: an already-expired
            # flow 404ing on cancel is not this call's problem to raise.
            with contextlib.suppress(HaApiError):
                await self._client.rest_delete(f"/api/config/config_entries/options/flow/{flow_id}")

    async def _alist_template_helpers(self, kind: str) -> dict[str, dict[str, Any]]:
        wanted_domain = _TEMPLATE_FLOW_TYPE[kind]
        entries = await self._client.ws_command("config_entries/get")
        entry_domains = await self._config_entry_entity_domains()
        out: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry.get("domain") != "template":
                continue
            entry_id = str(entry["entry_id"])
            if entry_domains.get(entry_id) != wanted_domain:
                continue
            title = entry.get("title")
            if not title:
                continue
            identity = _slugify(str(title))
            self._template_entry_ids[(kind, identity)] = entry_id
            # `config_entries/get` never carries options (§26.7) -- the
            # options-flow's suggested values are the only source of truth,
            # plus `name` (from `title`, never present in the options-flow
            # schema itself, §26.7 finding 2/3).
            options = await self._acurrent_template_options(entry_id)
            options["name"] = str(title)
            out[identity] = options
        return out

    async def _acreate_template_helper(self, kind: str, config: dict[str, Any]) -> str:
        name = config.get("name")
        if not name:
            raise ValueError(f"{kind} config has no 'name' (required to derive identity/title)")
        identity = _slugify(str(name))
        missing = [f for f in _TEMPLATE_REQUIRED_FIELDS[kind] if config.get(f) is None]
        if missing:
            raise ValueError(
                f"{kind} config is missing required field(s) {missing} "
                "(HA's template form schema rejects the submission without them, "
                "docs/internals/ha-api-notes.md §26.6)"
            )
        step_id = _TEMPLATE_FLOW_TYPE[kind]

        flow = await self._client.rest_post(
            "/api/config/config_entries/flow", json={"handler": "template"}
        )
        flow_id = flow["flow_id"]
        if flow.get("type") == "menu":
            flow = await self._client.rest_post(
                f"/api/config/config_entries/flow/{flow_id}", json={"next_step_id": step_id}
            )
        # EXACTLY the domain's own fields -- no `_template_type`/`unique_id`
        # smuggled in.
        result = await self._client.rest_post(
            f"/api/config/config_entries/flow/{flow_id}", json=dict(config)
        )
        # The create_entry response's `entry_id` is nested under a `"result"`
        # key, never a top-level key (docs/internals/ha-api-notes.md §31.8) -- and
        # never a silent `flow_id` fallback if it's missing, which would
        # cache a wrong value now instead of raising here; see
        # docs/internals/backend.md.
        entry_json = cast("dict[str, Any]", result.get("result") or {})
        entry_id_value = entry_json.get("entry_id")
        if not entry_id_value:
            raise HaApiError(
                f"POST /api/config/config_entries/flow/{flow_id}: the create_entry "
                f"response for {kind}:{identity} had no result.entry_id (received "
                f"top-level keys {sorted(result)}, result keys "
                f"{sorted(entry_json) if entry_json else '<result missing/empty>'}). "
                "This is a Hassle bug, not a mistake in your configuration -- the "
                "expected shape is documented at docs/internals/ha-api-notes.md §31.8. Fix: "
                "please report this (include the keys listed above) at "
                "https://github.com/KeatonTech/hassle/issues; the config entry "
                "may have been created in HA regardless -- check the HA UI's "
                "Settings -> Devices & services page before retrying, to avoid a "
                "duplicate."
            )
        entry_id = str(entry_id_value)
        self._template_entry_ids[(kind, identity)] = entry_id
        return identity

    async def _aupdate_template_helper(
        self, kind: str, identity: str, config: dict[str, Any]
    ) -> None:
        entry_id = self._template_entry_ids.get((kind, identity))
        if entry_id is None:
            # Rebuild the entry_id cache from a fresh list (e.g. a DirectBackend
            # that never listed this kind yet in this process).
            await self._alist_template_helpers(kind)
            entry_id = self._template_entry_ids.get((kind, identity))
        if entry_id is None:
            raise ValueError(
                f"no config entry found for {kind}:{identity} -- an UPDATE must "
                "target an existing entry via an options-flow update, never a recreate"
            )
        missing = [f for f in _TEMPLATE_REQUIRED_FIELDS[kind] if config.get(f) is None]
        if missing:
            raise ValueError(
                f"{kind} config is missing required field(s) {missing} "
                "(HA's template form schema rejects the submission without them, "
                "docs/internals/ha-api-notes.md §26.6)"
            )
        # `name` (and any other non-options-flow-schema key) must NOT be
        # resubmitted -- the options-flow schema never includes it (§26.7
        # finding 2); HA 400s with "extra keys not allowed @ data['name']"
        # otherwise. `name` survives untouched server-side regardless
        # (§26.7 finding 3) since an UPDATE's object_key/identity -- and
        # hence its `name` -- never actually changes (finding 4).
        payload = {k: v for k, v in config.items() if k != "name"}
        flow = await self._client.rest_post(
            "/api/config/config_entries/options/flow", json={"handler": entry_id}
        )
        flow_id = flow["flow_id"]
        await self._client.rest_post(
            f"/api/config/config_entries/options/flow/{flow_id}", json=payload
        )

    async def _adelete_template_helper(self, kind: str, identity: str) -> None:
        entry_id = self._template_entry_ids.get((kind, identity))
        if entry_id is None:
            await self._alist_template_helpers(kind)
            entry_id = self._template_entry_ids.get((kind, identity))
        if entry_id is None:
            return  # already gone / never existed -- delete is idempotent
        await self._client.rest_delete(f"/api/config/config_entries/entry/{entry_id}")
        self._template_entry_ids.pop((kind, identity), None)

    # -- config-entry group helpers (docs/internals/ha-api-notes.md §38) -------------
    #
    # Same create (menu -> form -> create_entry) / read-back (options-flow
    # suggested values) / update (options-flow form -> create_entry) /
    # delete (entry removal) mechanics as the template helper flows above,
    # captured against a live HA instance.
    #
    # The group options-flow schema does NOT include `name`, same as
    # template (real HA 400s `{"errors": {"base": ["extra keys not allowed @
    # data['name']"]}}` on an options-flow submission that carries `name`).
    # So, exactly like `_aupdate_template_helper` above, `_aupdate_group_
    # helper` strips `name` before submitting to the options flow, and
    # `_alist_group_helpers`'s `options.setdefault("name", str(title))`
    # fallback is load-bearing, not merely defensive -- it is the ONLY
    # source of `name` on read-back.

    async def _acurrent_group_options(self, entry_id: str) -> dict[str, Any]:
        """The stored options of a group config entry, read back via an
        options-flow's suggested values -- same mechanism as
        `_acurrent_template_options` (docs/internals/ha-api-notes.md §26.7/§38.1: there
        is no admin API that returns a config entry's options directly, for
        ANY integration). Opens an options flow, harvests `data_schema`'s
        `description.suggested_value` per field, then cancels the flow."""
        flow = await self._client.rest_post(
            "/api/config/config_entries/options/flow", json={"handler": entry_id}
        )
        flow_id = flow["flow_id"]
        try:
            options: dict[str, Any] = {}
            data_schema: list[dict[str, Any]] = flow.get("data_schema") or []
            for field in data_schema:
                name = field.get("name")
                description = field.get("description")
                if name is None or not isinstance(description, dict):
                    continue
                if "suggested_value" in description:
                    options[str(name)] = description["suggested_value"]
            return options
        finally:
            with contextlib.suppress(HaApiError):
                await self._client.rest_delete(f"/api/config/config_entries/options/flow/{flow_id}")

    async def _alist_group_helpers(self, kind: str) -> dict[str, dict[str, Any]]:
        wanted_flavor = _GROUP_FLOW_TYPE[kind]
        entries = await self._client.ws_command("config_entries/get")
        entry_domains = await self._config_entry_entity_domains()
        out: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry.get("domain") != "group":
                continue
            entry_id = str(entry["entry_id"])
            if entry_domains.get(entry_id) != wanted_flavor:
                continue
            title = entry.get("title")
            if not title:
                continue
            identity = _slugify(str(title))
            self._group_entry_ids[(kind, identity)] = entry_id
            options = await self._acurrent_group_options(entry_id)
            # LOAD-BEARING: the group options-flow schema does NOT include
            # `name` (same as template, §26.7 finding 2) --
            # `_acurrent_group_options` never returns it, so `title` (the
            # flow's create-time correlator) is the ONLY source of `name` on
            # read-back, exactly mirroring `_alist_template_helpers` above.
            options["name"] = str(title)
            out[identity] = options
        return out

    async def _acreate_group_helper(self, kind: str, config: dict[str, Any]) -> str:
        name = config.get("name")
        if not name:
            raise ValueError(f"{kind} config has no 'name' (required to derive identity/title)")
        identity = _slugify(str(name))
        missing = [f for f in _GROUP_REQUIRED_FIELDS[kind] if config.get(f) is None]
        if missing:
            raise ValueError(
                f"{kind} config is missing required field(s) {missing} "
                "(HA's group form schema rejects the submission without them, "
                "docs/internals/ha-api-notes.md §38.1)"
            )
        step_id = _GROUP_FLOW_TYPE[kind]

        flow = await self._client.rest_post(
            "/api/config/config_entries/flow", json={"handler": "group"}
        )
        flow_id = flow["flow_id"]
        if flow.get("type") == "menu":
            flow = await self._client.rest_post(
                f"/api/config/config_entries/flow/{flow_id}", json={"next_step_id": step_id}
            )
        result = await self._client.rest_post(
            f"/api/config/config_entries/flow/{flow_id}", json=dict(config)
        )
        # Same nested-`result` wire shape as template (docs/internals/ha-api-notes.md
        # §31.8) -- never a top-level `entry_id` key, and never a silent
        # flow_id fallback if it's missing (the exact bug class §31.8
        # documents).
        entry_json = cast("dict[str, Any]", result.get("result") or {})
        entry_id_value = entry_json.get("entry_id")
        if not entry_id_value:
            raise HaApiError(
                f"POST /api/config/config_entries/flow/{flow_id}: the create_entry "
                f"response for {kind}:{identity} had no result.entry_id (received "
                f"top-level keys {sorted(result)}, result keys "
                f"{sorted(entry_json) if entry_json else '<result missing/empty>'}). "
                "This is a Hassle bug, not a mistake in your configuration -- the "
                "expected shape is documented at docs/internals/ha-api-notes.md §31.8. Fix: "
                "please report this (include the keys listed above) at "
                "https://github.com/KeatonTech/hassle/issues; the config entry "
                "may have been created in HA regardless -- check the HA UI's "
                "Settings -> Devices & services page before retrying, to avoid a "
                "duplicate."
            )
        entry_id = str(entry_id_value)
        self._group_entry_ids[(kind, identity)] = entry_id
        return identity

    async def _aupdate_group_helper(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        entry_id = self._group_entry_ids.get((kind, identity))
        if entry_id is None:
            await self._alist_group_helpers(kind)
            entry_id = self._group_entry_ids.get((kind, identity))
        if entry_id is None:
            raise ValueError(
                f"no config entry found for {kind}:{identity} -- an UPDATE must "
                "target an existing entry via an options-flow update, never a recreate"
            )
        missing = [f for f in _GROUP_REQUIRED_FIELDS[kind] if config.get(f) is None]
        if missing:
            raise ValueError(
                f"{kind} config is missing required field(s) {missing} "
                "(HA's group form schema rejects the submission without them, "
                "docs/internals/ha-api-notes.md §38.1)"
            )
        # `name` (and any other non-options-flow-schema key) must NOT be
        # resubmitted -- the options-flow schema never includes it
        # (docs/internals/ha-api-notes.md §38.1: same rule as template, §26.7 finding
        # 2); HA 400s with "extra keys not allowed @ data['name']" otherwise.
        # `name` survives untouched server-side regardless (mirrors §26.7
        # finding 3) since an UPDATE's object_key/identity -- and hence its
        # `name` -- never actually changes.
        payload = {k: v for k, v in config.items() if k != "name"}
        flow = await self._client.rest_post(
            "/api/config/config_entries/options/flow", json={"handler": entry_id}
        )
        flow_id = flow["flow_id"]
        await self._client.rest_post(
            f"/api/config/config_entries/options/flow/{flow_id}", json=payload
        )

    async def _adelete_group_helper(self, kind: str, identity: str) -> None:
        entry_id = self._group_entry_ids.get((kind, identity))
        if entry_id is None:
            await self._alist_group_helpers(kind)
            entry_id = self._group_entry_ids.get((kind, identity))
        if entry_id is None:
            return  # already gone / never existed -- delete is idempotent
        await self._client.rest_delete(f"/api/config/config_entries/entry/{entry_id}")
        self._group_entry_ids.pop((kind, identity), None)

    # -- dashboards (Lovelace storage-mode, docs/internals/dashboards-design.md
    # §4.1) ------------------------------------------------------------------
    #
    # Unlike template/group helpers, every dashboard command is WebSocket
    # (§2.2's table) -- there is no REST flow here. `list_remote` composes
    # each dashboard's two HA-side stores (the `lovelace_dashboards` registry
    # item + its `lovelace[.<url_path>]` config blob) into the one
    # `{"meta": ..., "config": ...}` envelope `DashboardConfig` expects
    # (docs/internals/dashboards-design.md §3.2); `create`/`update`/`delete`
    # drive the two stores' WS commands to completion inside the single
    # synchronous `Backend` method call, exactly like the config-entry flows
    # above -- the sync engine never sees the two-store seam.

    async def _afetch_dashboard_config(self, url_path: str | None) -> Any:
        """`lovelace/config` for `url_path` (`None` == the default
        dashboard). Returns the sentinel `_CONFIG_NOT_FOUND` for a dashboard
        that has never been saved (§2.1: a never-customized default has no
        config at all; HA raises `config_not_found` -- Hassle treats this as
        absent from `list_remote` rather than an empty/default body)."""
        try:
            return await self._client.ws_command("lovelace/config", url_path=url_path)
        except HaApiError as exc:
            if exc.code == "config_not_found":
                return _CONFIG_NOT_FOUND
            raise

    async def _alist_dashboards(self) -> dict[str, dict[str, Any]]:
        items = await self._client.ws_command("lovelace/dashboards/list")
        out: dict[str, dict[str, Any]] = {}
        # Set while scanning ALL items -- deliberately BEFORE the mode filter,
        # since a YAML-mode `lovelace` item aliases the default probe just as
        # a storage-mode one does (docs/internals/ha-api-notes.md §39.2).
        has_lovelace_item = any(
            item.get("url_path") == _DEFAULT_DASHBOARD_URL_PATH for item in items
        )
        for item in items:
            if item.get("mode") != "storage":
                continue  # YAML-mode dashboard: not ours to manage (I1)
            dashboard_id = str(item["id"])
            url_path = item.get("url_path")
            identity = str(url_path) if url_path is not None else DEFAULT_IDENTITY
            if identity == DEFAULT_IDENTITY and url_path is not None:
                # §39.3: `lovelace/dashboards/create` exposes
                # `allow_single_word: true`, which bypasses HA's hyphen rule,
                # so a REAL dashboard at the literal `url_path: "default"` is
                # creatable -- and would silently share Hassle's sentinel
                # identity with the actual default dashboard.
                raise ValueError(
                    "this Home Assistant has a dashboard whose url_path is literally "
                    f"{DEFAULT_IDENTITY!r}, which collides with the identity Hassle "
                    "reserves for the DEFAULT dashboard (docs/internals/"
                    "dashboards-design.md §3.1) -- two different dashboards would "
                    "share one object key. Fix: rename that dashboard's URL in "
                    "Settings > Dashboards to anything containing a hyphen (HA "
                    "requires a hyphen for every dashboard created through the UI), "
                    "then re-run this command."
                )
            self._dashboard_ids[identity] = dashboard_id
            # `meta` is the registry item minus `id` (HA-assigned,
            # transport-only) and minus `mode` (always "storage" here, §3.2).
            meta = {k: v for k, v in item.items() if k not in ("id", "mode")}
            config = await self._afetch_dashboard_config(url_path)
            if config is _CONFIG_NOT_FOUND:
                continue
            out[identity] = {"meta": meta, "config": config}
        # The default dashboard is probed separately ONLY when it has no
        # registry item of its own (docs/internals/ha-api-notes.md §39.2). On
        # HA 2026.x it usually DOES have one: `_async_migrate_default_config`
        # moves a legacy `.storage/lovelace` into a real registry item at
        # `url_path: "lovelace"`, and `lovelace/config`'s handler is
        # `dashboards.get("lovelace") or dashboards[None]` -- so `url_path=null`
        # is then an ALIAS for that item, not a second store. Probing anyway
        # would adopt one HA dashboard as TWO Hassle objects (`"lovelace"` and
        # `"default"`) that overwrite each other's config on every push. The
        # same guard covers the YAML-mode default (mode `yaml` at the same
        # url_path): the mode filter above drops the registry item, but the
        # probe would otherwise adopt ui-lovelace.yaml's content, which Hassle
        # must never manage (I1).
        if not has_lovelace_item:
            default_config = await self._afetch_dashboard_config(None)
            if default_config is not _CONFIG_NOT_FOUND:
                out[DEFAULT_IDENTITY] = {"meta": None, "config": default_config}
        return out

    async def _acreate_dashboard(self, config: dict[str, Any]) -> str:
        meta = config.get("meta")
        view_config = config.get("config")
        if meta is None:
            # The default dashboard has no registry item -- config/save only
            # (§4.1's mapping table).
            #
            # ...unless HA has already migrated it into one (ha-api-notes
            # §39.2). There, `config/save(url_path=null)` writes THROUGH to the
            # `lovelace` dashboard, so a bundle still spelling
            # `@dashboard(default=True)` would silently overwrite it -- and,
            # since `list_remote` reports that dashboard as `"lovelace"` and
            # never as `"default"`, re-plan the identical create on every
            # single push. Fail loudly with the fix instead.
            await self._alist_dashboards_ids_only()
            if _DEFAULT_DASHBOARD_URL_PATH in self._dashboard_ids:
                raise ValueError(
                    "this Home Assistant's default dashboard already has its own "
                    f"registry entry at url_path={_DEFAULT_DASHBOARD_URL_PATH!r} (Home "
                    "Assistant migrates it there on upgrade), so `default=True` no "
                    "longer addresses it -- saving through it would overwrite that "
                    "dashboard and re-plan this create forever. Fix: declare it as "
                    f"@dashboard(url_path={_DEFAULT_DASHBOARD_URL_PATH!r}, ...) "
                    "instead of @dashboard(default=True), or run `hassle pull` to "
                    "have Hassle rewrite the declaration for you."
                )
            await self._client.ws_command("lovelace/config/save", url_path=None, config=view_config)
            return DEFAULT_IDENTITY
        if not isinstance(meta, dict):
            raise ValueError(
                "dashboard config's meta must be a dict or null (required to "
                "create a dashboard's registry item)"
            )
        meta = cast("dict[str, Any]", meta)
        if not meta.get("url_path"):
            raise ValueError(
                "dashboard config's meta has no 'url_path' (required to create a "
                "non-default dashboard's registry item, docs/internals/"
                "dashboards-design.md §5.2's @dashboard(url_path=...) contract)"
            )
        identity = str(meta["url_path"])
        payload = {k: v for k, v in meta.items() if k != "id"}
        payload["mode"] = "storage"
        result = await self._client.ws_command("lovelace/dashboards/create", **payload)
        dashboard_id = str(result["id"])
        self._dashboard_ids[identity] = dashboard_id
        try:
            await self._client.ws_command(
                "lovelace/config/save", url_path=identity, config=view_config
            )
        except BaseException:
            # Partial-create rollback (§4.1): the registry item was created
            # but the config write failed -- delete it before surfacing the
            # error, so the apply engine's snapshot/rollback model (DESIGN
            # §8.2) still holds at the object level (never a half-created
            # dashboard left dangling in HA). Best-effort: if the rollback
            # delete itself fails, the ORIGINAL error is still what
            # propagates, not the cleanup failure.
            with contextlib.suppress(Exception):
                await self._client.ws_command(
                    "lovelace/dashboards/delete", dashboard_id=dashboard_id
                )
            self._dashboard_ids.pop(identity, None)
            raise
        return identity

    async def _aresolve_dashboard_id(self, identity: str) -> str:
        """`dashboard_id` stays transport-internal (§4.1): resolved from
        `url_path` via `lovelace/dashboards/list`, cached per connection
        (`self._dashboard_ids`) -- no manifest field needed, unlike a
        config-entry's `entry_id`, since `url_path` is itself a stable,
        user-visible correlator."""
        cached = self._dashboard_ids.get(identity)
        if cached is not None:
            return cached
        await self._alist_dashboards_ids_only()
        dashboard_id = self._dashboard_ids.get(identity)
        if dashboard_id is None:
            raise ValueError(
                f"no dashboard registry item found for url_path {identity!r} -- an "
                "UPDATE/DELETE must target an existing dashboard, never a recreate "
                "(a url_path rename is modeled as delete+create, docs/internals/"
                "dashboards-design.md §4.1 -- an existing object's HA id is never "
                "changed in place)"
            )
        return dashboard_id

    async def _alist_dashboards_ids_only(self) -> None:
        """Refresh `self._dashboard_ids` from `lovelace/dashboards/list`
        without paying for a `lovelace/config` fetch per dashboard (unlike
        `_alist_dashboards`, which composes full envelopes for
        `Backend.list_remote`) -- used only to resolve a `dashboard_id` for
        `update`/`delete`."""
        items = await self._client.ws_command("lovelace/dashboards/list")
        for item in items:
            if item.get("mode") != "storage":
                continue
            url_path = item.get("url_path")
            identity = str(url_path) if url_path is not None else DEFAULT_IDENTITY
            self._dashboard_ids[identity] = str(item["id"])

    async def _aupdate_dashboard(self, identity: str, config: dict[str, Any]) -> None:
        meta = config.get("meta")
        view_config = config.get("config")
        if meta is not None:
            if not isinstance(meta, dict):
                raise ValueError("dashboard config's meta must be a dict or null")
            meta = cast("dict[str, Any]", meta)
            dashboard_id = await self._aresolve_dashboard_id(identity)
            payload = _dashboard_registry_payload(meta)
            await self._client.ws_command(
                "lovelace/dashboards/update", dashboard_id=dashboard_id, **payload
            )
        url_path = None if identity == "default" else identity
        await self._client.ws_command("lovelace/config/save", url_path=url_path, config=view_config)

    async def _adelete_dashboard(self, identity: str) -> None:
        if identity == "default":
            # Reverts to auto-generated (§4.1) -- there is no registry item
            # to remove for the default dashboard.
            await self._client.ws_command("lovelace/config/delete", url_path=None)
            return
        dashboard_id = await self._aresolve_dashboard_id(identity)
        await self._client.ws_command("lovelace/dashboards/delete", dashboard_id=dashboard_id)
        self._dashboard_ids.pop(identity, None)

    # -- registry snapshot (DESIGN §9.2) ----------------------------------

    def fetch_registry_snapshot(self) -> RegistrySnapshot:
        return self._run(self._afetch_registry_snapshot())

    # Scopes to fetch into the registry snapshot (docs/internals/ha-api-notes.md
    # §31.2/§31.6, source-verified): `automation`/`script` place by their own
    # scope; ALL 13 helper kinds share the one `"helpers"` scope. Bundle
    # placement for helpers is handled elsewhere -- this is just the read
    # path making the data available in the snapshot.
    _CATEGORY_SCOPES = ("automation", "script", "helpers")

    async def _afetch_registry_snapshot(self) -> RegistrySnapshot:
        entities = await self._client.ws_command("config/entity_registry/list")
        devices = await self._client.ws_command("config/device_registry/list")
        areas = await self._client.ws_command("config/area_registry/list")
        labels = await self._client.ws_command("config/label_registry/list")
        try:
            floors = await self._client.ws_command("config/floor_registry/list")
        except Exception:
            floors = []
        categories = await self._afetch_categories()
        services = await self._client.ws_command("get_services")
        vocab = await self._afetch_purpose_vocabulary()

        for entity in entities:
            entity.setdefault("domain", str(entity.get("entity_id", "")).split(".", 1)[0])
        # HA's device registry keys each row as `id`; the snapshot model (and its
        # fixtures) use `device_id` (docs/internals/ha-api-notes.md §5).
        for device in devices:
            device.setdefault("device_id", device.get("id"))

        return RegistrySnapshot.model_validate(
            {
                "entities": entities,
                "devices": devices,
                "areas": areas,
                "labels": labels,
                "floors": floors,
                "categories": categories,
                "services": services,
                "purpose_vocabulary": vocab.model_dump(),
            }
        )

    async def _afetch_categories(self) -> dict[str, dict[str, str]]:
        """`config/category_registry/list` per scope (DESIGN §7.3, docs/ha-api-
        notes.md new §22): each row is `{category_id, name, icon}`. Guarded
        per-scope, like the `floor_registry` guard above -- older HA (pre-
        category-registry) rejects the command entirely, and even on newer HA
        a single scope failing must not blank out the other's categories."""
        categories: dict[str, dict[str, str]] = {}
        for scope in self._CATEGORY_SCOPES:
            try:
                rows = await self._client.ws_command("config/category_registry/list", scope=scope)
            except Exception:
                continue
            categories[scope] = {
                str(row["category_id"]): str(row.get("name", row["category_id"])) for row in rows
            }
        return categories

    # -- category write-back on push-create/move ---------------------------
    #
    # Additive, non-`Backend`-Protocol surface (same `entry_id_for`/
    # `fetch_registry_snapshot` pattern) driving `hassle.sync.
    # category_writeback.attempt_category_writeback` (CREATE) and `hassle.
    # sync.category_move.sync_category_on_move` (UPDATE). Shapes are
    # source-verified against HA core's `homeassistant/components/config/
    # category_registry.py` / `entity_registry.py` (docs/internals/ha-api-notes.md §31).

    def list_categories(self, scope: str) -> dict[str, str]:
        return self._run(self._alist_categories(scope))

    async def _alist_categories(self, scope: str) -> dict[str, str]:
        rows = await self._client.ws_command("config/category_registry/list", scope=scope)
        return {str(row["category_id"]): str(row.get("name", row["category_id"])) for row in rows}

    def create_category(self, scope: str, name: str) -> str:
        return self._run(self._acreate_category(scope, name))

    async def _acreate_category(self, scope: str, name: str) -> str:
        result = await self._client.ws_command(
            "config/category_registry/create", scope=scope, name=name
        )
        return str(result["category_id"])

    def delete_category(self, scope: str, category_id: str) -> None:
        """`config/category_registry/delete` -- additive, test/CLI-facing
        (docs/internals/ha-api-notes.md §31.5c: `websocket_delete_category`,
        `{scope, category_id}`)."""
        self._run(self._adelete_category(scope, category_id))

    async def _adelete_category(self, scope: str, category_id: str) -> None:
        await self._client.ws_command(
            "config/category_registry/delete", scope=scope, category_id=category_id
        )

    def assign_category(
        self, kind: str, identity: str, scope: str, category_id: str | None
    ) -> None:
        self._run(self._aassign_category(kind, identity, scope, category_id))

    async def _aassign_category(
        self, kind: str, identity: str, scope: str, category_id: str | None
    ) -> None:
        """Find `kind:identity`'s entity-registry row and update its
        `categories` map for `scope`.

        **Single-scope merge payload, no read-first** (docs/internals/ha-api-notes.md
        §31.3/§31.5b, source-verified): `config/entity_registry/update`'s
        `categories` handler merges per-scope SERVER-SIDE ("If passed in, we
        update/adjust only the provided scope(s). Other category scopes in
        the entity, are left as is." -- HA core's own comment). A
        client-side read-then-merge is therefore unnecessary (though
        harmless/idempotent) -- this just sends `{scope: category_id}`, and
        `category_id=None` UNSETS that scope (the `{scope: None}` primitive
        §31.3 confirms), used by `hassle.sync.category_move` for a local
        move to the `misc.py` fallback.

        **Identity anchor** (docs/internals/ha-api-notes.md §2/§22/§31.6/§31.8):
        `unique_id == identity` for automations/scripts/storage helpers. A
        TEMPLATE_DOMAINS kind has no CALLER-settable `unique_id` (§26.6), but
        its entity's `unique_id` is not blank either -- `template/helpers.py`'s
        `async_setup_template_entry` constructs the entity with
        `unique_id=config_entry.entry_id` (source-verified, §31.8), i.e.
        **`unique_id` == the config entry's own `entry_id`, always**. So the
        SAME `unique_id`-keyed lookup this method already uses for every
        other kind works for template helpers too -- the match VALUE is just
        the cached `entry_id` (`self._template_entry_ids`) instead of the
        object-key identity.

        **Bounded-polls for the entity-registry row itself** (same class of
        async-settling wait as `_await_config_entity`, §17.7): by the time
        `apply_plan` calls this, `create()` already waited for the entity to
        appear in `/api/states`, but that is a DIFFERENT signal than "the
        entity-registry row is visible via `config/entity_registry/list`" --
        if HA populates the registry row on a slightly later tick, an
        immediate lookup here would raise `LookupError` even though the
        object was created correctly. Reuses `self._reload_timeout`/
        `self._reload_interval` (the same knobs `_await_config_entity` uses)
        rather than inventing a second wait budget.
        """
        entity_id = await self._await_entity_registry_row(kind, identity)
        await self._client.ws_command(
            "config/entity_registry/update", entity_id=entity_id, categories={scope: category_id}
        )

    def _unique_id_to_match(self, kind: str, identity: str) -> str | None:
        """The `unique_id` value `kind:identity`'s entity-registry row must
        carry (docs/internals/ha-api-notes.md §31.8): the object-key identity itself
        for every kind EXCEPT a TEMPLATE_DOMAINS/GROUP_DOMAINS kind, whose
        entity's `unique_id` is the config entry's `entry_id` instead (there
        is no caller-settable `unique_id` for these, §26.6/§38.1 -- the same
        `SchemaConfigFlowHandler`-family entity setup pattern
        `async_setup_template_entry` uses, §31.8, is the generic HA
        config-entry-helper convention, not template-specific) -- `None` if
        this process hasn't cached that kind/identity's `entry_id` yet."""
        if kind in TEMPLATE_DOMAINS:
            return self._template_entry_ids.get((kind, identity))
        if kind in GROUP_DOMAINS:
            return self._group_entry_ids.get((kind, identity))
        return identity

    async def _find_entity_registry_row(self, kind: str, identity: str) -> str | None:
        unique_id = self._unique_id_to_match(kind, identity)
        if unique_id is None:
            return None
        entities = await self._client.ws_command("config/entity_registry/list")
        for entity in entities:
            if str(entity.get("unique_id")) == unique_id:
                return str(entity.get("entity_id"))
        return None

    async def _await_entity_registry_row(self, kind: str, identity: str) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._reload_timeout
        while True:
            found = await self._find_entity_registry_row(kind, identity)
            if found is not None:
                return found
            if loop.time() >= deadline:
                raise LookupError(
                    f"no entity-registry row found for {kind}:{identity} after waiting "
                    f"{self._reload_timeout}s -- cannot assign its HA UI category (the object "
                    "was created successfully; only this metadata step failed)"
                )
            await asyncio.sleep(self._reload_interval)

    def categories_for(self, kind: str, identity: str) -> dict[str, str]:
        """Test/CLI-facing lookup: the entity-registry row's current
        `categories` map for `kind:identity` (empty if not found/uncategorized).
        Same identity anchor as `_aassign_category` (§31.6/§31.8)."""
        unique_id = self._unique_id_to_match(kind, identity)
        if unique_id is None:
            return {}
        entities = self._run(self._client.ws_command("config/entity_registry/list"))
        for entity in entities:
            if str(entity.get("unique_id")) == unique_id:
                return dict(entity.get("categories") or {})
        return {}

    # -- purpose vocabulary (DESIGN §4) -------------------------------------

    def fetch_purpose_vocabulary(self) -> PurposeVocabulary:
        return self._run(self._afetch_purpose_vocabulary())

    async def _afetch_purpose_vocabulary(self) -> PurposeVocabulary:
        # The 2026.7 UI enumerates purpose-specific trigger/condition types via
        # these subscriptions: each acks then pushes a `{type: description}`
        # snapshot event (docs/internals/ha-api-notes.md §17). The vocabulary is the keys.
        triggers = await self._subscribe_keys("trigger_platforms/subscribe")
        conditions = await self._subscribe_keys("condition_platforms/subscribe")
        return PurposeVocabulary(triggers=triggers, conditions=conditions)

    async def _subscribe_keys(self, command: str) -> list[str]:
        # Swallow ONLY "command not supported" (HA older than 2026.7 rejects the
        # subscription with success:false -> HaApiError): that legitimately means
        # "no purpose vocabulary". A connection/timeout/envelope error must
        # propagate, so a broken enumeration on real 2026.7 fails loudly instead
        # of masquerading as an empty vocabulary (which would let CI's purpose-
        # vocab verification pass vacuously).
        try:
            event = await self._client.ws_subscribe_first_event(command)
        except HaApiError:
            return []
        if not isinstance(event, dict):
            return []
        mapping = cast("dict[str, Any]", event)
        return sorted(str(key) for key in mapping)

    # -- server-side validation (DESIGN §9 tier 4) ------------------------

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Run HA's own `validate_config` on an automation-shaped config.

        Requires the plural block keys (docs/internals/ha-api-notes.md §6); returns HA's
        per-block `{valid, error}` report.
        """
        return self._run(
            self._client.ws_command(
                "validate_config",
                triggers=config.get("triggers", []),
                conditions=config.get("conditions", []),
                actions=config.get("actions", []),
            )
        )

    # -- traces (DESIGN §10.4) --------------------------------------------

    def list_traces(self, kind: str, identity: str) -> list[dict[str, Any]]:
        return self._run(self._client.ws_command("trace/list", domain=kind, item_id=identity))

    def get_trace(self, kind: str, identity: str, run_id: str) -> dict[str, Any]:
        return self._run(
            self._client.ws_command("trace/get", domain=kind, item_id=identity, run_id=run_id)
        )

    # -- template render (DESIGN §4 row 8) --------------------------------

    def render_template(self, template: str) -> str:
        return self._run(
            self._client.rest_post("/api/template", json={"template": template}, expect="text")
        )

    # -- service calls (`hassle run --live`, DESIGN §10.4) -----------------

    def call_service(self, domain: str, service: str, **data: Any) -> Any:
        """Call `{domain}.{service}` via `POST /api/services/{domain}/{service}`.

        The shadow-automation live-run flow needs to trigger
        `automation.trigger` with `skip_condition` explicitly set
        (docs/internals/ha-api-notes.md §10.6) -- a generic service-call passthrough,
        not specific to any one domain.
        """
        return self._run(self._client.rest_post(f"/api/services/{domain}/{service}", json=data))

    # -- misc read helpers -------------------------------------------------

    def states(self) -> list[dict[str, Any]]:
        return self._run(self._client.rest_get("/api/states"))

    def entity_registry(self) -> list[dict[str, Any]]:
        return self._run(self._client.ws_command("config/entity_registry/list"))

    # -- internal ----------------------------------------------------------

    def _require_kind(self, kind: str) -> None:
        if kind not in OBJECT_KINDS:
            raise ValueError(
                f"unknown object kind {kind!r} (expected one of {sorted(OBJECT_KINDS)})"
            )

    @property
    def helper_domains(self) -> frozenset[str]:
        return HELPER_DOMAINS
