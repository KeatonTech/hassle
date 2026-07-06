# `Backend` protocol, plan/apply data model, and the `SourceWriter` seam (F2)

Freeze point **F2** (declared at the start of M5, per MILESTONES.md): the
`Backend` Protocol plus the plan/apply data model. M5 builds the sync engine
against an in-memory `FakeBackend`; M6 builds `DirectBackend` (the real
REST/WebSocket transport) against the same Protocol, independently and in
parallel. Changing any shape documented here after this point requires a
MILESTONES.md update in the same PR (R5).

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
  §7.1, docs/ha-api-notes.md §10.1) — `DirectBackend` gets this for free
  because real HA already normalizes on read-back; `FakeBackend` reproduces it
  by calling `hassle.ir.normalize_ha` on every `create`/`update`.
- `create` returns the new object's identity (HA assigns automation/script ids
  from the caller and helper ids by slugifying `name`, per docs/ha-api-notes.md
  §2–§4 — either way, the backend is the source of truth for what identity was
  actually assigned).
- `update`/`delete` are addressed by `(kind, identity)`. The real HA helper
  WebSocket API keys update/delete payloads as `{domain}_id` (docs/ha-api-notes.md
  §4, quirk #1) — that is a `DirectBackend`/`FakeBackend` **internal**
  implementation detail; it does not appear in this Protocol's signature,
  keeping the Protocol domain-shape-agnostic.

### Deliberately out of scope

Registry snapshot fetch, trace access, template rendering, and media mirror
operations are **not** on `Backend`. Re-reading DESIGN §8.2/§8.3: the plan
table only ever compares base (manifest) / local (compiled) / remote (backend
`list_remote`) — it never consults registry data. Those concerns belong to
`DirectBackend` directly (M6) or to other modules layered on top of it; adding
them here would widen the seam every future `Backend` implementer has to
satisfy for no sync-engine benefit.

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
DSL* is M7's job (DESIGN §8.2); this is only the structured data.

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
transactional" paragraph; MILESTONES M5 test 3, `test_apply_reverifies_hashes`).
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
`datetime.now()` or anything else wall-clock-shaped (R8); the CLI layer (M7)
is what actually knows the time. `Manifest.canonical_json()` reuses
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
caller keeps its old manifest (MILESTONES M5 test 6,
`test_manifest_updates_only_on_success`).

## 3. The `SourceWriter` seam

`hassle.sync.source_writer.SourceWriter` decouples the sync engine's pull-side
actions from M2's LibCST-based splicer, which lives on a parallel,
not-yet-merged branch. The pull engine (`hassle.sync.pull`) only depends on
this Protocol:

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
  `test_splice_preserves_rest_of_file`, M2's job). Used for `refresh`.
- `delete_object` — remove an object's source (`drop`). May delete the whole
  file if that was the object's only definition.

**M2 will implement `SourceWriter` for real** with the LibCST splicer at
integration time. M5 ships two implementations so its own tests can exercise
the seam without M2:

- `WholeFileSourceWriter` — a blunt but correct stand-in: every operation
  is a whole-file write or delete (`splice_object` degrades to
  `write_whole_file`). Good enough for `adopt`, acceptable for `refresh`/`drop`
  until M2 lands.
- `RecordingSourceWriter` — an in-memory test double (no disk I/O) that
  records every call for assertions; used throughout the pull-engine unit
  tests and the I6 fuzz test.

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

M7 owns real conflict UX (a rich 3-way *DSL*-level diff, DESIGN §8.2); this
format only exists so a human (or M7, at integration time) can see both sides
of a conflict from M5's output today.

## 3.1. Config-entry template-helper addendum (M10, additive — `Backend` unchanged)

MILESTONES M10 adds the first config-entry `ObjectType` plugin (DESIGN §13),
scoped to the `template` domain (`hassle.ir.TEMPLATE_DOMAINS`:
`template_number`/`template_sensor`/`template_binary_sensor`/
`template_select`). This needed **zero changes to the `Backend` Protocol**:
`list_remote`/`create`/`update`/`delete` are exactly the same four methods,
addressed the same `(kind, identity)` way. What differs is entirely internal
to `FakeBackend`/`DirectBackend`:

- **Identity.** `identity` is the declared `unique_id` (the DSL's `id=`
  kwarg) — frozen as the object-key identity in the M10 PR. HA's own
  config-entry identity, the `entry_id` it assigns on creation
  (docs/ha-api-notes.md §26), is transport-side only.
- **`ManifestEntry.entry_id`** (additive optional field, `hassle.sync.models`):
  where the `entry_id` is tracked — never in the IR body, never in the
  object key. `apply.py`'s `_advance_manifest` populates it by calling an
  **additive, non-Protocol** `entry_id_for(kind, identity) -> str | None`
  method both `FakeBackend` and `DirectBackend` expose (probed defensively
  via `getattr`, the same pattern `fetch_registry_snapshot` already
  established for backend extras outside F2) — a `Backend` implementer that
  doesn't expose it (hypothetically, a backend with no config-entry kinds at
  all) simply gets `entry_id=None` forever, which is harmless: nothing else
  reads it except a future DirectBackend needing it to address
  `config_entries/options/flow` by entry_id rather than re-deriving it.
