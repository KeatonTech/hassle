"""Regression: a `delete` planned by `compute_plan` actually applies.

Bug: `compute_plan` produced `delete` entries with no `remote_hash_at_plan`, but
`apply_plan` re-verifies the remote hash before deleting (DESIGN §8.2). With the
field unset, the re-verify saw ``None != <live hash>`` and aborted every delete
as spurious drift. No prior test ran a `compute_plan` delete entry through
`apply_plan`, so it went unnoticed.
"""

from __future__ import annotations

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import ApplyOutcome, Manifest, ManifestEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan


def test_planned_delete_applies_end_to_end() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "gone", "alias": "Delete me"})
    remote = backend.list_remote("automation")[identity]

    manifest = Manifest(
        synced_at="base",
        ha_version="v",
        objects={
            "automation:gone": ManifestEntry(source="a.py", compiled_hash=sha256_hash(remote))
        },
    )

    # Local deleted, remote untouched since base -> `delete`.
    plan = compute_plan(
        manifest=manifest,
        local_objects={},
        remote_objects={"automation:gone": ("automation", remote)},
    )
    entry = plan.entry_for("automation:gone")
    assert entry is not None
    assert entry.remote_hash_at_plan == sha256_hash(remote)  # populated for re-verify

    result = apply_plan(plan, backend, manifest, synced_at="after")
    assert result.succeeded is True, result.outcomes
    assert result.outcomes["automation:gone"] is ApplyOutcome.SUCCEEDED
    assert "gone" not in backend.list_remote("automation")


def test_planned_delete_aborts_if_remote_drifted() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "gone", "alias": "Delete me"})
    remote = backend.list_remote("automation")[identity]
    manifest = Manifest(
        synced_at="base",
        ha_version="v",
        objects={
            "automation:gone": ManifestEntry(source="a.py", compiled_hash=sha256_hash(remote))
        },
    )
    plan = compute_plan(
        manifest=manifest,
        local_objects={},
        remote_objects={"automation:gone": ("automation", remote)},
    )
    # Remote drifts between plan and apply: the delete must abort, not proceed.
    backend.update("automation", identity, {"id": "gone", "alias": "Edited in UI"})

    result = apply_plan(plan, backend, manifest)
    assert result.succeeded is False
    assert result.outcomes["automation:gone"] is ApplyOutcome.ABORTED
    assert "gone" in backend.list_remote("automation")  # not deleted
