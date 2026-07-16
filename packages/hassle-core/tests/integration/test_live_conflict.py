"""MILESTONES M6 test 3 — conflict end-to-end against real HA.

After pull, edit an automation via HA's API (simulating a UI edit) *and* edit the
same object locally, to different values. `compute_plan` reports a `conflict`
(both_edited). Then both resolution paths are verified against HA:

- `--accept-local`: the local version is pushed; HA ends up with the local edit.
- `--accept-remote`: HA is left as the UI edited it (no write); the working tree
  takes the remote version (pull-side refresh).

Resolution flag handling proper is M7's CLI concern; here we model each path's
effect and assert it against real HA.
"""

from __future__ import annotations

from hassle.backend import DirectBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import (
    ConflictKind,
    Manifest,
    ManifestEntry,
    Plan,
    PlanAction,
    PlanEntry,
)
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan
from hassle.sync.pull import apply_pull
from hassle.sync.source_writer import RecordingSourceWriter

_KEY = "automation:conflicted"


def _seed_and_baseline(ha: DirectBackend) -> Manifest:
    ha.create(
        "automation",
        {"id": "conflicted", "alias": "Original", "trigger": [], "condition": [], "action": []},
    )
    base = ha.list_remote("automation")["conflicted"]
    return Manifest(
        synced_at="base",
        ha_version="test",
        objects={_KEY: ManifestEntry(source="automations/c.py", compiled_hash=sha256_hash(base))},
    )


def _diverge(ha: DirectBackend) -> tuple[dict[str, object], dict[str, object]]:
    """Edit remote (UI) and produce a different local edit."""
    ha.update(
        "automation",
        "conflicted",
        {"id": "conflicted", "alias": "UI edit", "trigger": [], "condition": [], "action": []},
    )
    remote = ha.list_remote("automation")["conflicted"]
    local = {
        "id": "conflicted",
        "alias": "Local edit",
        "trigger": [],
        "condition": [],
        "action": [],
    }
    return local, remote


def test_conflict_is_detected(ha: DirectBackend) -> None:
    manifest = _seed_and_baseline(ha)
    local, remote = _diverge(ha)
    plan = compute_plan(
        manifest=manifest,
        local_objects={_KEY: ("automation", local)},
        remote_objects={_KEY: ("automation", remote)},
    )
    entry = plan.entry_for(_KEY)
    assert entry.action is PlanAction.CONFLICT
    assert entry.conflict is not None
    assert entry.conflict.kind is ConflictKind.BOTH_EDITED


def test_accept_local_pushes_local_to_ha(ha: DirectBackend) -> None:
    _seed_and_baseline(ha)
    local, remote = _diverge(ha)
    # --accept-local: apply the local version as an UPDATE, re-verifying the
    # remote hash we saw at plan time (transactional apply).
    plan = Plan(
        entries=[
            PlanEntry(
                object_key=_KEY,
                kind="automation",
                action=PlanAction.UPDATE,
                local=local,
                remote_hash_at_plan=sha256_hash(remote),
            )
        ]
    )
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    result = apply_plan(plan, ha, manifest, synced_at="resolved")
    assert result.succeeded is True
    assert ha.list_remote("automation")["conflicted"]["alias"] == "Local edit"


def test_accept_remote_leaves_ha_and_refreshes_local(ha: DirectBackend) -> None:
    _seed_and_baseline(ha)
    _local, remote = _diverge(ha)
    # --accept-remote: HA is not written; the working tree takes the remote
    # version via a pull-side refresh.
    refresh_plan = Plan(
        entries=[
            PlanEntry(
                object_key=_KEY,
                kind="automation",
                action=PlanAction.REFRESH,
                remote=remote,
                source_path="automations/c.py",
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(refresh_plan, writer)
    # HA still shows the UI edit (untouched).
    assert ha.list_remote("automation")["conflicted"]["alias"] == "UI edit"
    # Local source was refreshed with the remote version.
    assert len(writer.spliced_objects) == 1
    assert writer.spliced_objects[0][1] == _KEY