- **Internally:** `create`/`update` drive a simulated (`FakeBackend`) or real
  (`DirectBackend`, M10) multi-step config-entry flow / options-flow to
  completion inside the single synchronous method call — the Protocol's
  caller (the sync engine) never sees the intermediate flow steps, exactly as
  it never sees the helper `{domain}_id` payload-key convention (quirk #1)
  either. `delete` is a plain entry removal by `entry_id`.
  **Transport correction (found via CI, docs/ha-api-notes.md §26.0):** flow
  create/step-submission, options-flow create/step-submission, and entry
  removal are all **REST**, not WebSocket (`POST /api/config/config_entries/
  flow[/{flow_id}]`, `POST /api/config/config_entries/options/flow[/{flow_id}]`,
  `DELETE /api/config/config_entries/entry/{entry_id}`) — only entry
  *listing* (`config_entries/get`) is WS. The original implementation drove
  all of these over WS and failed identically against both HA `stable` and
  `dev` with `Unknown command`; `DirectBackend` now uses `HaClient.rest_post`/
  `rest_delete` for every write path.
- **Apply order** (`hassle.sync.apply._KIND_ORDER`): the four template
  domains slot in after the nine storage helpers, before scripts — same
  dependency-ordering rationale (an automation/script may reference a
  template helper's entity id, so it must exist first).

See docs/ha-api-notes.md §26 for the full flow-shape capture notes and the
rollback entry_id-changes caveat.

### 3.1.1 What a new config-entry domain needs (proving the follow-ons are mechanical)

DESIGN §13 names `threshold`/`derivative`/`group`/… as future config-entry
helper plugins after `template`. Scoping M10 to one domain only pays off if
adding the next one is small and mechanical, not a repeat of this milestone's
design work. Concretely, a new domain (e.g. `threshold`) needs:

1. **IR:** a domain string added to a `*_DOMAINS` frozenset next to
   `TEMPLATE_DOMAINS` (`hassle.ir.keys`) — or, if it shares the exact same
   options shape as `TemplateHelperConfig` (`unique_id`/`name` + passthrough
   extras), no new IR class at all; a genuinely different shape gets its own
   thin `IRObject` subclass mirroring `TemplateHelperConfig` (~15 lines).
2. **DSL:** one builder function per new domain in a sibling module to
   `hassle.compiler.template_helpers`, reusing `_declare_helper`'s pattern
   (validate domain membership, build the IR object, register via
   `current_registry().add_object`, return an `EntityRef`) — no new
   registration mechanism.
3. **FakeBackend:** the SAME three internal methods
   (`_create_via_flow`/`_update_via_options_flow`/`entry_id_for`, or a shared
   helper extracted from them if a second domain makes the duplication worth
   collapsing) dispatch on the new domain's `_TEMPLATE_FLOW_TYPE`-equivalent
   step_id map — `create`/`update`/`delete`/`list_remote` themselves need NO
   change (they already dispatch on `kind in TEMPLATE_DOMAINS`-shaped
   membership checks; widen the membership set or add a sibling one).
4. **DirectBackend:** same shape — the REST flow/options-flow/entry-removal
   endpoints (`/api/config/config_entries/flow[/{flow_id}]`, `/api/config/
   config_entries/options/flow[/{flow_id}]`, `/api/config/config_entries/
   entry/{entry_id}`, §26.0) are **generic across every config-entry
   integration** (`handler=<domain integration name>` is the only per-domain
   parameter on the start-flow POST); only the step_id/field-name map is
   domain-specific.
5. **Decompiler/placement:** `_template_helper_source`'s `unique_id` -> `id=`
   rename logic is already generic per-domain (keyed off `TEMPLATE_DOMAINS`
   membership, not a hardcoded domain name); `default_source_path`'s
   `helpers/misc.py` rule already covers `TEMPLATE_DOMAINS` as a set, so a
   domain added to that set needs no placement-code change at all.
6. **Apply order / validation / ignore-glob:** all three are driven by
   `hassle.ir.OBJECT_KINDS` membership or plain object-key string matching —
   zero code changes for a new domain that's added to `OBJECT_KINDS`.

In short: steps 1-2 are the only places that see genuinely new code per
domain (an IR shape + a DSL builder); steps 3-6 are membership-set additions
into machinery this milestone already built generically. This is the
concrete evidence for MILESTONES M10's "mechanical follow-ons" framing.

## 4. Where things live

- `hassle.backend` — `Backend` Protocol (`protocol.py`), `FakeBackend`
  (`fake.py`, M5-only; `DirectBackend` arrives in M6 as a sibling module).
- `hassle.sync` — `PlanAction`/`Plan`/`PlanEntry`/`Conflict`/`ConflictKind`/
  `Manifest`/`ManifestEntry`/`ApplyResult`/`ApplyOutcome` (`models.py`),
  `SourceWriter`/`WholeFileSourceWriter`/`RecordingSourceWriter`
  (`source_writer.py`), `compute_plan` (`plan.py`), `apply_plan` (`apply.py`),
  `apply_pull` (`pull.py`).
