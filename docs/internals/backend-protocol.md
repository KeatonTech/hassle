# `Backend` protocol, plan/apply data model, and the `SourceWriter` seam

This is a frozen compatibility contract: the `Backend` Protocol plus the
plan/apply data model. The sync engine is built against an in-memory
`FakeBackend`; `DirectBackend` (the real REST/WebSocket transport) implements
the same Protocol, so the two stay interchangeable. Changing any shape
documented here requires updating this document in the same PR
(CONTRIBUTING.md, "compatibility contracts").

## 1. The `Backend` Protocol

`hassle.backend.Backend` (`packages/hassle-core/src/hassle/backend/protocol.py`)
is a structural `typing.Protocol` (`@runtime_checkable`) — implementers do not
inherit from it, they just implement the methods:

```python
class Backend(Protocol):
    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]: ...
    def create(self, kind: str, config: dict[str, Any]) -> str: ...
    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None: ...
    def delete(self, kind: str, identity: str) -> None: ...
```

- `kind` is one of `hassle.ir.OBJECT_KINDS` (`"automation"`, `"script"`, or one
  of the nine helper domains in `hassle.ir.HELPER_DOMAINS`).
- `list_remote` returns every object of that kind currently stored in HA,
  keyed by **identity** (not the full `"<kind>:<identity>"` object key), with
  each config body already in HA's normalized/plural storage form (DESIGN
  §7.1, docs/internals/ha-api-notes.md §10.1) — `DirectBackend` gets this for free
  because real HA already normalizes on read-back; `FakeBackend` reproduces it
  by calling `hassle.ir.normalize_ha` on every `create`/`update`.
- `create` returns the new object's identity (HA assigns automation/script ids
  from the caller and helper ids by slugifying `name`, per docs/internals/ha-api-notes.md
  §2–§4 — either way, the backend is the source of truth for what identity was
  actually assigned).
