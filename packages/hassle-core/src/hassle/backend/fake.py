"""`FakeBackend` — in-memory `Backend` for M5 (DESIGN §8, docs/ha-api-notes.md §11).

Seed data is hand-written Python modeled on the real capture shapes in
docs/ha-api-captures/ (not parsed at runtime — provenance noted per record
below), covering automations, scripts, and all nine storage-collection helper
domains (rest-ws-core.json records: `automation_create`/`automation_read_normalized`
for automations, `script_create`/`script_read_normalized` for scripts,
`helper_*_full_cycle` for the nine helper domains).

Two behaviors mirror real HA exactly (docs/ha-api-notes.md §10.1, §11):

- **Normalization on write.** `create`/`update` run the input through
  `hassle.ir.normalize_ha` before storing — legacy singular `trigger/condition/
  action` + `service:` becomes plural `triggers/conditions/actions` + `action:`,
  exactly like HA's real POST-then-GET round-trip
  (docs/ha-api-captures/normalize-post-get-pair.json). Without this, the plan
  engine would show spurious `update`s for every already-plural object.
- **Helper identity derivation.** A helper's `id` (if not supplied) is a slug
  of its `name` — real HA slugifies `name` into the storage-collection item id
  (docs/ha-api-notes.md §4: `"H bool"` -> `"h_bool"`). Real HA addresses
  update/delete via a `{domain}_id` payload key (quirk #1); `FakeBackend`
  reproduces this as an internal storage-organization detail even though the
  `Backend` Protocol's `update`/`delete` signatures are domain-shape-agnostic.

**M10: config-entry template-helper domains (`TEMPLATE_DOMAINS`)** are modeled
on the same four `Backend` methods, but internally drive a simulated
`config_entries/flow` (create — menu step `step_id="user"` choosing the
template type, then a form step collecting fields, `type: "create_entry"`
result) / `config_entries/options/flow` (update — one form step re-collecting
the same fields, `type: "create_entry"` result merges into `entry.options`)
instead of the storage-collection WS API (docs/ha-api-notes.md §26 records the
real shapes this models; CI's integration suite is the authoritative
verification against real HA per MILESTONES M10). Delete is config-entry
removal (`config_entries/remove`). Object identity is the declared
`unique_id`; the config entry's HA-assigned `entry_id` is tracked internally
(`self._entry_ids`) exactly the way a real sync engine would persist it in the
manifest — never in the stored config body itself (module docstring above,
docs/backend.md's config-entry addendum).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hassle.ir.canonical import sha256_hash
from hassle.ir.keys import HELPER_DOMAINS, OBJECT_KINDS, TEMPLATE_DOMAINS
from hassle.ir.keys import slugify as _slugify
from hassle.ir.normalize import normalize_ha

# The subset of a template helper's stored options body that identifies its
# "type" (the config flow's menu step, docs/ha-api-notes.md §26) --
# informational only, mirrors the real integration's step_id naming.
_TEMPLATE_FLOW_TYPE = {
    "template_number": "number",
    "template_sensor": "sensor",
    "template_binary_sensor": "binary_sensor",
    "template_select": "select",
}


@dataclass
class FlowStep:
    """One step of a simulated `config_entries/flow` (or `.../options/flow`)
    interaction, mirroring HA's real WS flow shapes (docs/ha-api-notes.md
    §26): `type` is `"menu"` | `"form"` | `"create_entry"` | `"abort"`."""

    flow_id: str
    type: str
    step_id: str | None = None
    menu_options: list[str] = field(default_factory=list)
    data_schema: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None


class ConfigEntryFlowError(Exception):
    """Raised when a simulated flow step is invalid (bad menu choice, missing
    required field) -- mirrors HA rejecting a flow step with an `errors` dict
    rather than crashing; modeled here as an exception since FakeBackend's
    `Backend`-facing methods (`create`/`update`) are single-shot, not
    step-by-step (see module docstring: the multi-step flow is an internal
    simulation detail the four `Backend` methods drive through to completion)."""


class FakeBackend:
    """In-memory `Backend` (structurally satisfies `hassle.backend.Backend`)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in OBJECT_KINDS}
        self._writes = 0
        # Settable by tests (MILESTONES M9 deliverable 4: `hassle doctor`'s
        # HA tested-version-range check, `hassle.backend.version`). `None`
        # (the default) mirrors "not connected / version unknown" -- no
        # warning is possible without a version to compare.
        self.ha_version: str | None = None
        # M10: config-entry template-helper bookkeeping. `entry_id` is
        # HA-side identity, tracked the way a real manifest would (never in
        # the stored config body) -- (kind, unique_id) -> entry_id.
        self._entry_ids: dict[tuple[str, str], str] = {}
        self._entry_id_counter = 0
        # Every simulated flow step this backend has driven, in order --
        # asserted on by the FakeBackend flow-shape tests (menu -> form ->
        # create_entry / options-flow form -> create_entry) so the shapes
        # themselves are test-visible, not just their net effect on the store.
        self.flow_log: list[FlowStep] = []

    # -- Backend protocol -------------------------------------------------

    def fetch_registry_snapshot(self):  # additive test/registry surface, not part of F2
        """Minimal registry snapshot (settable via `self.registry_snapshot`).

        Mirrors DirectBackend's non-protocol registry surface so CLI flows that
        refresh `.hassle/registry.json` on pull are exercisable offline.
        """
        from hassle.registry.snapshot import RegistrySnapshot

        snapshot = getattr(self, "registry_snapshot", None)
        return snapshot if snapshot is not None else RegistrySnapshot()

    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
        self._require_kind(kind)
        return {identity: dict(config) for identity, config in self._store[kind].items()}

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self._require_kind(kind)
        if kind in TEMPLATE_DOMAINS:
            return self._create_via_flow(kind, config)
        # normalize_ha only special-cases kind == "automation" (outer-key
        # pluralization); every other kind gets the same service:->action:
        # recursive rewrite, so passing `kind` straight through is correct.
        normalized = normalize_ha(config, kind=kind)
        identity = self._derive_identity(kind, normalized)
        normalized = self._stored_body(kind, identity, normalized)
        self._store[kind][identity] = normalized
        self._writes += 1
        return identity

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        self._require_kind(kind)
        if kind in TEMPLATE_DOMAINS:
            self._update_via_options_flow(kind, identity, config)
            return
        normalized = normalize_ha(config, kind=kind)
        normalized = self._stored_body(kind, identity, normalized)
        self._store[kind][identity] = normalized
        self._writes += 1

    # -- M10: config-entry template-helper flows --------------------------
    #
    # Modeled on the real `config_entries/flow` (create) and
    # `config_entries/options/flow` (update) WS shapes (docs/ha-api-notes.md
    # §26): a menu step choosing the template type, then a form step
    # collecting fields, ending in a `type: "create_entry"` result whose
    # `result.options` is exactly what the integration stores. Identity is
    # the declared `unique_id`; the flow's `create_entry` result carries a
    # fresh `entry_id` HA assigns (never caller-supplied, mirrors §17.5's
    # "creation assigns identity" rule for storage helpers) -- tracked here,
    # never in the stored options body.

    def _next_entry_id(self) -> str:
        self._entry_id_counter += 1
        return f"entry_{self._entry_id_counter:04d}"

    def _create_via_flow(self, kind: str, config: dict[str, Any]) -> str:
        unique_id = config.get("unique_id")
        if not unique_id:
            raise ValueError(
                f"{kind} config has no 'unique_id' (required to start the config-entry flow)"
            )
        identity = str(unique_id)
        if (kind, identity) in self._entry_ids:
            raise ConfigEntryFlowError(
                f"a {kind} config entry with unique_id {identity!r} already exists "
                "(CREATE-collision -- the flow would need to be aborted, not overwrite)"
            )

        flow_id = f"flow_{self._next_entry_id()}"
        menu_step = FlowStep(
            flow_id=flow_id,
            type="menu",
            step_id="user",
            menu_options=sorted(_TEMPLATE_FLOW_TYPE.values()),
        )
        self.flow_log.append(menu_step)

        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_TEMPLATE_FLOW_TYPE[kind],
            data_schema=sorted(k for k in config if k != "unique_id"),
        )
        self.flow_log.append(form_step)

        options = {k: v for k, v in config.items() if k != "unique_id"}
        entry_id = self._next_entry_id()
        result_step = FlowStep(
            flow_id=flow_id,
            type="create_entry",
            result={"entry_id": entry_id, "options": dict(options), "unique_id": identity},
        )
        self.flow_log.append(result_step)

        self._entry_ids[(kind, identity)] = entry_id
        stored = {"unique_id": identity, **options}
        self._store[kind][identity] = stored
        self._writes += 1
        return identity

    def _update_via_options_flow(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        entry_id = self._entry_ids.get((kind, identity))
        if entry_id is None:
            raise ValueError(
                f"no config entry tracked for {kind}:{identity} -- an UPDATE must "
                "target an existing entry (options-flow update, never a recreate, I2 analog)"
            )
        flow_id = f"optflow_{entry_id}"
        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_TEMPLATE_FLOW_TYPE[kind],
            data_schema=sorted(k for k in config if k != "unique_id"),
        )
        self.flow_log.append(form_step)

        options = {k: v for k, v in config.items() if k != "unique_id"}
        result_step = FlowStep(
            flow_id=flow_id,
            type="create_entry",
            result={"entry_id": entry_id, "options": dict(options)},
        )
        self.flow_log.append(result_step)

        # entry_id is UNCHANGED (I2 analog: an options-update never recreates
        # the entry) -- only the options body is replaced.
        stored = {"unique_id": identity, **options}
        self._store[kind][identity] = stored
        self._writes += 1

    def entry_id_for(self, kind: str, identity: str) -> str | None:
        """Test/CLI-facing lookup of a template helper's HA-assigned
        `entry_id` (manifest-only in the real sync engine, docs/backend.md)."""
        return self._entry_ids.get((kind, identity))

    def _stored_body(self, kind: str, identity: str, normalized: dict[str, Any]) -> dict[str, Any]:
        """The exact body real HA stores for one object of ``kind`` (the
        capture-verified read-back shape, docs/ha-api-captures/rest-ws-core.json
        ``script_read_normalized`` / ``automation_read_normalized`` /
        ``helper_*_full_cycle``):

        - Helpers store `id` in the body (`id` is an intrinsic
          :class:`HelperConfig` field) -- always set to the derived identity.
        - Scripts key by an EXTRINSIC object_id (no `id` field on
          :class:`ScriptConfig` at all); real HA's script config read-back
          never has `id` in the body, so any caller-supplied `id` in the
          input config (a natural mistake -- automations/helpers both DO take
          one) must be stripped here, never persisted, or local (`to_ha()`,
          no `id`) vs remote (this store, `id` leaked in) hash forever
          afterward, producing a phantom conflict/perpetual-update out of an
          untouched object (docs/ha-api-notes.md's pull-plan-noop finding).
        - Automations already carry `id` as part of the real input (intrinsic
          identity) -- passed through verbatim, no rewrite needed.
        """
        if kind in HELPER_DOMAINS:
            return {**normalized, "id": identity}
        if kind == "script":
            return {k: v for k, v in normalized.items() if k != "id"}
        return normalized

    def delete(self, kind: str, identity: str) -> None:
        self._require_kind(kind)
        self._store[kind].pop(identity, None)
        if kind in TEMPLATE_DOMAINS:
            # Config entry removal (docs/ha-api-notes.md §26): the entry_id
            # is retired -- a later re-CREATE under the same unique_id gets a
            # FRESH entry_id (the "entry_id-changes" rollback caveat, DESIGN
            # §13 amendment / MILESTONES M10 test 4).
            self._entry_ids.pop((kind, identity), None)
        self._writes += 1

    # -- test-only helpers --------------------------------------------------

    def writes_since_reset(self) -> int:
        return self._writes

    def reset_write_tracking(self) -> None:
        self._writes = 0

    def snapshot(self, kind: str) -> dict[str, dict[str, Any]]:
        """A deep-ish copy of the current store for a kind (for rollback tests)."""
        return {identity: dict(config) for identity, config in self._store[kind].items()}

    def restore(self, kind: str, snapshot: dict[str, dict[str, Any]]) -> None:
        self._store[kind] = {identity: dict(config) for identity, config in snapshot.items()}

    def hash_of(self, kind: str, identity: str) -> str | None:
        config = self._store[kind].get(identity)
        return None if config is None else sha256_hash(config)

    @classmethod
    def with_seed_data(cls) -> FakeBackend:
        """A FakeBackend pre-populated with realistic starting state, modeled on
        docs/ha-api-captures/rest-ws-core.json (automations, scripts, one item
        per helper domain)."""
        backend = cls()

        # rest-ws-core.json records "automation_create" / "automation_read_normalized"
        backend.create(
            "automation",
            {
                "id": "hassle_auto_demo",
                "alias": "Hassle Demo Automation",
                "description": "created by M0.V harness",
                "mode": "single",
                "trigger": [
                    {"platform": "state", "entity_id": "input_boolean.hassle_flag_2", "to": "on"}
                ],
                "condition": [],
                "action": [
                    {
                        "service": "input_boolean.turn_off",
                        "target": {"entity_id": "input_boolean.hassle_flag_2"},
                    }
                ],
            },
        )

        # rest-ws-core.json records "script_create" / "script_read_normalized"
        backend.create(
            "script",
            {
                "alias": "Hassle Demo Script",
                "mode": "single",
                "sequence": [
                    {
                        "service": "input_boolean.toggle",
                        "target": {"entity_id": "input_boolean.hassle_flag_2"},
                    }
                ],
            },
        )
        # Give the script a stable, known identity for seed consumers/tests.
        scripts = backend._store["script"]
        ((identity, config),) = list(scripts.items())
        del scripts[identity]
        scripts["hassle_script_demo"] = config

        # rest-ws-core.json "helper_input_boolean_full_cycle"
        backend.create(
            "input_boolean", {"id": "hassle_flag", "name": "Hassle Flag", "icon": "mdi:flag"}
        )
        # rest-ws-core.json "helper_input_number_full_cycle"
        backend.create(
            "input_number",
            {"id": "h_num", "name": "H num", "min": 0, "max": 100, "step": 1, "mode": "slider"},
        )
        # rest-ws-core.json "helper_input_select_full_cycle"
        backend.create("input_select", {"id": "h_sel", "name": "H sel", "options": ["a", "b", "c"]})
        # rest-ws-core.json "helper_input_text_full_cycle"
        backend.create("input_text", {"id": "h_text", "name": "H text", "min": 0, "max": 100})
        # rest-ws-core.json "helper_input_datetime_full_cycle"
        backend.create(
            "input_datetime", {"id": "h_dt", "name": "H dt", "has_date": True, "has_time": True}
        )
        # rest-ws-core.json "helper_input_button_full_cycle"
        backend.create("input_button", {"id": "h_btn", "name": "H btn"})
        # rest-ws-core.json "helper_counter_full_cycle"
        backend.create(
            "counter",
            {
                "id": "h_counter",
                "name": "H counter",
                "initial": 0,
                "step": 1,
                "minimum": 0,
                "maximum": 10,
            },
        )
        # rest-ws-core.json "helper_timer_full_cycle"
        backend.create("timer", {"id": "h_timer", "name": "H timer", "duration": "00:01:00"})
        # rest-ws-core.json "helper_schedule_full_cycle"
        backend.create(
            "schedule",
            {
                "id": "h_schedule",
                "name": "H schedule",
                "monday": [{"from": "08:00:00", "to": "17:00:00"}],
            },
        )

        backend.reset_write_tracking()
        return backend

    # -- internal ------------------------------------------------------------

    def _require_kind(self, kind: str) -> None:
        if kind not in OBJECT_KINDS:
            raise ValueError(
                f"unknown object kind {kind!r} (expected one of {sorted(OBJECT_KINDS)})"
            )

    def _derive_identity(self, kind: str, normalized: dict[str, Any]) -> str:
        if kind == "automation":
            return str(normalized.get("id") or _slugify(str(normalized.get("alias", "automation"))))
        if kind == "script":
            # Scripts are keyed by an extrinsic object_id HA doesn't invent from
            # the body; callers of FakeBackend.create for scripts should supply
            # one via config["id"] (mirroring the CLI layer choosing the object_id
            # before POSTing to /api/config/script/config/{object_id}).
            return str(normalized.get("id") or _slugify(str(normalized.get("alias", "script"))))
        if kind in HELPER_DOMAINS:
            supplied = normalized.get("id")
            if supplied:
                return str(supplied)
            return _slugify(str(normalized.get("name", kind)))
        raise ValueError(f"unknown object kind {kind!r}")
