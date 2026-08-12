"""`FakeBackend` — in-memory `Backend` (DESIGN §8, docs/internals/ha-api-notes.md §11).

Seed data is hand-written Python modeled on the real capture shapes in
docs/ha-api-captures/ (not parsed at runtime — provenance noted per record
below), covering automations, scripts, and all nine storage-collection helper
domains (rest-ws-core.json records: `automation_create`/`automation_read_normalized`
for automations, `script_create`/`script_read_normalized` for scripts,
`helper_*_full_cycle` for the nine helper domains).

Two behaviors mirror real HA exactly (docs/internals/ha-api-notes.md §10.1, §11):

- **Normalization on write.** `create`/`update` run the input through
  `hassle.ir.normalize_ha` before storing — legacy singular `trigger/condition/
  action` + `service:` becomes plural `triggers/conditions/actions` + `action:`,
  exactly like HA's real POST-then-GET round-trip
  (docs/ha-api-captures/normalize-post-get-pair.json). Without this, the plan
  engine would show spurious `update`s for every already-plural object.
- **Helper identity derivation.** A helper's `id` (if not supplied) is a slug
  of its `name` — real HA slugifies `name` into the storage-collection item id
  (docs/internals/ha-api-notes.md §4: `"H bool"` -> `"h_bool"`). Real HA addresses
  update/delete via a `{domain}_id` payload key (quirk #1); `FakeBackend`
  reproduces this as an internal storage-organization detail even though the
  `Backend` Protocol's `update`/`delete` signatures are domain-shape-agnostic.

**Config-entry template-helper domains (`TEMPLATE_DOMAINS`)** are modeled on
the same four `Backend` methods, but internally drive a simulated REST
config-entry flow (create — menu step `step_id="user"` choosing the template
type, then a form step collecting fields, `type: "create_entry"` result) /
options-flow (update — one form step re-collecting the same fields,
`type: "create_entry"` result merges into `entry.options`) instead of the
storage-collection WS API (docs/internals/ha-api-notes.md §26 records the real shapes
this models — flow/options-flow/removal are REST, §26.0, verified against
real HA by the integration suite). Delete is config-entry removal (REST
`DELETE .../entry/{entry_id}`).

**Identity: there is no `unique_id`** (docs/internals/ha-api-notes.md §26.6) — the real
form schema rejects an unrecognized `unique_id` key outright. Object identity
is derived from the submitted `name` (slugified) -- mirroring the storage
helpers' "id is a slug of name" rule, except here it is the ONLY identity
source. The config entry's HA-assigned `entry_id` is tracked internally
(`self._entry_ids`) exactly the way a real sync engine would persist it in
the manifest — never in the stored config body itself (docs/internals/backend-protocol.md's
config-entry addendum).

**Required write-target fields** (docs/internals/ha-api-notes.md §26.6): a
`template_number`'s form requires `set_value`; a `template_select`'s form
requires `select_option` (alongside `options`). Missing either raises
`ConfigEntryFlowError`, mirroring HA's real `400 {"errors": {"set_value":
"required key not provided"}}` rejection (modeled as an exception here since
`create`/`update` are single-shot, not step-by-step — module note below).

**Options-flow schema never includes `name`** (docs/internals/ha-api-notes.md §26.7).
Real HA's `generate_schema(domain, flow_type)` (`template/config_flow.py`)
only adds the name field `if flow_type == "config"` — the options flow's
schema (`flow_type="options"`) never has it, so submitting `name` in an
UPDATE 400s with `"extra keys not allowed @ data['name']"`.
`_update_via_options_flow` reproduces this rejection (`ConfigEntryFlowError`);
`name` (and the server-injected `template_type`) survive an update untouched
regardless, since real HA only overwrites keys that appear in the CURRENT
step's schema (`_update_and_remove_omitted_optional_keys`) — `FakeBackend`
reproduces that too, merging the submitted fields into the existing stored
options rather than replacing the dict outright, so `list_remote` after an
update still has `name` (docs/internals/ha-api-notes.md §26.7 findings 2-3;
`test_template_number_update_rejects_name_field`,
`test_template_number_update_preserves_name_without_resubmitting_it`).

**`template_number`'s `min`/`max`/`step` are float-coerced on write**
(docs/internals/ha-api-notes.md §26.10). HA's `NumberSelector` (the form field type for
these three) unconditionally runs the submitted value through
`vol.Coerce(float)` and stores the result -- an `int` submission is stored as
a `float` regardless. `_coerce_number_selector_fields` reproduces this on
both create and update so `list_remote` returns what real HA actually
stores; the compiler (`hassle.compiler.template_helpers`) coerces the same
fields at compile time so the compiled local IR is byte-identical, keeping
plan comparison a plain hash equality with no special case.

**Category registry + per-entity category assignment.** Additive,
non-`Backend`-Protocol surface (same pattern as `entry_id_for`/
`fetch_registry_snapshot`) modeling `config/category_registry/list|create`
and `config/entity_registry/update`'s `categories` field (docs/internals/ha-api-notes.md
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
transport -- does look the entity up by `unique_id`, docs/internals/ha-api-notes.md
§30). `seed_category` is test-only sugar for pre-populating a category
before a push (the "category already exists" case).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from hassle.blueprints import (
    INSTANCE_IDENTITY_FIELDS,
    blueprint_display_path,
    blueprint_metadata,
    blueprint_remote_body,
    parse_blueprint,
)
from hassle.ir.canonical import sha256_hash
from hassle.ir.keys import (
    BLUEPRINT_KIND,
    DASHBOARD_KIND,
    GROUP_DOMAINS,
    HELPER_DOMAINS,
    OBJECT_KINDS,
    TEMPLATE_DOMAINS,
)
from hassle.ir.keys import slugify as _slugify
from hassle.ir.normalize import normalize_ha

# The subset of a template helper's stored options body that identifies its
# "type" (the config flow's menu step, docs/internals/ha-api-notes.md §26) --
# informational only, mirrors the real integration's step_id naming.
_TEMPLATE_FLOW_TYPE = {
    "template_number": "number",
    "template_sensor": "sensor",
    "template_binary_sensor": "binary_sensor",
    "template_select": "select",
}

# Fields HA's form schema requires beyond `name`/`state` (docs/internals/ha-api-notes.md
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

# The `group` integration's twelve flavors (docs/internals/ha-api-notes.md §38.1) -- the
# config-flow menu's `step_id` per flavor also equals the flavor name
# itself (§38.2), unlike template's `number`/`sensor`/`binary_sensor`/
# `select` naming.
_GROUP_FLAVOR: dict[str, str] = {
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
# own required-kwarg signatures (`hassle.compiler.group_helpers`); the only
# field HA's form schema requires that Hassle's own DSL leaves as a runtime
# check is `type` on `group_sensor` (docs/internals/ha-api-notes.md §38.1) -- mirrors
# `_TEMPLATE_REQUIRED_FIELDS` covering only the EXTRA required fields beyond
# the ones every domain already shares.
_GROUP_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    domain: ("type",) if domain == "group_sensor" else () for domain in GROUP_DOMAINS
}


def _check_required_fields(kind: str, config: dict[str, Any], required: tuple[str, ...]) -> None:
    missing = [f for f in required if config.get(f) is None]
    if missing:
        raise ConfigEntryFlowError(
            f"{kind} form rejected: required key(s) not provided: {missing} "
            f"(mirrors HA's real 400 {{'errors': {{'<field>': 'required key not "
            "provided'}}}} form-schema rejection, docs/internals/ha-api-notes.md §26.6/§38.1)"
        )


# `template_number`'s `min`/`max`/`step` are the ONLY numeric fields across
# the four template domains HA's form schema types as `NumberSelector`
# (docs/internals/ha-api-notes.md §26.10 -- confirmed by reading every domain's schema
# in `template/config_flow.py`: sensor/binary_sensor/select
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
    """Mirror HA's `NumberSelector` float coercion (docs/internals/ha-api-notes.md
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


