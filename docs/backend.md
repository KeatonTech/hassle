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

## 4. Where things live

- `hassle.backend` — `Backend` Protocol (`protocol.py`), `FakeBackend`
  (`fake.py`, M5-only; `DirectBackend` arrives in M6 as a sibling module).
- `hassle.sync` — `PlanAction`/`Plan`/`PlanEntry`/`Conflict`/`ConflictKind`/
  `Manifest`/`ManifestEntry`/`ApplyResult`/`ApplyOutcome` (`models.py`),
  `SourceWriter`/`WholeFileSourceWriter`/`RecordingSourceWriter`
  (`source_writer.py`), `compute_plan` (`plan.py`), `apply_plan` (`apply.py`),
  `apply_pull` (`pull.py`).