- `update`/`delete` are addressed by `(kind, identity)`. The real HA helper
  WebSocket API keys update/delete payloads as `{domain}_id` (docs/internals/ha-api-notes.md
  §4, quirk #1) — that is a `DirectBackend`/`FakeBackend` **internal**
  implementation detail; it does not appear in this Protocol's signature,
  keeping the Protocol domain-shape-agnostic.

### Deliberately out of scope

Registry snapshot fetch, trace access, and template rendering are **not** on
`Backend`. The plan table only ever compares base (manifest) / local
(compiled) / remote (backend `list_remote`) — it never consults registry data
(DESIGN §8.2/§8.3). Those concerns belong to `DirectBackend` directly or to
other modules layered on top of it; adding them here would widen the seam
every future `Backend` implementer has to satisfy for no sync-engine benefit.

## 2. The plan/apply data model (`hassle.sync`)

All models are pydantic `BaseModel`s (matching the style already established
in `hassle.ir.models`), frozen where they represent a computed result
(`Conflict`, `PlanEntry`, `Plan`) so a plan can't be mutated after the fact.

### `PlanAction`

The exact action set of the DESIGN §8.2 table — no more, no fewer:

```
noop | update | delete | refresh | conflict | drop | create | adopt
```

### `ConflictKind`

The three distinct ways DESIGN §8.2's table produces a `conflict` action:

- `both_edited` — base-vs-local and base-vs-remote both changed, to different
  values ("different | different" row).
- `deleted_locally_edited_remotely` — remote changed since base, local was
  deleted ("different (UI edit) | local deleted" row).
- `edited_locally_deleted_remotely` — remote object is gone, local changed
  since base ("remote deleted | different" row).

### `Conflict`

```python
class Conflict(BaseModel):
    object_key: str
    kind: ConflictKind
    base: dict[str, Any] | None
    local: dict[str, Any] | None
    remote: dict[str, Any] | None
```

Full config payloads, never lossy summaries (`local`/`remote` may be `None`
when that side was deleted). Rendering a pretty 3-way diff of the *decompiled
DSL* is the CLI's job (DESIGN §8.2); this is only the structured data.

### `PlanEntry` / `Plan`

```python
class PlanEntry(BaseModel):
    object_key: str
    kind: str
    action: PlanAction
    base: dict[str, Any] | None = None
    local: dict[str, Any] | None = None
    remote: dict[str, Any] | None = None
    remote_hash_at_plan: str | None = None
    source_path: str | None = None
    conflict: Conflict | None = None

class Plan(BaseModel):
    entries: list[PlanEntry]
    def entry_for(self, object_key: str) -> PlanEntry | None: ...
    def entries_with_action(self, action: PlanAction) -> list[PlanEntry]: ...
```

`remote_hash_at_plan` is the canonical hash (`hassle.ir.canonical.sha256_hash`)
of the remote object *at the moment the plan was computed* — the apply engine
re-verifies against this immediately before writing (DESIGN §8.2's "apply is
transactional" paragraph; `test_apply_reverifies_hashes`).
`source_path` is where the pull engine should route `SourceWriter` calls for
this object key.

### `Manifest` / `ManifestEntry`

The `manifest.lock` model (DESIGN §8.1), unchanged in shape from the design
doc:

```python
class ManifestEntry(BaseModel):
    source: str | None
    compiled_hash: str
    kind: str = "dsl"  # dsl | raw | blueprint

class Manifest(BaseModel):
    synced_at: str
    ha_version: str
    objects: dict[str, ManifestEntry]
```

`synced_at` is **always caller-supplied** — core logic never calls
`datetime.now()` or anything else wall-clock-shaped; the CLI layer is what
actually knows the time. `Manifest.canonical_json()` reuses
`hassle.ir.canonical.canonical_json` for stable serialization, matching the
IR's own convention.

### `ApplyResult` / `ApplyOutcome`

```python
class ApplyOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ABORTED = "aborted"

class ApplyResult(BaseModel):
    outcomes: dict[str, ApplyOutcome]
    succeeded: bool
    manifest: Manifest | None
```

`manifest` is only populated when `succeeded` is `True` — on any failure the
caller keeps its old manifest (`test_manifest_updates_only_on_success`).

## 3. The `SourceWriter` seam

`hassle.sync.source_writer.SourceWriter` decouples the sync engine's pull-side
actions from the LibCST-based splicer. The pull engine (`hassle.sync.pull`)
only depends on this Protocol:

```python
class SourceWriter(Protocol):
    def write_whole_file(self, path: Path, content: str) -> None: ...
    def splice_object(self, path: Path, object_key: str, content: str) -> None: ...
    def delete_object(self, path: Path, object_key: str) -> None: ...
```

- `write_whole_file` — create or fully overwrite a file. Used for `adopt`
  (a brand-new object has no existing file to splice into).
- `splice_object` — replace just one object's definition within an existing
  file, preserving everything else byte-for-byte (DESIGN §7.3's
  `test_splice_preserves_rest_of_file`). Used for `refresh`.
- `delete_object` — remove an object's source (`drop`). May delete the whole
  file if that was the object's only definition.

Three implementations:

- `SplicingSourceWriter` — the real one, and what `hassle pull` uses:
  `splice_object` surgically replaces one object's statement in place via
  `hassle.decompiler.splice`, and `delete_object` removes only that object's
  statement — sibling objects and hand-written comments in the same file
  survive byte-for-byte (no local or UI edit is ever silently lost). If the
  manifest points at a file that no longer defines the object, it appends the
  refreshed definition under a `# hassle: updated from UI on <date>` marker
  rather than clobbering unrelated content; if that append would collide with
  a metaprogrammed (compile-time-loop-generated) object of the same key, it
  records a `reconcile_warnings` entry instead of creating a silent duplicate.
- `WholeFileSourceWriter` — a blunt but correct stand-in: every operation
  is a whole-file write or delete (`splice_object` degrades to
  `write_whole_file`). Correct only when every touched file holds a single
  object — on a multi-object file, `splice_object`/`delete_object` would
  clobber the siblings, so this implementation is used only for `adopt` (a
  new file has no "rest of file" to preserve) and in tests.
- `RecordingSourceWriter` — an in-memory test double (no disk I/O) that
  records every call for assertions; used throughout the pull-engine unit
  tests and the fuzz test for lost edits.

### Conflict marker format

When the pull engine writes a `conflict` plan entry, it hands `SourceWriter` a
placeholder textual marker block (not real DSL, not git's own conflict-marker
syntax — deliberately distinct so it's never confused with an actual git
conflict by tooling):

```
<<<<<<< local
{local config, pretty-printed}
=======
{remote config, pretty-printed}
>>>>>>> remote
```

The CLI owns real conflict UX (a rich 3-way *DSL*-level diff, DESIGN §8.2);
this format only exists so a human can see both sides of a conflict from the
pull engine's output directly.

## 3.1. Config-entry template/group-helper addendum (`Backend` unchanged)

Template (`hassle.ir.TEMPLATE_DOMAINS`: `template_number`/`template_sensor`/
`template_binary_sensor`/`template_select`) and group
(`hassle.ir.GROUP_DOMAINS`, twelve flavors) are config-entry `ObjectType`
plugins (DESIGN §13). Both need **zero changes to the `Backend` Protocol**:
`list_remote`/`create`/`update`/`delete` are exactly the same four methods,
addressed the same `(kind, identity)` way. What differs is entirely internal
to `FakeBackend`/`DirectBackend`:

- **Identity:** there is no settable `unique_id` — real HA's config-flow form
  schema rejects an unrecognized `unique_id` key outright. `identity` is
  DERIVED from the declared `name` (slugified), the same rule storage helpers
  use for an unsupplied `id` — except here it's the ONLY identity source
  (docs/internals/ha-api-notes.md §26.6/§38.1). HA's own config-entry
  identity, the `entry_id` it assigns on creation (docs/internals/ha-api-notes.md
  §26), remains transport-side only; the wire-level correlator for
  re-deriving identity on `list_remote` is the entry's `title` (set from the
  submitted `name` by the flow). Which config-entry sub-kind a listed entry
  is gets determined by cross-referencing the entity registry's
  `config_entry_id` field (a WS call, `config/entity_registry/list`) rather
  than a client-side marker, since sub-kind data can't travel through
  `options` either (the same "no bookkeeping keys" schema rule).
- **`ManifestEntry.entry_id`** (additive optional field, `hassle.sync.models`):
  where the `entry_id` is tracked — never in the IR body, never in the
  object key. `apply.py`'s `_advance_manifest` populates it by calling an
  **additive, non-Protocol** `entry_id_for(kind, identity) -> str | None`
  method both `FakeBackend` and `DirectBackend` expose (probed defensively
  via `getattr`, the same pattern `fetch_registry_snapshot` uses for backend
  extras outside this Protocol) — a `Backend` implementer that doesn't expose
  it (hypothetically, a backend with no config-entry kinds at all) simply
  gets `entry_id=None` forever, which is harmless: nothing else reads it
  except `DirectBackend` needing it to address
  `config_entries/options/flow` by entry_id rather than re-deriving it. The
  same additive, `getattr`-probed pattern backs the category-writeback
  surface (`list_categories`/`create_category`/`categories_for`/
  `assign_category` — see `hassle.sync.category_writeback`).
- **Internally:** `create`/`update` drive a simulated (`FakeBackend`) or real
  (`DirectBackend`) multi-step config-entry flow / options-flow to completion
  inside the single synchronous method call — the Protocol's caller (the sync
  engine) never sees the intermediate flow steps, exactly as it never sees
  the helper `{domain}_id` payload-key convention (quirk #1) either. `delete`
  is a plain entry removal by `entry_id`. Flow create/step-submission,
  options-flow create/step-submission, and entry removal are all **REST**,
  not WebSocket (`POST /api/config/config_entries/flow[/{flow_id}]`,
  `POST /api/config/config_entries/options/flow[/{flow_id}]`,
  `DELETE /api/config/config_entries/entry/{entry_id}`) — only entry
  *listing* (`config_entries/get`) is WS (docs/internals/ha-api-notes.md
  §26.0). `DirectBackend` uses `HaClient.rest_post`/`rest_delete` for every
  write path here.
- **Apply order** (`hassle.sync.apply._KIND_ORDER`): the template and group
  domains slot in after the nine storage helpers, before scripts — same
  dependency-ordering rationale (an automation/script may reference a
  template/group helper's entity id, so it must exist first). `_KIND_ORDER`
  is a literal ordered tuple, not a bare `OBJECT_KINDS` membership check —
  `_kind_sort_key`'s fallback for a kind absent from the tuple sorts it dead
  last (after `script`, the tuple's own last entry), which would be silently
  wrong dependency order for any object referencing it. A new config-entry
  domain must be added to `_KIND_ORDER` explicitly, not just to
  `OBJECT_KINDS`.

See docs/internals/ha-api-notes.md §26 and §38 for the full flow-shape capture
notes.

### 3.1.1 Adding a new config-entry domain

A new config-entry helper domain (e.g. `threshold`/`derivative`, DESIGN §13's
other named follow-ons) needs:

1. **IR:** a domain string added to a `*_DOMAINS` frozenset next to
   `TEMPLATE_DOMAINS`/`GROUP_DOMAINS` (`hassle.ir.keys`) — or, if it shares
   the exact same options shape as `TemplateHelperConfig` (`name` + passthrough
   extras, no `unique_id`/`id` field at all), no new IR class at all; a
   genuinely different shape gets its own thin `IRObject` subclass mirroring
   `TemplateHelperConfig`. `identity` is a computed `slugify(name)` property
   either way — check the new integration's own config-flow schema for
   whether it, too, rejects a caller-supplied `unique_id` (verify against its
   own `config_flow.py` rather than assuming the template/group finding
   generalizes).
2. **DSL:** one builder function per new domain in a sibling module to
   `hassle.compiler.template_helpers`, reusing `_declare_helper`'s pattern
   (validate domain membership, build the IR object, register via
   `current_registry().add_object`, return an `EntityRef`) — no new
   registration mechanism. Check the new domain's own required-field set and
   encode it the same way (a `_TEMPLATE_REQUIRED_FIELDS`-equivalent map).
3. **`FakeBackend`:** the same internal methods
   (`_create_via_flow`/`_update_via_options_flow`/`entry_id_for`, or a shared
   helper if a further domain makes the duplication worth collapsing)
   dispatch on the new domain's own step_id map and required-fields map —
   `create`/`update`/`delete`/`list_remote` themselves need no change (they
   already dispatch on `kind in TEMPLATE_DOMAINS`-shaped membership checks;
   widen the membership set or add a sibling one).
4. **`DirectBackend`:** same shape — the REST flow/options-flow/entry-removal
   endpoints are generic across every config-entry integration
   (`handler=<domain integration name>` is the only per-domain parameter on
   the start-flow POST); only the step_id/field-name/required-field map is
   domain-specific. The entity-registry sub-kind-discrimination cross-reference
   is also generic — any config-entry integration creating exactly one entity
   per entry can reuse `_config_entry_entity_domains`'s pattern verbatim.
5. **Decompiler/placement:** the stored body's keys map straight onto the
   builder's kwargs, generic per-domain (keyed off the domain set's
   membership, not a hardcoded domain name); `default_source_path`'s shared
   root-level `misc.py` rule (category-first layout) already covers a domain
   added to that set via `_SCOPE_FOR_KIND`'s shared `"helpers"` scope, so no
   placement-code change is needed.
6. **Apply order / validation / ignore-glob:** apply order needs the new
   domain added to `_KIND_ORDER` explicitly (see above — this is NOT a bare
   `OBJECT_KINDS` membership check, unlike validation and the ignore-glob,
   which are). Validation may need a genuinely new function if the domain has
   a body field that references other entities (the way `group`'s `entities=`
   does): nothing in the existing validator walks a helper object's own body
   at all (`hassle.registry.extract.extract_references` only ever descends
   into an object's `triggers`/`conditions`/`actions`, and neither template
   nor group helpers have any of those sections) — `group`'s
   `hassle.registry.validate._validate_group_entities` is the precedent to
   follow if the new domain has an analogous field; check the new domain's
   own schema shape rather than assuming it does.

Steps 1–2 are the only places that see genuinely new code per domain (an IR
shape + a DSL builder); steps 3–6 are membership-set additions into machinery
that already exists generically.

## 4. Where things live

- `hassle.backend` — `Backend` Protocol (`protocol.py`), `FakeBackend`
  (`fake.py`), `DirectBackend` (`direct.py`).
- `hassle.sync` — `PlanAction`/`Plan`/`PlanEntry`/`Conflict`/`ConflictKind`/
  `Manifest`/`ManifestEntry`/`ApplyResult`/`ApplyOutcome` (`models.py`),
  `SourceWriter`/`WholeFileSourceWriter`/`SplicingSourceWriter`/
  `RecordingSourceWriter` (`source_writer.py`), `compute_plan` (`plan.py`),
  `apply_plan` (`apply.py`), `apply_pull` (`pull.py`).
