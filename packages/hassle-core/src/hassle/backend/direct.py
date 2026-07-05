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
"""

from __future__ import annotations

import asyncio
import threading
from types import TracebackType
from typing import Any, cast

from hassle.backend.client import HaClient
from hassle.backend.errors import HaApiError
from hassle.backend.version import version_warning
from hassle.ir.keys import HELPER_DOMAINS, OBJECT_KINDS
from hassle.ir.keys import slugify as _slugify
from hassle.registry.snapshot import PurposeVocabulary, RegistrySnapshot


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
        return self._run(self._alist_helpers(kind))

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self._require_kind(kind)
        if kind == "automation":
            return self._run(self._awrite_automation(config))
        if kind == "script":
            return self._run(self._awrite_script(config))
        return self._run(self._acreate_helper(kind, config))

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        self._require_kind(kind)
        if kind == "automation":
            self._run(self._awrite_automation({**config, "id": identity}))
        elif kind == "script":
            self._run(self._awrite_script({**config, "id": identity}))
        else:
            self._run(self._aupdate_helper(kind, identity, config))

    def delete(self, kind: str, identity: str) -> None:
        self._require_kind(kind)
        if kind == "automation":
            self._run(self._adelete_config("automation", identity))
        elif kind == "script":
            self._run(self._adelete_config("script", identity))
        else:
            self._run(self._client.ws_command(f"{kind}/delete", **{f"{kind}_id": identity}))

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

    # -- registry snapshot (DESIGN §9.2) ----------------------------------

    def fetch_registry_snapshot(self) -> RegistrySnapshot:
        return self._run(self._afetch_registry_snapshot())

    # Scopes DESIGN §7.3 places by category: automations and scripts (helpers
    # have no category-registry scope in HA -- they place by domain default).
    _CATEGORY_SCOPES = ("automation", "script")

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
