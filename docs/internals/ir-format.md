# Frozen IR interface

This is the frozen contract the compiler, decompiler, sync engine, and
simulator all build against. Changing anything here requires updating this
document in the same PR (CONTRIBUTING.md, "compatibility contracts").

Module: `hassle.ir` (package `hassle-core`). Public surface (`hassle.ir.__all__`):

## Object kinds and keys

- Kinds (`OBJECT_KINDS`, 11 total): `automation`, `script`, and the nine
  storage-collection helper domains (`HELPER_DOMAINS`): `input_boolean`,
  `input_number`, `input_select`, `input_text`, `input_datetime`,
  `input_button`, `counter`, `timer`, `schedule`.
- Object key format: `object_key(kind, identity) -> "<kind>:<identity>"`
  (e.g. `"automation:hall_light_on_motion"`, `"script:movie_time"`,
  `"input_boolean:guest_mode"`). This is the manifest/plan key (DESIGN §8.1).
- Identity source: automations/helpers derive identity from the config body
  `id`; scripts have an **extrinsic** object_id supplied via `key_hint=` at
  parse time (their config body has no id). `IRObject.object_key()` raises if
  identity is absent.
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

## parse / serialize (I3 — lossless round-trip)

- `parse(config: dict, *, kind: str, key_hint: str | None = None) -> IRObject`
- `serialize(obj: IRObject) -> dict`
- Invariant: `serialize(parse(x, kind=k)) == x` (semantic/key-order-insensitive
  equality) for any HA config. Serialization emits exactly the keys parsed
  (`exclude_unset=True`); no default is ever materialized into output.

## Canonical JSON + hashing (R8 — determinism)

- `canonical_json(data) -> str`: sorted keys (recursive), preserved list order,
  compact separators, `ensure_ascii=False`. Byte-stable across runs/platforms.
- `sha256_hash(data) -> str`: `"sha256:" + sha256(canonical_json(data))`.
  Key-order-invariant; sensitive to any value change or list reordering.

Acceptance tests (all green): `test_ir_roundtrip_corpus`,
`test_ir_preserves_unknown_fields`, `test_canonical_hash_stable`,
`test_object_key_format` (in `packages/hassle-core/tests/`).