# HA's own `url_path` for the default dashboard once it has a registry item
# (docs/internals/ha-api-notes.md §39.2). HA's migration creates it with
# `allow_single_word: True`, so it is exempt from the hyphen rule below --
# mirroring the same exemption in
# `hassle.compiler.dashboards.decorators.HA_DEFAULT_DASHBOARD_URL_PATH`
# (spelled separately: `hassle.backend` must not import `hassle.compiler`).
_HA_DEFAULT_DASHBOARD_URL_PATH = "lovelace"

# Registry fields HA's `dashboards/create` schema materializes when the caller
# omits them (docs/internals/ha-api-notes.md §39.1: every `create_*` capture in
# `dashboards-db0.json` comes back carrying both).
_DASHBOARD_CREATE_DEFAULTS: dict[str, Any] = {
    "show_in_sidebar": True,
    "require_admin": False,
}


def _dashboard_registry_stored_shape(
    envelope: dict[str, Any], *, creating: bool = False
) -> dict[str, Any]:
    """Mirror how HA's dashboard registry actually STORES a written item
    (docs/internals/ha-api-notes.md §39.1, DB0 captures `list_after_icon_null`
    and the `create_*` family).

    Two behaviors, both observed against HA 2026.7.4:

    - `lovelace/dashboards/update` merges (`{**item, **update}`) but an
      explicit `icon: null` REMOVES the key -- HA never persists a literal
      JSON `null` there, and `dashboards/list` accordingly never returns one.
      `DirectBackend._dashboard_registry_payload` sends `icon: None` on every
      update precisely to clear a deleted icon, so a fake that stored the
      envelope verbatim would report an `icon: None` key real HA cannot
      produce.
    - `lovelace/dashboards/create` materializes `show_in_sidebar: true` and
      `require_admin: false` when they are omitted (``creating=True``). Storing
      the envelope verbatim instead made a hand-authored `@dashboard` that
      omits those two kwargs show phantom UI drift on the first plan after its
      own push.

    Only `meta` is reshaped; the `config` blob is opaque and stored verbatim
    (§39.4 -- byte-verbatim, key order and all). A null `meta` is THE default
    dashboard, which has no registry item for either rule to apply to.
    """
    raw_meta = envelope.get("meta")
    if not isinstance(raw_meta, dict):
        return envelope
    meta = cast("dict[str, Any]", raw_meta)
    stored = {k: v for k, v in meta.items() if not (k == "icon" and v is None)}
    if creating:
        for field_name, default in _DASHBOARD_CREATE_DEFAULTS.items():
            stored.setdefault(field_name, default)
    if stored == meta:
        return envelope
    return {**envelope, "meta": stored}


