"""`DirectBackend` — the real HA transport behind the F2 `Backend` protocol (M6).

`DirectBackend` is the synchronous face of :class:`hassle.backend.client.HaClient`.
The sync engine (plan/apply, DESIGN §8) and the CLI (M7) are synchronous, but the
HA transport is async (aiohttp), so `DirectBackend` owns a dedicated asyncio loop
running on a daemon thread and bridges every call through it. This keeps a single
long-lived WebSocket connection alive across many sync calls, while presenting the
four plain `Backend` methods (`list_remote`/`create`/`update`/`delete`) the sync
engine expects — so `apply_plan` (M5) drives real HA unchanged.

It also exposes the M6-only, non-`Backend` concerns that live on the transport,
not the sync seam (docs/backend.md "Deliberately out of scope"): registry
snapshot fetch, server-side `validate_config`, trace access, template render, the
HA version check, and the 2026.7 purpose-vocabulary enumeration.

Per-kind mapping to HA's APIs (DESIGN §4, docs/ha-api-notes.md):

- **automations** — config REST, keyed by `id`; enumerate via `/api/states`
  (`attributes.id`), fetch/write/delete `/api/config/automation/config/{id}`.
- **scripts** — config REST, keyed by object_id (from `script.<object_id>`).
- **helpers** (9 storage-collection domains) — WS `{domain}/list|create|update|
  delete`; update/delete key the item as `{domain}_id` (quirk #1).
- **template helpers** (M10, 4 config-entry domains) — listing is WS
  (`config_entries/get`); create/update/delete are REST
  (`/api/config/config_entries/flow[/{flow_id}]`, `/api/config/
  config_entries/options/flow[/{flow_id}]`, `DELETE /api/config/
  config_entries/entry/{entry_id}`) — docs/ha-api-notes.md §26, §26.0
  correction (an earlier revision modeled all three as WS commands; CI
  found they don't exist as such on real HA). Identity is derived from
  `name` (§26.6 correction: the flow's form schema rejects an unrecognized
  `unique_id` key outright, so there is no settable unique id at all).
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
from hassle.ir.keys import HELPER_DOMAINS, OBJECT_KINDS, TEMPLATE_DOMAINS
from hassle.ir.keys import slugify as _slugify
from hassle.registry.snapshot import PurposeVocabulary, RegistrySnapshot

# The template integration's config-flow menu step_id per domain (M10,
# docs/ha-api-notes.md §26.1) -- source-informed; the CI integration suite is
# the authoritative verification (`test_m10_template_flow.py`).
_TEMPLATE_FLOW_TYPE = {
    "template_number": "number",
    "template_sensor": "sensor",
    "template_binary_sensor": "binary_sensor",
    "template_select": "select",
}

# Fields HA's form schema requires beyond `name`/`state` (CI finding,
# docs/ha-api-notes.md §26.6): a template number needs a write target
# (`set_value`); a template select needs both the option list (`options`) and
# its write target (`select_option`). Sensor/binary_sensor are read-only.
_TEMPLATE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "template_number": ("set_value",),
    "template_sensor": (),
    "template_binary_sensor": (),
    "template_select": ("options", "select_option"),
}


class DirectBackend:
    """Synchronous `Backend` (F2) talking to a real HA instance over REST + WS."""

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
        # M10: (kind, name-derived identity) -> HA-assigned entry_id,
        # discovered via list_remote/create and consumed by update/delete
        # (which address the entry by entry_id, not identity --
        # docs/ha-api-notes.md §26, §26.6). Process-local cache; a fresh
        # DirectBackend rebuilds it from `_alist_template_helpers` on first
        # list_remote.
        self._template_entry_ids: dict[tuple[str, str], str] = {}

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
        return self._run(self._alist_helpers(kind))

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self._require_kind(kind)
        if kind == "automation":
            return self._run(self._awrite_automation(config))
        if kind == "script":
            return self._run(self._awrite_script(config))
        if kind in TEMPLATE_DOMAINS:
            return self._run(self._acreate_template_helper(kind, config))
        return self._run(self._acreate_helper(kind, config))

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        self._require_kind(kind)
        if kind == "automation":
            self._run(self._awrite_automation({**config, "id": identity}))
        elif kind == "script":
            self._run(self._awrite_script({**config, "id": identity}))
        elif kind in TEMPLATE_DOMAINS:
            self._run(self._aupdate_template_helper(kind, identity, config))
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
        else:
            self._run(self._client.ws_command(f"{kind}/delete", **{f"{kind}_id": identity}))

    def entry_id_for(self, kind: str, identity: str) -> str | None:
        """Additive, non-`Backend`-Protocol lookup (docs/backend.md §3.1):
        the config entry_id for a template-helper kind, `None` for any other
        kind or an identity DirectBackend hasn't seen this process."""
        return self._template_entry_ids.get((kind, identity))

    # -- config-REST reload settling --------------------------------------
    #
    # The config REST API (automations/scripts) writes the YAML file and then
    # *auto-reloads asynchronously* — the entity appears ~300 ms after POST and
    # disappears ~1 s after DELETE (docs/ha-api-notes.md §2). So a create/update/
    # delete returns before the change is observable via `/api/states`. To keep
    # the `Backend` contract synchronous (a later `list_remote` must see the
    # write), we block until the reload settles. This is bounded polling in the
    # transport layer — not core-logic wall-clock (R8 concerns compiler/sim
    # determinism, not I/O waits).

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
        # body (docs/ha-api-notes.md §3) — strip it before POSTing.
        body = {k: v for k, v in config.items() if k != "id"}
        await self._client.rest_post(f"/api/config/script/config/{object_id}", json=body)
        await self._await_config_entity("script", object_id, present=True)
        return object_id

    # -- helpers (WebSocket storage collections) --------------------------

    async def _alist_helpers(self, kind: str) -> dict[str, dict[str, Any]]:
        items = await self._client.ws_command(f"{kind}/list")
        return {str(item["id"]): item for item in items}

    async def _acreate_helper(self, kind: str, config: dict[str, Any]) -> str:
        # HA assigns the id from the name slug; it rejects a caller-supplied id.
        payload = {k: v for k, v in config.items() if k != "id"}
        result = await self._client.ws_command(f"{kind}/create", **payload)
        return str(result["id"])

    async def _aupdate_helper(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        payload = {k: v for k, v in config.items() if k != "id"}
        await self._client.ws_command(f"{kind}/update", **{f"{kind}_id": identity}, **payload)

    # -- config-entry template helpers (M10, docs/ha-api-notes.md §26) ----
    #
    # **CORRECTION 1 (docs/ha-api-notes.md §26.0, CI round 1, HA stable+dev):**
    # the ORIGINAL implementation drove config_entries/flow,
    # config_entries/options/flow, and config_entries/remove over the
    # WebSocket -- all three do not exist as WS commands (HA raised
    # `Unknown command` on every one). `homeassistant/components/config/
    # config_entries.py` registers these as **REST views**: flow start/step
    # submission is `ConfigManagerFlowIndexView`/`ConfigManagerFlowResourceView`
    # under `/api/config/config_entries/flow`; options-flow is the same shape
    # under `/api/config/config_entries/options/flow`; entry removal is
    # `ConfigManagerEntryResourceView`'s `DELETE /api/config/config_entries/
    # entry/{entry_id}`. Only listing entries (`config_entries/get`) is a
    # genuine WS command and was already correct.
    #
    # **CORRECTION 2 (docs/ha-api-notes.md §26.6, CI round 2, HA stable+dev):**
    # with the transport fixed, step submission itself 400'd:
    # `{"errors": {"base": ["extra keys not allowed @ data['_template_type']",
    # "extra keys not allowed @ data['unique_id']"], "set_value": "required
    # key not provided"}}`. Three findings:
    #
    # 1. The form step's `user_input` must be EXACTLY the domain's own fields
    #    -- no smuggled-in bookkeeping keys. `_template_type` (this module's
    #    own "which of the 4 sub-kinds" tracker) and `unique_id` (the
    #    original identity scheme) are both rejected as unknown schema keys.
    #    The menu selection is a SEPARATE step (`{"next_step_id": "number"}`,
    #    §26.1) and is never resent with the form.
    # 2. `template_number`'s schema requires `set_value` (the write-target
    #    action sequence, since a number needs somewhere to send a written
    #    value -- `state` alone only computes the display value);
    #    `template_select` likewise requires `select_option` alongside
    #    `options`. Sensor/binary_sensor need only `state` (read-only, no
    #    write target). See `_TEMPLATE_REQUIRED_FIELDS` above and
    #    `hassle.compiler.template_helpers`'s `set_value=`/`select_option=`
    #    DSL kwargs.
    # 3. `unique_id` is REJECTED by the flow outright -- a flow-created entry
    #    has no caller-settable unique id at all. **Identity redesign
    #    (un-freezes and re-freezes MILESTONES M10's identity section, same
    #    PR, R5):** object identity is now derived from the declared `name`
    #    (slugified), exactly mirroring the storage helpers' "id is a slug of
    #    name" rule -- see `TemplateHelperConfig.identity`
    #    (`hassle.ir.models`). On the wire, the entry's `title` (which the
    #    flow sets from the submitted `name`) is what `list_remote` slugifies
    #    to re-derive the SAME identity on read-back. The sub-kind (which of
    #    the 4 domains an entry is) can no longer travel inside `options`
    #    either, so `_alist_template_helpers` below cross-references the
    #    entity registry (`config/entity_registry/list`, keyed by
    #    `config_entry_id`) to read the actual HA domain
    #    (`number`/`sensor`/`binary_sensor`/`select`) of the entity the entry
    #    created -- the authoritative, HA-side answer to "which sub-kind is
    #    this", not a client-side guess.
    #
    # **CORRECTION 3 (docs/ha-api-notes.md §26.7-26.9, CI round 3, HA
    # stable+dev): CREATE works; READ-BACK and UPDATE were both still wrong.**
    #
    # 1. **`config_entries/get` (and `config_entries/get_single`) never carry
    #    a config entry's options at all.** Both serialize
    #    `ConfigEntry.as_json_fragment` (`homeassistant/config_entries.py`),
    #    whose JSON body is `entry_id`/`domain`/`title`/`state`/... -- there is
    #    no `options`/`data` key in that shape, full stop. The round-2 code's
    #    `entry.get("options", {})` was always `{}` against real HA; that's
    #    exactly the `KeyError: 'name'` / `KeyError: 'state'` CI hit reading
    #    back a just-created entry. **There is no admin API that returns a
    #    config entry's options directly** (confirmed by reading every view
    #    `homeassistant/components/config/config_entries.py` registers: the
    #    single-entry REST resource has only `DELETE`/reload-`POST`, no `GET`).
    #    The only place options ever appear on the wire is as **suggested
    #    values baked into an options-flow form's `data_schema`**
    #    (`SchemaOptionsFlowHandler.__init__` seeds `self._options` from
    #    `config_entry.options`; `SchemaCommonFlowHandler._show_next_step`
    #    calls `add_suggested_values_to_schema` with exactly that dict,
    #    `homeassistant/helpers/schema_config_entry_flow.py`), which
    #    `voluptuous_serialize.convert` turns into each field's
    #    `{"name": ..., "description": {"suggested_value": ...}}` entry
    #    (`homeassistant/helpers/data_entry_flow.py`). This is genuinely what
    #    the UI's own edit dialog does to pre-populate its form (I1) -- so
    #    read-back now starts an options flow per entry, reads the suggested
    #    values off `data_schema`, and **cancels the flow**
    #    (`DELETE .../options/flow/{flow_id}`, same cleanup a user closing the
    #    dialog without saving triggers) rather than committing it.
    # 2. **The options-flow schema never includes `name` for any domain.**
    #    `generate_schema(domain, flow_type)` (`template/config_flow.py`) only
    #    adds `CONF_NAME` `if flow_type == "config"`; `options_schema =
    #    partial(generate_schema, flow_type="options")` never does. That's the
    #    verbatim `"extra keys not allowed @ data['name']"` 400 CI hit --
    #    UPDATE must submit the domain's own fields MINUS `name`.
    # 3. **`name` is NOT lost by omitting it from an update.** The entry's
    #    `title` (and hence `options["name"]`, since `async_config_entry_title`
    #    reads `options["name"]` and `SchemaConfigFlowHandler.async_create_entry`
    #    stores `options=data` verbatim on CREATE) is preserved server-side:
    #    `SchemaCommonFlowHandler._update_and_remove_omitted_optional_keys`
    #    only prunes/overwrites keys that appear in the CURRENT step's schema;
    #    since `name` was never in the options-flow schema to begin with, the
    #    pre-existing `name` (and `template_type`, likewise server-injected
    #    and absent from the options-flow schema) survive an update untouched.
    #    Hassle therefore never needs to (and must not try to) push `name`
    #    through the options flow.
    # 4. **Renames are out of scope for the options flow, by construction.**
    #    HA does expose an explicit entry-rename primitive
    #    (`config_entries/update`, WS, `vol.Optional("title")`,
    #    `homeassistant/components/config/config_entries.py`) -- the
    #    mechanism the UI's "rename" affordance uses. Hassle does not call it:
    #    since `identity = slugify(name)` (MILESTONES M10, re-frozen §26.6), a
    #    changed local `name` is a changed `object_key`, which the plan engine
    #    already treats as delete-old + create-new (or an id-collision
    #    conflict) like every other kind -- there is no code path where an
    #    UPDATE entry (same object_key, hence same `name`) would ever need to
    #    change the title. Recorded here rather than wired up, since wiring an
    #    unused rename path would be untested dead code.

    async def _template_entry_domains(self) -> dict[str, str]:
        """`entry_id -> HA entity domain` for every template config entry,
        by cross-referencing the entity registry (docs/ha-api-notes.md
        §26.6): each template config entry creates exactly one entity, and
        its registry row's `config_entry_id` links back to the entry."""
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
        options-flow's suggested values (docs/ha-api-notes.md §26.7 -- there
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
            # (docs/ha-api-notes.md §26.7). Best-effort: an already-expired
            # flow 404ing on cancel is not this call's problem to raise.
            with contextlib.suppress(HaApiError):
                await self._client.rest_delete(f"/api/config/config_entries/options/flow/{flow_id}")

    async def _alist_template_helpers(self, kind: str) -> dict[str, dict[str, Any]]:
        wanted_domain = _TEMPLATE_FLOW_TYPE[kind]
        entries = await self._client.ws_command("config_entries/get")
        entry_domains = await self._template_entry_domains()
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
                "docs/ha-api-notes.md §26.6)"
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
        # smuggled in (§26.6 correction 1).
        result = await self._client.rest_post(
            f"/api/config/config_entries/flow/{flow_id}", json=dict(config)
        )
        # Flat create_entry body (docs/ha-api-notes.md §26.1): `entry_id` is a
        # top-level key, not nested under a "result" wrapper (that was the
        # original, incorrect WS-envelope assumption).
        entry_id = str(result.get("entry_id", flow_id))
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
                "target an existing entry (options-flow update, never a recreate, I2 analog)"
            )
        missing = [f for f in _TEMPLATE_REQUIRED_FIELDS[kind] if config.get(f) is None]
        if missing:
            raise ValueError(
                f"{kind} config is missing required field(s) {missing} "
                "(HA's template form schema rejects the submission without them, "
                "docs/ha-api-notes.md §26.6)"
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

    # -- registry snapshot (DESIGN §9.2) ----------------------------------

    def fetch_registry_snapshot(self) -> RegistrySnapshot:
        return self._run(self._afetch_registry_snapshot())

    # Scopes to fetch into the registry snapshot (docs/ha-api-notes.md
    # §31.2/§31.6, source-verified -- corrects the earlier "helpers have no
    # category-registry scope" belief, §31.5a): `automation`/`script` place
    # by their own scope; ALL 13 helper kinds share the one `"helpers"` scope.
    # Bundle PLACEMENT for helpers is unchanged this round (M15 work item A;
    # work item B's job) -- this is just the read path making the data
    # available in the snapshot.
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
        # HA's device registry keys each row as `id`; the snapshot model (and the
        # M3 fixture) use `device_id` (docs/ha-api-notes.md §5).
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

    # -- M11: category write-back on push-create --------------------------
    #
    # Additive, non-`Backend`-Protocol surface (same `entry_id_for`/
    # `fetch_registry_snapshot` pattern) driving `hassle.sync.
    # category_writeback.attempt_category_writeback` (CREATE) and `hassle.
    # sync.category_move.sync_category_on_move` (UPDATE, M15). Shapes are
    # source-verified against HA core's `homeassistant/components/config/
    # category_registry.py` / `entity_registry.py` (docs/ha-api-notes.md §31 --
    # corrects §30's inferred-but-untested wholesale-replace assumption).

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
        (docs/ha-api-notes.md §31.5c: confirmed to exist,
        `websocket_delete_category`, `{scope, category_id}` -- corrects §30's
        "not confirmed" caveat that had integration teardown suppressing any
        error from calling it)."""
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

        **Single-scope merge payload, no read-first** (docs/ha-api-notes.md
        §31.3/§31.5b, source-verified -- corrects §30's inferred
        wholesale-replace assumption): `config/entity_registry/update`'s
        `categories` handler merges per-scope SERVER-SIDE ("If passed in, we
        update/adjust only the provided scope(s). Other category scopes in
        the entity, are left as is." -- HA core's own comment). M11's
        original client-side read-then-merge is therefore unnecessary (though
        harmless/idempotent, §30's own pre-declared contingency) -- this just
        sends `{scope: category_id}`, and `category_id=None` UNSETS that
        scope (the `{scope: None}` primitive §31.3 confirms), used by
        `hassle.sync.category_move` for a local move to the `misc.py`
        fallback.

        **Identity anchor** (docs/ha-api-notes.md §2/§22, widened by M15
        §31.6): `unique_id == identity` for automations/scripts/storage
        helpers; a TEMPLATE_DOMAINS kind has no settable `unique_id` at all
        (§26.6) and is instead found via `config_entry_id` -> the cached
        HA-assigned `entry_id` (`self._template_entry_ids`).

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

    def _entity_registry_matcher(self, kind: str, identity: str):
        """The predicate identifying `kind:identity`'s entity-registry row
        among `config/entity_registry/list`'s rows (docs/ha-api-notes.md
        §31.6): `config_entry_id` for a TEMPLATE_DOMAINS kind (no settable
        `unique_id`, §26.6), else `unique_id == identity`."""
        if kind in TEMPLATE_DOMAINS:
            entry_id = self._template_entry_ids.get((kind, identity))
            if entry_id is None:
                return None

            def _matches_entry(entity: dict[str, Any]) -> bool:
                return str(entity.get("config_entry_id")) == entry_id

            return _matches_entry

        def _matches_unique_id(entity: dict[str, Any]) -> bool:
            return str(entity.get("unique_id")) == identity

        return _matches_unique_id

    async def _find_entity_registry_row(self, kind: str, identity: str) -> str | None:
        matcher = self._entity_registry_matcher(kind, identity)
        if matcher is None:
            return None
        entities = await self._client.ws_command("config/entity_registry/list")
        for entity in entities:
            if matcher(entity):
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
        Same identity anchor as `_aassign_category` (§31.6): `config_entry_id`
        for a TEMPLATE_DOMAINS kind, else `unique_id == identity`."""
        matcher = self._entity_registry_matcher(kind, identity)
        if matcher is None:
            return {}
        entities = self._run(self._client.ws_command("config/entity_registry/list"))
        for entity in entities:
            if matcher(entity):
                return dict(entity.get("categories") or {})
        return {}

    # -- purpose vocabulary (DESIGN §4; captured M6) ----------------------

    def fetch_purpose_vocabulary(self) -> PurposeVocabulary:
        return self._run(self._afetch_purpose_vocabulary())

    async def _afetch_purpose_vocabulary(self) -> PurposeVocabulary:
        # The 2026.7 UI enumerates purpose-specific trigger/condition types via
        # these subscriptions: each acks then pushes a `{type: description}`
        # snapshot event (docs/ha-api-notes.md §17). The vocabulary is the keys.
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

        Requires the plural block keys (docs/ha-api-notes.md §6); returns HA's
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

    # -- service calls (M7: `hassle run --live`, DESIGN §10.4) -------------

    def call_service(self, domain: str, service: str, **data: Any) -> Any:
        """Call `{domain}.{service}` via `POST /api/services/{domain}/{service}`.

        Additive (M7): the shadow-automation live-run flow needs to trigger
        `automation.trigger` with `skip_condition` explicitly set
        (docs/ha-api-notes.md §10.6) -- not previously exposed since M6's own
        test suite never needed a generic service-call passthrough.
        """
        return self._run(self._client.rest_post(f"/api/services/{domain}/{service}", json=data))

    # -- misc read helpers -------------------------------------------------

    def states(self) -> list[dict[str, Any]]:
        return self._run(self._client.rest_get("/api/states"))

    def entity_registry(self) -> list[dict[str, Any]]:
        return self._run(self._client.ws_command("config/entity_registry/list"))

    # -- media source (for the mirror; DESIGN §8.5) -----------------------

    def media_upload(self, folder: str, filename: str, data: bytes, content_type: str) -> str:
        return self._run(self._amedia_upload(folder, filename, data, content_type))

    async def _amedia_upload(
        self, folder: str, filename: str, data: bytes, content_type: str
    ) -> str:
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("media_content_id", f"media-source://media_source/local/{folder}")
        form.add_field("file", data, filename=filename, content_type=content_type)
        result = await self._client.rest_post_multipart(
            "/api/media_source/local_source/upload", form
        )
        return str(result["media_content_id"])

    def media_resolve(self, media_content_id: str) -> tuple[str, str]:
        result = self._run(
            self._client.ws_command("media_source/resolve_media", media_content_id=media_content_id)
        )
        return str(result["url"]), str(result.get("mime_type", ""))

    def media_download(self, url: str) -> bytes:
        return self._run(self._client.rest_get(url, expect="bytes"))

    def media_remove(self, media_content_id: str) -> None:
        self._run(
            self._client.ws_command(
                "media_source/local_source/remove", media_content_id=media_content_id
            )
        )

    # -- internal ----------------------------------------------------------

    def _require_kind(self, kind: str) -> None:
        if kind not in OBJECT_KINDS:
            raise ValueError(
                f"unknown object kind {kind!r} (expected one of {sorted(OBJECT_KINDS)})"
            )

    @property
    def helper_domains(self) -> frozenset[str]:
        return HELPER_DOMAINS
