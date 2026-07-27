# Frozen IR interface

This is the frozen contract the compiler, decompiler, sync engine, and
simulator all build against. Changing anything here requires updating this
document in the same PR (CONTRIBUTING.md, "compatibility contracts").

Module: `hassle.ir` (package `hassle-core`). Public surface (`hassle.ir.__all__`):

## Object kinds and keys

- Kinds (`OBJECT_KINDS`, 28 total): `automation`, `script`, `dashboard`, the
  nine storage-collection helper domains (`HELPER_DOMAINS`): `input_boolean`,
  `input_number`, `input_select`, `input_text`, `input_datetime`,
  `input_button`, `counter`, `timer`, `schedule`; and the sixteen config-entry
  helper domains (`CONFIG_ENTRY_DOMAINS` = `TEMPLATE_DOMAINS` |
  `GROUP_DOMAINS`) — four `template_*` and twelve `group_*`.
- Object key format: `object_key(kind, identity) -> "<kind>:<identity>"`
  (e.g. `"automation:hall_light_on_motion"`, `"script:movie_time"`,
  `"input_boolean:guest_mode"`, `"dashboard:climate-control"`). This is the
  manifest/plan key (DESIGN §8.1).
- Identity source: automations/helpers derive identity from the config body
  `id`; config-entry helpers derive it from the declared `name` (slugified);
  scripts have an **extrinsic** object_id supplied via `key_hint=` at
  parse time (their config body has no id). `IRObject.object_key()` raises if
  identity is absent.
- **`dashboard` identity** is the dashboard's `url_path`, taken **verbatim**
  from `meta` — it is already HA's own slug and is never re-slugified (that
  would turn `climate-control` into `climate_control` and target the wrong
  dashboard). Derivation order: `meta["url_path"]` → the extrinsic `key_hint`
  → the sentinel `"default"`. The sentinel is the **default dashboard**, which
  has no registry item and `url_path = null` on the wire; it cannot collide
  with a real dashboard because HA requires a created `url_path` to contain a
  hyphen. Unlike every other kind, `object_key()` therefore never raises for a
  `dashboard`, and the identity segment routinely contains a hyphen — which is
  exactly why the key-opacity rule below matters.
- **Key opacity (downstream contract):** treat an object key as an opaque
  string. If a consumer must recover `(kind, identity)`, split on the **first**
  `:` only — the identity segment is not escaped and is not guaranteed
  colon-free. Never `split(":")` and assume two parts.

## Models

- `IRObject` — base pydantic model; `extra="allow"` (unknown-field preservation, I3).
  Methods: `kind()`, `identity`, `object_key()`, `to_ha()`, `canonical_json()`,
  `sha256()`, `attach_key()`; `HelperConfig.attach_domain()`.
- `AutomationConfig`, `ScriptConfig`, `HelperConfig` — mirror HA's stored config.
  Common scalar options are declared; structural blocks
  (`trigger`/`condition`/`action`/`sequence`/`fields`/…) pass through verbatim as
  native JSON (`Any`) — the typed compiler/decompiler layer that interprets them
  is separate from this schema (DESIGN §7.1). A future typed refinement of these
  blocks (e.g. tagged unions) is an allowed extension, not a break, so long as
  the round-trip and hashing contracts below still hold.
- `DashboardConfig` — a Lovelace storage-mode dashboard. **The one model whose
  body is a Hassle-composed envelope rather than a mirror of a single HA
  store**, because a dashboard is two HA-side objects (a `lovelace_dashboards`
  registry item and a `lovelace[.<url_path>]` config blob) but one Hassle
  object — one plan row diffs both, one conflict covers both:

  ```json
  {"meta": {"url_path": "climate-control", "title": "Climate",
            "icon": "mdi:thermostat", "show_in_sidebar": true,
            "require_admin": false},
   "config": {"views": [ ... ]}}
  ```

  - `meta` is the registry item **minus** `id` (HA-assigned, transport-only —
    the same rule as a config entry's `entry_id`) and **minus** `mode` (always
    `"storage"`; YAML-mode dashboards are filtered out of `list_remote`
    entirely and are not Hassle's to manage). `meta` is **`null`** for the
    default dashboard, which has no registry item at all — and `null` here is a
    *set* field, so it survives `exclude_unset=True` serialization.
  - `config` is the view config **verbatim**, native-JSON passthrough (`Any`),
    exactly like `triggers`/`actions` above. The typed card layer lives in the
    compiler/decompiler, not this schema.
  - Rationale for the envelope over flattening `meta` into the config top
    level: the Lovelace config has its own top-level `title` key, so flattening
    would silently collide "sidebar title" with "config title". The envelope
    keeps the two stores' keyspaces disjoint by construction.
  - Because the object hash covers the whole envelope, a UI edit to *either*
    the sidebar metadata or the cards surfaces as one drifted object — refresh
    and conflict happen at dashboard granularity.

## parse / serialize (I3 — lossless round-trip)

- `parse(config: dict, *, kind: str, key_hint: str | None = None) -> IRObject`
- `serialize(obj: IRObject) -> dict`
- Invariant: `serialize(parse(x, kind=k)) == x` (semantic/key-order-insensitive
  equality) for any HA config. Serialization emits exactly the keys parsed
  (`exclude_unset=True`); no default is ever materialized into output.

## Normalization (`normalize_ha`) and its one exempt kind

- `normalize_ha(config, *, kind) -> dict`: reproduces HA's 2024.10+ storage
  normalization so a local body hashes identically to HA's stored copy —
  outer `trigger`/`condition`/`action` → plural (automations only), and a
  recursive `service:` → `action:` rewrite through every nested action
  container. Never mutates its input.
- **`kind == "dashboard"` is exempt: `normalize_ha` is an exact identity
  function** (it still returns a deep copy, so callers may mutate the result).
  A Lovelace card body legitimately contains `service:` keys of its own,
  inside `tap_action`/`hold_action`/`double_tap_action` payloads written in
  the legacy `{"action": "call-service", "service": "..."}` form, and the
  Lovelace store saves the body verbatim — no schema validation, no
  normalization. Applying the generic rewrite would break the card *and* drift
  the hash into a phantom conflict on every subsequent plan.
- The same exemption applies to `modernize_for_comparison`, whose two rewrites
  (`platform:` → `trigger:`, string/numeric `delay:` → dict-of-units) walk
  every dict in a body unconditionally and would otherwise rewrite matching
  shapes inside third-party card bodies.
- `storage_canonical(kind, config)` has **no entries for `dashboard`**
  (identity), for the same reason: HA materializes no defaults into a Lovelace
  body. List order is semantically meaningful throughout a dashboard (views,
  sections, cards) and the canonical-JSON rules below already preserve it.

## Canonical JSON + hashing (R8 — determinism)

- `canonical_json(data) -> str`: sorted keys (recursive), preserved list order,
  compact separators, `ensure_ascii=False`. Byte-stable across runs/platforms.
- `sha256_hash(data) -> str`: `"sha256:" + sha256(canonical_json(data))`.
  Key-order-invariant; sensitive to any value change or list reordering.

Acceptance tests (all green): `test_ir_roundtrip_corpus`,
`test_ir_preserves_unknown_fields`, `test_canonical_hash_stable`,
`test_object_key_format`, `test_ir_keys`, `test_ir_dashboard_envelope`,
`test_ir_dashboard_normalize` (in `packages/hassle-core/tests/`).
