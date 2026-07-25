"""The frozen plan/apply data model — DESIGN §8.1, §8.2.

`PlanAction` is the exact set of outcomes in the DESIGN §8.2 table. `Plan` is
one `PlanEntry` per object key, produced by :func:`hassle.sync.plan.compute_plan`
and consumed by :func:`hassle.sync.apply.apply_plan` (push-side actions) and
:func:`hassle.sync.pull.apply_pull` (bundle-side actions). `Manifest` is the
`manifest.lock` model (DESIGN §8.1) — a plain data model with no wall-clock or
other side effects; `synced_at` is always caller-supplied.

Style note: pydantic `BaseModel`, matching `hassle.ir.models` for consistency
within the codebase. Unlike the IR models, these are *not* meant to preserve
arbitrary unknown fields forever (they aren't an HA wire format) — but they
do store full config dicts (never lossy summaries): nothing the sync engine
looks at is ever thrown away before a human or the CLI layer can see it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from hassle.ir.canonical import canonical_json


class PlanAction(StrEnum):
    """The exact action set of the DESIGN §8.2 table."""

    NOOP = "noop"
    UPDATE = "update"
    DELETE = "delete"
    REFRESH = "refresh"
    CONFLICT = "conflict"
    DROP = "drop"
    CREATE = "create"
    ADOPT = "adopt"


class ConflictKind(StrEnum):
    """The three distinct conflict subtypes named in DESIGN §8.2's table rows."""

    # "different | different" row: both base-vs-local and base-vs-remote changed,
    # to different values.
    BOTH_EDITED = "both_edited"
    # "different (UI edit) | local deleted" row.
    DELETED_LOCALLY_EDITED_REMOTELY = "deleted_locally_edited_remotely"
    # "remote deleted | different" row.
    EDITED_LOCALLY_DELETED_REMOTELY = "edited_locally_deleted_remotely"


class Conflict(BaseModel):
    """Structured conflict data (DESIGN §8.2). Rendering (3-way diff) is the CLI's job."""

    model_config = ConfigDict(frozen=True)

    object_key: str
    kind: ConflictKind
    base: dict[str, Any] | None
    local: dict[str, Any] | None
    remote: dict[str, Any] | None


class PlanEntry(BaseModel):
    """One object key's plan outcome."""

    model_config = ConfigDict(frozen=True)

    object_key: str
    kind: str
    action: PlanAction

    # Full config payloads (never summarized — see module docstring). Present
    # depending on `action`; `None` where not applicable (e.g. no `local` for a
    # pure `adopt`/`drop`).
    base: dict[str, Any] | None = None
    local: dict[str, Any] | None = None
    remote: dict[str, Any] | None = None

    # The canonical hash of the remote object *at plan time* — apply.py
    # re-verifies against this immediately before writing (test_apply_reverifies_hashes).
    remote_hash_at_plan: str | None = None

    # Where the bundle source for this object lives (or should be created);
    # used by the pull engine to route SourceWriter calls. `None` is valid for
    # push-only entries in tests that don't exercise pull.
    source_path: str | None = None

    # Present only when action is CONFLICT.
    conflict: Conflict | None = None


class Plan(BaseModel):
    """A full plan: one `PlanEntry` per object key."""

    model_config = ConfigDict(frozen=True)

    entries: list[PlanEntry] = []

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, index: int) -> PlanEntry:
        return self.entries[index]

    def __iter__(self):  # type: ignore[override]
        return iter(self.entries)

    def entry_for(self, object_key: str) -> PlanEntry | None:
        for entry in self.entries:
            if entry.object_key == object_key:
                return entry
        return None

    def entries_with_action(self, action: PlanAction) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.action is action]


class ManifestEntry(BaseModel):
    """One object's entry in `manifest.lock` (DESIGN §8.1).

    ``entry_id`` (additive/optional): for a config-entry template-helper
    (``hassle.ir.TEMPLATE_DOMAINS``) or group-helper (``hassle.ir.GROUP_DOMAINS``)
    object, the HA-assigned config entry id (docs/internals/ha-api-notes.md §26.5/§38)
    -- transport-side identity only, never the object-key identity
    (``unique_id``) and never part of the IR body (docs/internals/backend-protocol.md's
    config-entry addendum). ``None`` for every other kind (automation/script/
    storage-collection helper), which have no such secondary identity to
    track.

    ``category`` (additive/optional): the object's HA UI category **slug**
    as of the last successful sync (base, in the three-way sense) -- ``None``
    means "uncategorized as of base" (including an older manifest that
    parses with this field absent). `hassle.sync.category_move` uses this to
    detect a local file move vs. a remote (HA UI) recategorization since
    base, and to surface a conflict (no local or UI edit is ever silently
    lost) rather than silently letting either side win when both changed to
    different values. Never the display name (that's transient HA-side
    state, not tracked here) -- just the slug `bundle_ops`'s placement
    already anchors on (docs/internals/ha-api-notes.md §22/§30).
    """

    model_config = ConfigDict(frozen=True)

    source: str | None
    compiled_hash: str
    kind: str = "dsl"  # dsl | raw | blueprint
    entry_id: str | None = None
    category: str | None = None


class Manifest(BaseModel):
    """The `manifest.lock` model (DESIGN §8.1).

    `synced_at` is always supplied by the caller (the CLI layer supplies
    wall-clock); core logic never calls `datetime.now()` or similar.
    """

    synced_at: str
    ha_version: str
    objects: dict[str, ManifestEntry] = {}

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Manifest:
        return cls.model_validate(data)

    def canonical_json(self) -> str:
        return canonical_json(self.to_json_dict())


class ApplyOutcome(StrEnum):
    """Per-object outcome of an apply attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ABORTED = "aborted"  # never attempted because an earlier hash re-verify failed
    #: Applied, then the rollback attempt itself failed: the remote still
    #: holds this object's NEW state while the run as a whole failed. The
    #: apply's failure_message names these objects (what/where/fix).
    ROLLBACK_FAILED = "rollback_failed"


class ApplyResult(BaseModel):
    """The result of a full `apply_plan` run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    outcomes: dict[str, ApplyOutcome] = {}
    succeeded: bool
    manifest: Manifest | None = None
    #: Additive: WHY the failing entry
    #: failed, when the apply engine knows -- e.g. the created-identity
    #: divergence message naming the id HA actually derived. `None` for
    #: successes and for failures with no better story than the outcome enum.
    failure_message: str | None = None
    # Additive: non-fatal warnings from category write-back on CREATE
    # (`hassle.sync.category_writeback`) -- always empty when nothing was
    # attempted or everything succeeded. Never affects `succeeded` (a
    # category-assignment failure is metadata-only, surfaced here rather than
    # silently dropped, but never fails or rolls back the object it's about).
    category_warnings: list[str] = []
    # Additive: category-on-move conflicts (`hassle.sync.category_move`)
    # -- an object whose LOCAL category (derived from its source file) and
    # REMOTE category (HA UI) both changed since the manifest's recorded base,
    # to DIFFERENT values. Distinct from `category_warnings` (a failure to
    # apply an otherwise-uncontested change): a conflict is never even
    # attempted in either direction (never silently overwritten), and
    # the manifest's base category is left UNCHANGED so the next plan/push
    # surfaces the same conflict again rather than quietly resolving it.
    # Never affects `succeeded`/rollback for the object's own content update.
    category_conflicts: list[str] = []