def _empty_str_list() -> list[str]:
    return []


@dataclass
class FlowStep:
    """One step of a simulated `config_entries/flow` (or `.../options/flow`)
    interaction, mirroring HA's real WS flow shapes (docs/internals/ha-api-notes.md
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
        # Settable by tests (`hassle doctor`'s HA tested-version-range check,
        # `hassle.backend.version`). `None` (the default) mirrors "not
        # connected / version unknown" -- no warning is possible without a
        # version to compare.
        self.ha_version: str | None = None
        # Config-entry template-helper bookkeeping. `entry_id` is HA-side
        # identity, tracked the way a real manifest would (never in the
        # stored config body) -- (kind, name-derived identity) -> entry_id.
        self._entry_ids: dict[tuple[str, str], str] = {}
        self._entry_id_counter = 0
        # Config-entry group-helper bookkeeping -- a SEPARATE dict from
        # `_entry_ids` (never folded in), even though the entry_id counter is
        # shared: `entry_id_for`/`delete` need to know which of the two
        # families a `(kind, identity)` pair belongs to, and keeping the
        # tables apart mirrors keeping `TEMPLATE_DOMAINS`/`GROUP_DOMAINS`
        # apart in `hassle.ir.keys` (a separate set even though the apply
        # mechanics are near-identical).
        self._group_entry_ids: dict[tuple[str, str], str] = {}
        # Every simulated flow step this backend has driven, in order --
        # asserted on by the FakeBackend flow-shape tests (menu -> form ->
        # create_entry / options-flow form -> create_entry) so the shapes
        # themselves are test-visible, not just their net effect on the store.
        self.flow_log: list[FlowStep] = []
        # Category registry per scope (scope -> {category_id: name}) and
        # per-object category assignment ((kind, identity) -> {scope:
        # category_id}) -- see the module docstring's category-registry
        # paragraph.
        self._categories: dict[str, dict[str, str]] = {}
        self._category_id_counter = 0
        self._entity_categories: dict[tuple[str, str], dict[str, str]] = {}
        # `automation.reload` calls issued (blueprints-design §4.3). Additive
        # and non-Protocol, like `flow_log`: the apply-ordering tests assert
        # a blueprint UPDATE with live instances triggers exactly one.
        self.automation_reloads = 0
        # Post-save blueprint staleness (ha-api-notes §40.8). While positive,
        # each `blueprint_substitute` call serves the document as it was
        # BEFORE the most recent save and decrements this -- modelling the
        # real HA window a plan run seconds after a push falls into. Zero (the
        # default) means every read is fresh, so no existing test changes.
        self.blueprint_stale_reads = 0
        # identity -> the source this blueprint had before its last update.
        self._blueprint_previous: dict[str, str] = {}
        # Every settle wait `apply_plan` asked for before a post-update
        # `automation.reload` (ha-api-notes §40.8), in order. The fake NEVER
        # actually sleeps -- R2's "no network in unit tests" applied to the
        # clock -- so a test can assert the exact wait sequence, and the
        # common path (HA already fresh) provably costs nothing.
        self.blueprint_settle_waits: list[float] = []

    # -- Backend protocol ---------------------------------------------------

    def fetch_registry_snapshot(self):  # additive test/registry surface, not part of the protocol
        """Minimal registry snapshot (settable via `self.registry_snapshot`).

        Mirrors DirectBackend's non-protocol registry surface so CLI flows that
        refresh `.hassle/registry.json` on pull are exercisable offline.
        """
        from hassle.registry.snapshot import RegistrySnapshot

        snapshot = getattr(self, "registry_snapshot", None)
        return snapshot if snapshot is not None else RegistrySnapshot()

    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
        self._require_kind(kind)
        if kind == BLUEPRINT_KIND:
            # METADATA ONLY (docs/internals/blueprints-design.md §2.1): HA has
            # no command that serves a blueprint's source back, so a remote
            # body physically cannot carry one. The projection happens HERE,
            # at the one place a caller can observe the remote side, even
            # though the store holds the whole document -- that asymmetry is
            # exactly real HA's, and it is what makes this kind
            # push-authoritative.
            return {
                identity: blueprint_remote_body(
                    str(stored["domain"]),
                    str(stored["path"]),
                    blueprint_metadata(str(stored["source"]), display_path=identity),
                )
                for identity, stored in self._store[kind].items()
            }
        return {identity: dict(config) for identity, config in self._store[kind].items()}

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self._require_kind(kind)
        if kind in TEMPLATE_DOMAINS:
            return self._create_via_flow(kind, config)
        if kind in GROUP_DOMAINS:
            return self._create_group_via_flow(kind, config)
        if kind == DASHBOARD_KIND:
            return self._create_dashboard(config)
        if kind == BLUEPRINT_KIND:
            return self._create_blueprint(config)
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
            # `update()`'s contract still takes the FULL local config, same
            # as every other kind -- `name` is stripped here, at the
            # public-API boundary, before it ever reaches the simulated
            # options-flow submission, exactly mirroring `DirectBackend.
            # _aupdate_template_helper` (docs/internals/ha-api-notes.md §26.7: the
            # options-flow schema never includes `name`, so a caller must
            # never be able to leak it onto the wire through this path).
            payload = {k: v for k, v in config.items() if k != "name"}
            self._update_via_options_flow(kind, identity, payload)
            return
        if kind in GROUP_DOMAINS:
            # `update()`'s contract still takes the FULL local config, same
            # as every other kind -- `name` is stripped here, at the
            # public-API boundary, before it ever reaches the simulated
            # options-flow submission, exactly mirroring the TEMPLATE_DOMAINS
            # branch above (docs/internals/ha-api-notes.md §38.1: the group
            # options-flow schema does NOT include `name` either -- same rule
            # as template, §26.7 finding 2 -- real HA 400s
            # `{"errors": {"base": ["extra keys not allowed @ data['name']"]}}`
            # on both stable and dev).
            payload = {k: v for k, v in config.items() if k != "name"}
            self._update_group_via_options_flow(kind, identity, payload)
            return
        if kind == BLUEPRINT_KIND:
            self._update_blueprint(identity, config)
            return
        if kind in HELPER_DOMAINS and identity not in self._store[kind]:
            # Fidelity with real HA: the storage-collection WS `{kind}/update`
            # command errors on an unknown id -- it never upserts. (Caller-
            # keyed automations/scripts genuinely DO upsert via their config
            # REST endpoint, so only the helper domains get this guard.) A
            # lenient upsert here previously masked a real bug in apply's
            # rollback path: rollback recreating a deleted object must go
            # through `create()`, not `update()` against an id that no
            # longer exists in the store -- an upserting fake would let that
            # mistake pass silently instead of raising like real HA.
            raise ValueError(f"WS command failed: Unable to find {kind}_id {identity}")
        if kind == DASHBOARD_KIND and identity != "default" and identity not in self._store[kind]:
            # Fidelity with real HA (mirrors the HELPER_DOMAINS guard just
            # above, should-fix 3(b)): `DirectBackend._aresolve_dashboard_id`
            # raises when a non-default `url_path` has no known registry
            # item -- an UPDATE never upserts a dashboard's registry item
            # into existence. The DEFAULT dashboard is exempt: real HA's
            # `lovelace/config/save(url_path=null)` genuinely upserts it,
            # since there is no registry item that could ever be "missing".
            raise ValueError(
                f"lovelace: no dashboard registry item found for url_path {identity!r} "
                "-- an UPDATE must target an existing dashboard, never a recreate"
            )
        normalized = normalize_ha(config, kind=kind)
        normalized = self._stored_body(kind, identity, normalized)
        if kind == DASHBOARD_KIND:
            normalized = _dashboard_registry_stored_shape(normalized)
        self._store[kind][identity] = normalized
        self._writes += 1

    # -- dashboards (Lovelace storage-mode, docs/internals/dashboards-design.md
    # §4.1) ------------------------------------------------------------------
    #
    # `delete`/`list_remote` need NO dashboard-specific branch at all:
    # `list_remote` is the plain generic copy (the default dashboard is
    # simply absent from `self._store["dashboard"]` until `create` puts it
    # there -- the `config_not_found` analogue, §2.1); `delete`'s generic
    # `self._store[kind].pop(identity, None)` already removes the whole
    # envelope. `update` needs one small guard above (the missing-identity
    # fidelity check, should-fix 3(b)) but otherwise falls through to the
    # generic tail, which already runs `normalize_ha` (an identity function
    # for this kind, §3.3) and stores the envelope verbatim (`_stored_body`'s
    # default passthrough branch) -- exactly "replaces meta and/or config".
    # Only `create` needs a dedicated method: HA rejects a hyphen-less
    # `url_path` and a duplicate one (§2.2 item 1), neither of which the
    # generic create path checks for any other kind.

    def _create_dashboard(self, config: dict[str, Any]) -> str:
        # normalize_ha is an identity function for this kind (§3.3) -- called
        # here for consistency with every other kind's write path, not
        # because a dashboard body needs any rewriting (a card's `tap_action`
        # legitimately keeps a legacy `service:` key, §2.2 item 5, and must
        # never be touched).
        normalized = normalize_ha(config, kind=DASHBOARD_KIND)
        identity = self._derive_identity(DASHBOARD_KIND, normalized)
        # Should-fix 3(a): the hyphen exemption is keyed off `meta is None`
        # (the ACTUAL default-dashboard marker), never off the derived
        # identity STRING -- a real, non-default dashboard whose declared
        # `url_path` happens to be the literal string "default" is NOT
        # exempt from HA's unconditional hyphen rule.
        is_default = normalized.get("meta") is None
        if not is_default and "-" not in identity:
            raise ValueError(
                f"lovelace/dashboards/create rejected: url_path {identity!r} must "
                "contain a hyphen (mirrors HA's real create-flow validation -- "
                "verified against HA 2026.7.4, docs/internals/ha-api-notes.md "
                "§39.3). HA bypasses its own rule with `allow_single_word: true` "
                "for the dashboards IT creates (`lovelace`, `map`), which is why "
                "those are adoptable but not creatable -- §39.11/§39.12)"
            )
        if identity in self._store[DASHBOARD_KIND]:
            raise ValueError(
                f"lovelace/dashboards/create rejected: a dashboard with url_path "
                f"{identity!r} already exists"
            )
        self._store[DASHBOARD_KIND][identity] = _dashboard_registry_stored_shape(
            normalized, creating=True
        )
        self._writes += 1
        return identity

    # -- config-entry template-helper flows ---------------------------------
    #
    # Modeled on the real REST flow (create: POST /api/config/config_entries/
    # flow[/{flow_id}]) and options-flow (update: POST /api/config/
    # config_entries/options/flow[/{flow_id}]) shapes (docs/internals/ha-api-notes.md
    # §26, §26.0: these are REST, NOT WebSocket -- they do not exist as WS
    # commands on real HA, which raises "Unknown command" for any of them): a
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
        _check_required_fields(kind, config, _TEMPLATE_REQUIRED_FIELDS[kind])

        flow_id = f"flow_{self._next_entry_id()}"
        menu_step = FlowStep(
            flow_id=flow_id,
            type="menu",
            step_id="user",
            menu_options=sorted(_TEMPLATE_FLOW_TYPE.values()),
        )
        self.flow_log.append(menu_step)

        # `unique_id` is NEVER part of the form's data_schema/submission
        # (docs/internals/ha-api-notes.md §26.6: real HA rejects it as an extra key).
        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_TEMPLATE_FLOW_TYPE[kind],
            data_schema=sorted(config),
        )
        self.flow_log.append(form_step)

        # HA's NumberSelector float-coerces min/max/step on the way in
        # (docs/internals/ha-api-notes.md §26.10) -- store what real HA would store,
        # not the caller's raw submission.
        options = _coerce_number_selector_fields(kind, config)
        entry_id = self._next_entry_id()
        # This `FlowStep.result` shape is FakeBackend's own internal
        # test-log bookkeeping (asserted on by
        # `test_fake_backend_template_flow.py`), NOT a literal mirror of the
        # real REST wire response: real HA's create_entry body nests
        # `entry_id`/`title`/... under a `"result"` key
        # (`_prepare_config_flow_result_json`, docs/internals/ha-api-notes.md §31.8),
        # and never has an `"options"` key at all (options are only ever
        # readable via the options-flow's suggested values, §26.7).
        # `DirectBackend._acreate_template_helper` parses that real nested
        # shape directly; this fake's `result` dict is deliberately
        # flat/simplified bookkeeping since `FakeBackend.create()` never
        # round-trips through JSON at all -- `title` is what HA actually
        # sets from the submitted `name` -- the wire-level correlator now
        # that there is no settable unique_id (§26.6).
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
                "target an existing entry via an options-flow update, never a recreate"
            )
        # `name` is REJECTED by the real options-flow schema outright
        # (docs/internals/ha-api-notes.md §26.7 finding 2): `generate_schema`
        # only adds the name field for `flow_type == "config"`, never
        # `"options"`. Mirrors HA's real `400 {"errors": {"base": ["extra
        # keys not allowed @ data['name']"]}}`.
        if "name" in config:
            raise ConfigEntryFlowError(
                f"{kind} options-flow form rejected: extra keys not allowed @ data['name'] "
                "(the options-flow schema never includes `name` -- it is create-only and "
                "becomes the entry's title, docs/internals/ha-api-notes.md §26.7)"
            )
        _check_required_fields(kind, config, _TEMPLATE_REQUIRED_FIELDS[kind])
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

        # entry_id is UNCHANGED (an options-update never recreates the entry)
        # -- only the options body is updated. Note: real HA's options-flow
        # submission for `template` still cannot rename the entry's title
        # via a `name` change without special handling; Hassle treats the
        # object key (identity) as fixed once created (matching every other
        # kind -- a rename is a delete+recreate under a new key, never an
        # in-place identity change: an existing object's HA id is never
        # changed).
        self._store[kind][identity] = options
        self._writes += 1

    def entry_id_for(self, kind: str, identity: str) -> str | None:
        """Test/CLI-facing lookup of a template/group helper's HA-assigned
        `entry_id` (manifest-only in the real sync engine, docs/internals/backend-protocol.md)."""
        if kind in GROUP_DOMAINS:
            return self._group_entry_ids.get((kind, identity))
        return self._entry_ids.get((kind, identity))

    # -- config-entry group-helper flows -------------------------------------
    #
    # Same create (menu -> form -> create_entry) / update (options-flow form
    # -> create_entry) / delete (entry removal) shape as the template-helper
    # flows above (docs/internals/ha-api-notes.md §38, mirroring §26): a menu
    # step choosing the flavor (twelve options, §38.1), then a form step
    # collecting `name`/`entities`/`hide_members`(+`all`/`type`), ending in a
    # flat `type: "create_entry"` body.
    #
    # The group options-flow schema does NOT re-present the same form as
    # create: real HA 400s an options-flow submission that carries `name`,
    # `{"errors": {"base": ["extra keys not allowed @ data['name']"]}}` --
    # the SAME rule as template (§26.7 finding 2): a group's title is not
    # editable through the options flow at all, exactly mirroring
    # `_update_via_options_flow` above (name-stripping at the public-API
    # boundary in `update()`, name-rejection here as a second line of
    # defense, merge-with-existing-options so `name` survives an update that
    # never resubmits it).

    def _create_group_via_flow(self, kind: str, config: dict[str, Any]) -> str:
        name = config.get("name")
        if not name:
            raise ValueError(f"{kind} config has no 'name' (required to derive identity/title)")
        identity = _slugify(str(name))
        if (kind, identity) in self._group_entry_ids:
            raise ConfigEntryFlowError(
                f"a {kind} config entry titled {name!r} already exists "
                "(CREATE-collision -- the flow would need to be aborted, not overwrite)"
            )
        _check_required_fields(kind, config, _GROUP_REQUIRED_FIELDS[kind])

        flow_id = f"flow_{self._next_entry_id()}"
        menu_step = FlowStep(
            flow_id=flow_id,
            type="menu",
            step_id="user",
            menu_options=sorted(_GROUP_FLAVOR.values()),
        )
        self.flow_log.append(menu_step)

        # `unique_id` is never part of the form's data_schema/submission
        # (docs/internals/ha-api-notes.md §38.1: same "extra keys not allowed" rule as
        # template, §26.6).
        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_GROUP_FLAVOR[kind],
            data_schema=sorted(config),
        )
        self.flow_log.append(form_step)

        options = dict(config)
        entry_id = self._next_entry_id()
        result_step = FlowStep(
            flow_id=flow_id,
            type="create_entry",
            result={"entry_id": entry_id, "title": str(name), "options": dict(options)},
        )
        self.flow_log.append(result_step)

        self._group_entry_ids[(kind, identity)] = entry_id
        self._store[kind][identity] = options
        self._writes += 1
        return identity

    def _update_group_via_options_flow(
        self, kind: str, identity: str, config: dict[str, Any]
    ) -> None:
        entry_id = self._group_entry_ids.get((kind, identity))
        if entry_id is None:
            raise ValueError(
                f"no config entry tracked for {kind}:{identity} -- an UPDATE must "
                "target an existing entry via an options-flow update, never a recreate"
            )
        # `name` is REJECTED by the real options-flow schema outright
        # (docs/internals/ha-api-notes.md §38.1: same rule as template, §26.7 finding
        # 2). Mirrors HA's real `400 {"errors":
        # {"base": ["extra keys not allowed @ data['name']"]}}`.
        if "name" in config:
            raise ConfigEntryFlowError(
                f"{kind} options-flow form rejected: extra keys not allowed @ data['name'] "
                "(the options-flow schema never includes `name` -- it is create-only and "
                "becomes the entry's title, docs/internals/ha-api-notes.md §38.1)"
            )
        _check_required_fields(kind, config, _GROUP_REQUIRED_FIELDS[kind])
        flow_id = f"optflow_{entry_id}"
        form_step = FlowStep(
            flow_id=flow_id,
            type="form",
            step_id=_GROUP_FLAVOR[kind],
            data_schema=sorted(config),
        )
        self.flow_log.append(form_step)

        # Real HA MERGES the submitted fields into the entry's existing
        # options rather than replacing the dict outright (mirrors template
        # §26.7 finding 3) -- `name` (never part of the options-flow schema)
        # survives an update untouched.
        existing = self._store[kind].get(identity, {})
        options = {**existing, **config}
        result_step = FlowStep(
            flow_id=flow_id,
            type="create_entry",
            result={"entry_id": entry_id, "options": dict(options)},
        )
        self.flow_log.append(result_step)

        # entry_id is UNCHANGED (an options-update never recreates the
        # entry).
        self._store[kind][identity] = options
        self._writes += 1

    # -- category registry + per-entity category assignment ----------------

    def list_categories(self, scope: str) -> dict[str, str]:
        """`config/category_registry/list` for `scope` -- `{category_id: name}`
        (additive, non-`Backend`-Protocol; see the module docstring's
        category-registry paragraph)."""
        return dict(self._categories.get(scope, {}))

    def create_category(self, scope: str, name: str) -> str:
        """`config/category_registry/create` -- returns the new `category_id`."""
        self._category_id_counter += 1
        category_id = f"cat_{self._category_id_counter:04d}"
        self._categories.setdefault(scope, {})[category_id] = name
        return category_id

    def assign_category(
        self, kind: str, identity: str, scope: str, category_id: str | None
    ) -> None:
        """`config/entity_registry/update`'s `categories` field, a per-scope
        SERVER-SIDE merge (never drops another scope's existing assignment on
        the same object -- no local or UI edit is silently lost --
        docs/internals/ha-api-notes.md §31.3, source-verified: "update/adjust only the
        provided scope(s); other category scopes ... are left as is").
        ``category_id=None`` UNSETS `scope` entirely (§31.3's `{scope: None}`
        primitive -- used by `hassle.sync.category_move` for a local move to
        the `misc.py` fallback), matching real HA's per-scope delete-or-set
        handler exactly (never a lingering `{scope: None}` entry -- the key
        itself is removed)."""
        existing = dict(self._entity_categories.get((kind, identity), {}))
        if category_id is None:
            existing.pop(scope, None)
        else:
            existing[scope] = category_id
        self._entity_categories[(kind, identity)] = existing

    def categories_for(self, kind: str, identity: str) -> dict[str, str]:
        """Test-facing lookup: the current `{scope: category_id}` assignment
        for `kind:identity` (empty if never assigned)."""
        return dict(self._entity_categories.get((kind, identity), {}))

    def seed_category(self, scope: str, category_id: str, name: str) -> None:
        """Test-only sugar: pre-populate a category registry row (the
        "category already exists" case) with a caller-chosen, stable
        `category_id` rather than the auto-generated `cat_NNNN` shape
        `create_category` would assign."""
        self._categories.setdefault(scope, {})[category_id] = name

    def delete_category(self, scope: str, category_id: str) -> None:
        """`config/category_registry/delete` (docs/internals/ha-api-notes.md §31.5c) --
        removes the category registry row AND strips it from every entity's
        `categories` assignment (real HA's `async_clear_category_id`, §31.3)."""
        self._categories.get(scope, {}).pop(category_id, None)
        for assigned in self._entity_categories.values():
            if assigned.get(scope) == category_id:
                del assigned[scope]

    # -- blueprints (docs/internals/blueprints-design.md §2/§7) --------------
    #
    # The store holds the FULL body (`source` included); `list_remote`
    # projects it down to metadata. That split is deliberate and is the whole
    # fidelity point: real HA holds the file and answers `blueprint/list` with
    # metadata only, having no command at all that serves the source back
    # (§2.1). Modelling it as "stored fully, exposed partially" rather than
    # "never stored" is what lets `blueprint_substitute` below answer from
    # HA's OWN copy -- which is what makes §2.2's drift oracle a real
    # comparison of two independently stored documents rather than a circular
    # re-expansion of the caller's.
    #
    # Keeping the source inside `self._store` (rather than in a sidecar dict)
    # also means `snapshot`/`restore` round-trip it for free, so apply's
    # rollback restores a blueprint completely instead of resurrecting a
    # sourceless husk.

    def _create_blueprint(self, config: dict[str, Any]) -> str:
        domain, path, source = self._blueprint_parts(config)
        identity = f"{domain}/{path}"
        if identity in self._store[BLUEPRINT_KIND]:
            # `blueprint/save` with `allow_override: False` -- a CREATE was
            # planned because nothing was there (§3's `create` row), so
            # something being there NOW is drift, never a silent overwrite.
            raise ValueError(
                f"blueprint `{path}` already exists in domain `{domain}` "
                "(blueprint/save refused: allow_override is false on a create)"
            )
        self._store[BLUEPRINT_KIND][identity] = {**config, "source": source}
        self._writes += 1
        return identity

    def _update_blueprint(self, identity: str, config: dict[str, Any]) -> None:
        if identity not in self._store[BLUEPRINT_KIND]:
            # The same non-upserting fidelity guard the helper and dashboard
            # branches carry: an UPDATE against a path HA does not have must
            # raise, so apply's rollback can never quietly paper over a
            # recreate that had to go through `create`.
            raise ValueError(
                f"blueprint `{identity}` does not exist -- an UPDATE must target an "
                "existing blueprint, never a recreate"
            )
        _domain, _path, source = self._blueprint_parts(config)
        # Remember what this blueprint said BEFORE the save, so
        # `blueprint_stale_reads` can model real HA serving the prior document
        # for a moment afterwards (ha-api-notes §40.8).
        previous = self.blueprint_source(identity)
        if previous is not None:
            self._blueprint_previous[identity] = previous
        self._store[BLUEPRINT_KIND][identity] = {**config, "source": source}
        self._writes += 1

    def _delete_blueprint(self, identity: str) -> None:
        if identity not in self._store[BLUEPRINT_KIND]:
            # §2: real HA answers `unknown_error`/ENOENT for a missing path --
            # an error, not a silent success.
            raise ValueError(
                f"blueprint `{identity}` does not exist "
                "(blueprint/delete: No such file or directory)"
            )
        del self._store[BLUEPRINT_KIND][identity]
        self._writes += 1

    @staticmethod
    def _blueprint_parts(config: dict[str, Any]) -> tuple[str, str, str]:
        domain = config.get("domain")
        path = config.get("path")
        source = config.get("source")
        if not isinstance(domain, str) or not isinstance(path, str):
            raise ValueError("a blueprint body needs a `domain` and a `path`")
        if not isinstance(source, str):
            # `blueprint/save` takes `yaml`; a body with no source has nothing
            # to send, and a remote (metadata-only) body must never be
            # mistaken for something pushable (§2.1).
            raise ValueError(
                f"blueprint `{domain}/{path}` has no `source` to save -- a remote "
                "(metadata-only) body is not pushable; HA cannot serve a blueprint's "
                "source back, so the bundle file is the only source of truth"
            )
        return domain, path, source

    def blueprint_source(self, identity: str) -> str | None:
        """The stored YAML for one blueprint, or ``None``.

        Additive test/inspection surface, NOT part of the `Backend` Protocol
        and deliberately not reachable through `list_remote`: real HA has no
        equivalent (§2.1). Tests use it to assert what a save actually stored.
        """
        stored = self._store[BLUEPRINT_KIND].get(identity)
        if stored is None:
            return None
        source = stored.get("source")
        return source if isinstance(source, str) else None

    def blueprint_substitute(
        self, domain: str, path: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """``blueprint/substitute``: expand this backend's OWN stored YAML.

        Additive, non-Protocol, probed via `getattr` exactly as `entry_id_for`
        is. The expansion runs through :mod:`hassle.blueprints` — the same
        implementation the compiler, validator and simulator use (§7) — so a
        drift check comparing this against a local expansion is comparing two
        genuinely independent copies of the document, which is the entire
        basis of §2.2's oracle.

        Returns the **config block only**, matching the observed API shape
        (ha-api-notes §40.7) — see the comment at the return statement.
        """
        identity = f"{domain}/{path}"
        source = self.blueprint_source(identity)
        if source is None:
            raise ValueError(f"blueprint `{identity}` does not exist (blueprint/substitute)")
        if self.blueprint_stale_reads > 0 and identity in self._blueprint_previous:
            # Post-save staleness, modelled (ha-api-notes §40.8): real HA's
            # `blueprint/substitute` served the PRIOR document for several
            # seconds after a `blueprint/save`, which made a plan run straight
            # after a push report drift that then self-healed. Setting this
            # counter is how a test reproduces that window offline.
            self.blueprint_stale_reads -= 1
            source = self._blueprint_previous[identity]
        blueprint = parse_blueprint(
            source, display_path=blueprint_display_path(path, domain=domain)
        )
        expanded = blueprint.expand(inputs)
        # Real HA's `blueprint/substitute` returns the CONFIG BLOCK ONLY --
        # observed keys exactly {actions, conditions, max_exceeded, mode,
        # triggers} on 2026-08-10 (ha-api-notes §40.7). It is handed
        # `{domain, path, input}` and NO INSTANCE, so it has no
        # `id`/`alias`/`description` to return -- not even when the blueprint
        # DOCUMENT declares an `alias:`/`description:` of its own, which
        # community blueprints commonly do as a default label.
        #
        # Modelled here rather than special-cased in the drift check, because
        # this is simply what the API does. A fake that returned them would
        # keep both sides' key sets artificially identical and could never
        # catch an asymmetry that exists only against real HA -- which is
        # exactly how the first live run's false-positive drift got through.
        return {
            key: value for key, value in expanded.items() if key not in INSTANCE_IDENTITY_FIELDS
        }

    def blueprint_settle_sleep(self, seconds: float) -> None:
        """Record a settle wait instead of taking it (ha-api-notes §40.8).

        Additive and non-Protocol, `getattr`-probed by
        `hassle.sync.apply._reload_after_blueprint_update` exactly as
        `reload_automations` is. `DirectBackend` deliberately does NOT define
        it, so live pushes get a real `time.sleep`.
        """
        self.blueprint_settle_waits.append(seconds)

    def reload_automations(self) -> None:
        """``automation.reload`` (blueprints-design §4.3).

        Additive and non-Protocol, like `blueprint_substitute`. The counter is
        what the apply-ordering tests assert on.
        """
        self.automation_reloads += 1

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
          untouched object (docs/internals/ha-api-notes.md's pull-plan-noop finding).
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
        if kind == BLUEPRINT_KIND:
            self._delete_blueprint(identity)
            return
        self._store[kind].pop(identity, None)
        if kind in TEMPLATE_DOMAINS:
            # Config entry removal (docs/internals/ha-api-notes.md §26): the entry_id
            # is retired -- a later re-CREATE under the same name-derived
            # identity gets a FRESH entry_id (the "entry_id-changes" rollback
            # caveat, DESIGN §13 amendment).
            self._entry_ids.pop((kind, identity), None)
        elif kind in GROUP_DOMAINS:
            # Same rollback-by-recreate caveat as template (docs/
            # ha-api-notes.md §38 mirrors §26.3).
            self._group_entry_ids.pop((kind, identity), None)
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
        # Routed through `list_remote` so it hashes what a CALLER can actually
        # see. For `blueprint` the store holds more than the remote body does
        # (§2.1), and hashing the store would give a value `apply_plan`'s
        # pre-write re-verification -- which reads `list_remote` -- could
        # never match.
        config = self.list_remote(kind).get(identity)
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
                "description": "created by the seed-data harness",
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
            # Real HA's storage-collection WS create IGNORES any supplied id
            # and derives identity by slugifying the NAME (docs/ha-api-notes
            # §17.5; validate's helper-id-name-mismatch rule documents the
            # same). An earlier version of this fake honored `id` instead,
            # which meant a duplicate-create bug (creating a second helper
            # with the same name but a different id) went uncaught in tests.
            return _slugify(str(normalized.get("name") or normalized.get("id") or kind))
        if kind == DASHBOARD_KIND:
            # Mirrors `DashboardConfig.identity` (docs/internals/
            # dashboards-design.md §3.1/§3.2): `meta.url_path` verbatim
            # (never re-slugified -- a real url_path IS HA's own slug), or
            # the sentinel `"default"` when `meta` is null/absent. Unlike
            # every other kind this is NOT HA-assigned -- it's the caller's
            # own declared url_path, which is why `dashboard` is in
            # `_CALLER_KEYED_KINDS` (`hassle.sync.apply`).
            meta = normalized.get("meta")
            if isinstance(meta, dict):
                meta = cast("dict[str, Any]", meta)
                if meta.get("url_path") is not None:
                    return str(meta["url_path"])
            return "default"
        if kind == BLUEPRINT_KIND:
            # Mirrors `BlueprintConfig.identity`: `<domain>/<path>`, both
            # verbatim. Caller-keyed like a dashboard -- HA assigns nothing
            # here, the path IS the address.
            return f"{normalized.get('domain')}/{normalized.get('path')}"
        raise ValueError(f"unknown object kind {kind!r}")
