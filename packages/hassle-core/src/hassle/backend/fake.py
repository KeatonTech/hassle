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
on the same four `Backend` methods, but internally drive a simulated REST
config-entry flow (create — menu step `step_id="user"` choosing the template
type, then a form step collecting fields, `type: "create_entry"` result) /
options-flow (update — one form step re-collecting the same fields,
`type: "create_entry"` result merges into `entry.options`) instead of the
storage-collection WS API (docs/ha-api-notes.md §26 records the real shapes
this models — flow/options-flow/removal are REST, §26.0; CI's integration
suite is the authoritative verification against real HA per MILESTONES M10).
Delete is config-entry removal (REST `DELETE .../entry/{entry_id}`).

**Identity (redesigned 2026-07-05, docs/ha-api-notes.md §26.6): there is no
`unique_id`.** CI found the real form schema rejects an unrecognized
`unique_id` key outright. Object identity is derived from the submitted
`name` (slugified) -- mirroring the storage helpers' "id is a slug of name"
rule, except here it is the ONLY identity source. The config entry's
HA-assigned `entry_id` is tracked internally (`self._entry_ids`) exactly the
way a real sync engine would persist it in the manifest — never in the
stored config body itself (module docstring above, docs/backend.md's
config-entry addendum).

**Required write-target fields (CI finding, docs/ha-api-notes.md §26.6):** a
`template_number`'s form requires `set_value`; a `template_select`'s form
requires `select_option` (alongside `options`). Missing either raises
`ConfigEntryFlowError`, mirroring HA's real `400 {"errors": {"set_value":
"required key not provided"}}` rejection (modeled as an exception here since
`create`/`update` are single-shot, not step-by-step — module note below).

**Options-flow schema never includes `name` (CI round 3 finding, docs/
ha-api-notes.md §26.7).** Real HA's `generate_schema(domain, flow_type)`
(`template/config_flow.py`) only adds the name field `if flow_type ==
"config"` — the options flow's schema (`flow_type="options"`) never has it,
so submitting `name` in an UPDATE 400s with `"extra keys not allowed @
data['name']"`. `_update_via_options_flow` reproduces this rejection
(`ConfigEntryFlowError`); `name` (and the server-injected `template_type`)
survive an update untouched regardless, since real HA only overwrites keys
that appear in the CURRENT step's schema (`_update_and_remove_omitted_
optional_keys`) — `FakeBackend` reproduces that too, merging the submitted
fields into the existing stored options rather than replacing the dict
outright, so `list_remote` after an update still has `name` (docs/
ha-api-notes.md §26.7 findings 2-3; `test_template_number_update_rejects_name_field`,
`test_template_number_update_preserves_name_without_resubmitting_it`).

**`template_number`'s `min`/`max`/`step` are float-coerced on write (CI round
4 finding, docs/ha-api-notes.md §26.10).** HA's `NumberSelector` (the form
field type for these three) unconditionally runs the submitted value through
`vol.Coerce(float)` and stores the result -- an `int` submission is stored as
a `float` regardless. `_coerce_number_selector_fields` reproduces this on
both create and update so `list_remote` returns what real HA actually
stores; the compiler (`hassle.compiler.template_helpers`) coerces the same
fields at compile time so the compiled local IR is byte-identical, keeping
plan comparison a plain hash equality with no special case.

**M11: category registry + per-entity category assignment.** Additive,
non-`Backend`-Protocol surface (same pattern as `entry_id_for`/
`fetch_registry_snapshot`) modeling `config/category_registry/list|create`
and `config/entity_registry/update`'s `categories` field (docs/ha-api-notes.md
§30) well enough for `hassle.sync.category_writeback` to drive against it in
unit tests: `list_categories`/`create_category` per scope
(`self._categories: dict[scope, dict[category_id, name]]`), and
`assign_category`/`categories_for` per `(kind, identity)`
(`self._entity_categories`) -- FakeBackend doesn't model real entity_ids at
all (no automation/script entity_id synthesis exists elsewhere in this class
either), so category assignment is keyed directly by `(kind, identity)`
rather than round-tripping through a simulated entity registry row; this is
an internal simplification, like the helper-id-from-name-slug shortcut
above, not a claim about HA's wire shape (`DirectBackend` -- the real
transport -- does look the entity up by `unique_id`, docs/ha-api-notes.md
§30). `seed_category` is test-only sugar for pre-populating a category
before a push (MILESTONES M11 test 1's "category already exists" case).
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

# Fields HA's form schema requires beyond `name`/`state` (docs/ha-api-notes.md
# §26.6): a template number needs a write target (`set_value`); a template
# select needs both the option list (`options`) and its write target
# (`select_option`). Sensor/binary_sensor are read-only -- no extra required
# field.
_TEMPLATE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "template_number": ("set_value",),
    "template_sensor": (),
    "template_binary_sensor": (),
    "template_select": ("options", "select_option"),
}


def _check_required_fields(kind: str, config: dict[str, Any]) -> None:
    missing = [f for f in _TEMPLATE_REQUIRED_FIELDS[kind] if config.get(f) is None]
    if missing:
        raise ConfigEntryFlowError(
            f"{kind} form rejected: required key(s) not provided: {missing} "
            f"(mirrors HA's real 400 {{'errors': {{'<field>': 'required key not "
            "provided'}}}} form-schema rejection, docs/ha-api-notes.md §26.6)"
        )


# `template_number`'s `min`/`max`/`step` are the ONLY numeric fields across
# the four template domains HA's form schema types as `NumberSelector`
# (CI round 4, docs/ha-api-notes.md §26.10 -- confirmed by reading every
# domain's schema in `template/config_flow.py`: sensor/binary_sensor/select
# have no numeric fields at all). `NumberSelector.__call__`
# (`homeassistant/helpers/selector.py`) unconditionally runs the submitted
# value through `vol.Coerce(float)` and stores the result, regardless of
# what was submitted -- so real HA always stores these three as floats.
_NUMBER_SELECTOR_FIELDS: dict[str, tuple[str, ...]] = {
    "template_number": ("min", "max", "step"),
    "template_sensor": (),
    "template_binary_sensor": (),
    "template_select": (),
}


def _coerce_number_selector_fields(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """Mirror HA's `NumberSelector` float coercion (docs/ha-api-notes.md
    §26.10) on the fields it actually applies to for `kind` -- storing floats
    the same way real HA does, so a compiled `int` local value and the
    (fixed, §26.10) stored remote value hash-compare equal only when they
    really are byte-identical, exactly matching production behavior instead
    of silently tolerating a mismatch the compiler is responsible for fixing."""
    coerced = dict(config)
    for field_name in _NUMBER_SELECTOR_FIELDS[kind]:
        if field_name in coerced and coerced[field_name] is not None:
            coerced[field_name] = float(coerced[field_name])
    return coerced


def _empty_str_list() -> list[str]:
    return []


@dataclass
class FlowStep:
    """One step of a simulated `config_entries/flow` (or `.../options/flow`)
    interaction, mirroring HA's real WS flow shapes (docs/ha-api-notes.md
    §26): `type` is `"menu"` | `"form"` | `"create_entry"` | `"abort"`."""

    flow_id: str
    type: str
    step_id: str | None = None
    menu_options: list[str] = field(default_factory=_empty_str_list)
    data_schema: list[str] = field(default_factory=_empty_str_list)
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
        # the stored config body) -- (kind, name-derived identity) -> entry_id.
        self._entry_ids: dict[tuple[str, str], str] = {}
        self._entry_id_counter = 0
        # Every simulated flow step this backend has driven, in order --
        # asserted on by the FakeBackend flow-shape tests (menu -> form ->
        # create_entry / options-flow form -> create_entry) so the shapes
        # themselves are test-visible, not just their net effect on the store.
        self.flow_log: list[FlowStep] = []
        # M11: category registry per scope (scope -> {category_id: name}) and
        # per-object category assignment ((kind, identity) -> {scope:
        # category_id}) -- see module docstring's M11 paragraph.
        self._categories: dict[str, dict[str, str]] = {}
        self._category_id_counter = 0
        self._entity_categories: dict[tuple[str, str], dict[str, str]] = {}

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
            # `update()`'s contract (F2) still takes the FULL local config,
            # same as every other kind -- `name` is stripped here, at the
            # public-API boundary, before it ever reaches the simulated
            # options-flow submission, exactly mirroring `DirectBackend.
            # _aupdate_template_helper` (docs/ha-api-notes.md §26.7: the
            # options-flow schema never includes `name`, so a caller must
            # never be able to leak it onto the wire through this path).
            payload = {k: v for k, v in config.items() if k != "name"}
            self._update_via_options_flow(kind, identity, payload)
            return
        normalized = normalize_ha(config, kind=kind)
        normalized = self._stored_body(kind, identity, normalized)
        self._store[kind][identity] = normalized
        self._writes += 1

    # -- M10: config-entry template-helper flows --------------------------
    #
    # Modeled on the real REST flow (create: POST /api/config/config_entries/
    # flow[/{flow_id}]) and options-flow (update: POST /api/config/
    # config_entries/options/flow[/{flow_id}]) shapes (docs/ha-api-notes.md
    # §26, §26.0 correction: these are REST, NOT WebSocket -- an earlier
    # revision of this module modeled them as WS commands, which CI found
    # failed identically on real HA stable+dev with "Unknown command"): a
    # menu step choosing the template type, then a form step collecting
    # fields, ending in a flat `type: "create_entry"` body whose `options` is
    # exactly what the integration stores. Identity is derived from `name`
    # (§26.6 -- there is no settable `unique_id`); the flow's `create_entry`
    # result carries a fresh `entry_id` HA assigns (never caller-supplied,
    # mirrors §17.5's "creation assigns identity" rule for storage helpers)
    # -- tracked here, never in the stored options body.

    def _next_entry_id(self) -> str:
        self._entry_id_counter += 1
        return f"entry_{self._entry_id_counter:04d}"

    def _create_via_flow(self, kind: str, config: dict[str, Any]) -> str:
        name = config.get("name")
        if not name:
            raise ValueError(f"{kind} config has no 'name' (required to derive identity/title)")
        identity = _slugify(str(name))
        if (kind, identity) in self._entry_ids:
            raise ConfigEntryFlowError(
                f"a {kind} config entry titled {name!r} already exists "
                "(CREATE-collision -- the flow would need to be aborted, not overwrite)"
            )
        _check_required_fields(kind, config)

        flow_id = f"flow_{self._next_entry_id()}"
        menu_step = FlowStep(
            flow_id=flow_id,
            type="menu",
            step_id="user",
            menu_options=sorted(_TEMPLATE_FLOW_TYPE.values()),
        )
        self.flow_log.append(menu_step)

        # `unique_id` is NEVER part of the form's data_schema/submission
        # (docs/ha-api-notes.md §26.6: real HA rejects it as an extra key).
        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_TEMPLATE_FLOW_TYPE[kind],
            data_schema=sorted(config),
        )
        self.flow_log.append(form_step)

        # HA's NumberSelector float-coerces min/max/step on the way in
        # (docs/ha-api-notes.md §26.10) -- store what real HA would store,
        # not the caller's raw submission.
        options = _coerce_number_selector_fields(kind, config)
        entry_id = self._next_entry_id()
        # Flat body (no nested "result" wrapper) -- the REST create_entry
        # response is `{"type": "create_entry", "flow_id", "entry_id",
        # "title", "options", ...}` directly, not a WS-style
        # `{"result": {...}}` envelope (docs/ha-api-notes.md §26.0/§26.1).
        # `title` is what HA actually sets from the submitted `name` -- the
        # wire-level correlator now that there is no settable unique_id
        # (§26.6).
        result_step = FlowStep(
            flow_id=flow_id,
            type="create_entry",
            result={"entry_id": entry_id, "title": str(name), "options": dict(options)},
        )
        self.flow_log.append(result_step)

        self._entry_ids[(kind, identity)] = entry_id
        self._store[kind][identity] = options
        self._writes += 1
        return identity

    def _update_via_options_flow(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        entry_id = self._entry_ids.get((kind, identity))
        if entry_id is None:
            raise ValueError(
                f"no config entry tracked for {kind}:{identity} -- an UPDATE must "
                "target an existing entry (options-flow update, never a recreate, I2 analog)"
            )
        # `name` is REJECTED by the real options-flow schema outright (CI
        # round 3, docs/ha-api-notes.md §26.7 finding 2): `generate_schema`
        # only adds the name field for `flow_type == "config"`, never
        # `"options"`. Mirrors HA's real `400 {"errors": {"base": ["extra
        # keys not allowed @ data['name']"]}}`.
        if "name" in config:
            raise ConfigEntryFlowError(
                f"{kind} options-flow form rejected: extra keys not allowed @ data['name'] "
                "(the options-flow schema never includes `name` -- it is create-only and "
                "becomes the entry's title, docs/ha-api-notes.md §26.7)"
            )
        _check_required_fields(kind, config)
        flow_id = f"optflow_{entry_id}"
        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_TEMPLATE_FLOW_TYPE[kind],
            data_schema=sorted(config),
        )
        self.flow_log.append(form_step)

        # Real HA MERGES the submitted fields into the entry's existing
        # options rather than replacing the dict outright (docs/
        # ha-api-notes.md §26.7 finding 3: `_update_and_remove_omitted_
        # optional_keys` only touches keys present in the CURRENT step's
        # schema) -- `name`/`template_type` (never part of the options-flow
        # schema) survive an update untouched. HA's NumberSelector
        # float-coerces min/max/step on the way in too (§26.10), same as create.
        existing = self._store[kind].get(identity, {})
        options = {**existing, **_coerce_number_selector_fields(kind, config)}
        result_step = FlowStep(
            flow_id=flow_id,
            type="create_entry",
            result={"entry_id": entry_id, "options": dict(options)},
        )
        self.flow_log.append(result_step)

        # entry_id is UNCHANGED (I2 analog: an options-update never recreates
        # the entry) -- only the options body is updated. Note: real HA's
        # options-flow submission for `template` still cannot rename the
        # entry's title via a `name` change without special handling; Hassle
        # treats the object key (identity) as fixed once created (matching
        # every other kind -- a rename is a delete+recreate under a new key,
        # never an in-place identity change, I2's spirit).
        self._store[kind][identity] = options
        self._writes += 1

    def entry_id_for(self, kind: str, identity: str) -> str | None:
        """Test/CLI-facing lookup of a template helper's HA-assigned
        `entry_id` (manifest-only in the real sync engine, docs/backend.md)."""
        return self._entry_ids.get((kind, identity))

    # -- M11: category registry + per-entity category assignment ----------

    def list_categories(self, scope: str) -> dict[str, str]:
        """`config/category_registry/list` for `scope` -- `{category_id: name}`
        (additive, non-`Backend`-Protocol; module docstring's M11 paragraph)."""
        return dict(self._categories.get(scope, {}))

    def create_category(self, scope: str, name: str) -> str:
        """`config/category_registry/create` -- returns the new `category_id`."""
        self._category_id_counter += 1
        category_id = f"cat_{self._category_id_counter:04d}"
        self._categories.setdefault(scope, {})[category_id] = name
        return category_id

    def assign_category(self, kind: str, identity: str, scope: str, category_id: str) -> None:
        """`config/entity_registry/update`'s `categories` field, scoped merge
        (never drops another scope's existing assignment on the same object,
        I6 -- mirrors the merge `DirectBackend._aassign_category` does against
        the real entity-registry row before resubmitting the whole dict)."""
        existing = dict(self._entity_categories.get((kind, identity), {}))
        existing[scope] = category_id
        self._entity_categories[(kind, identity)] = existing

    def categories_for(self, kind: str, identity: str) -> dict[str, str]:
        """Test-facing lookup: the current `{scope: category_id}` assignment
        for `kind:identity` (empty if never assigned)."""
        return dict(self._entity_categories.get((kind, identity), {}))

    def seed_category(self, scope: str, category_id: str, name: str) -> None:
        """Test-only sugar: pre-populate a category registry row (MILESTONES
        M11 test 1's "category already exists" case) with a caller-chosen,
        stable `category_id` rather than the auto-generated `cat_NNNN` shape
        `create_category` would assign."""
        self._categories.setdefault(scope, {})[category_id] = name

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
            # is retired -- a later re-CREATE under the same name-derived
            # identity gets a FRESH entry_id (the "entry_id-changes" rollback
            # caveat, DESIGN §13 amendment / MILESTONES M10 test 4).
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
