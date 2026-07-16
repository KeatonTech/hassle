"""The core edit loop, end to end against real HA.

pull → edit one automation + add one helper + delete one script (+ a local test
file that is bundle-only) → plan shows **exactly 3** changes → push → HA state
verified via HA's own API → pull again → the hand-written source of the
untouched automation and the local test file are **never rewritten** (source
preservation is local; pull only rewrites objects whose live config drifted from
the manifest baseline — DESIGN §7.3, §8.3).
"""

from __future__ import annotations

from pathlib import Path

from hassle.backend import DirectBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import Manifest, ManifestEntry, PlanAction
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan
from hassle.sync.pull import apply_pull
from hassle.sync.source_writer import RecordingSourceWriter

ObjMap = dict[str, tuple[str, dict[str, object]]]


def _remote_objmap(ha: DirectBackend, kinds: tuple[str, ...]) -> ObjMap:
    out: ObjMap = {}
    for kind in kinds:
        for identity, config in ha.list_remote(kind).items():
            out[f"{kind}:{identity}"] = (kind, config)
    return out


def _manifest_from(objmap: ObjMap, sources: dict[str, str]) -> Manifest:
    return Manifest(
        synced_at="base",
        ha_version="test",
        objects={
            key: ManifestEntry(source=sources.get(key), compiled_hash=sha256_hash(config))
            for key, (_kind, config) in objmap.items()
        },
    )


def _seed(ha: DirectBackend) -> None:
    ha.create("input_boolean", {"id": "existing_flag", "name": "Existing Flag"})
    ha.create(
        "automation",
        {"id": "edit_me", "alias": "Edit me", "trigger": [], "condition": [], "action": []},
    )
    ha.create(
        "automation",
        {"id": "leave_me", "alias": "Leave me", "trigger": [], "condition": [], "action": []},
    )
    ha.create("script", {"id": "delete_me", "alias": "Delete me", "sequence": []})


def test_core_loop_three_changes_and_source_preservation(ha: DirectBackend, tmp_path: Path) -> None:
    _seed(ha)
    kinds = ("automation", "script", "input_boolean")

    # --- baseline: manifest == current remote, hand-written sources on disk -----
    base = _remote_objmap(ha, kinds)
    sources = {
        "automation:edit_me": "automations/edit_me.py",
        "automation:leave_me": "automations/leave_me.py",
        "script:delete_me": "scripts/delete_me.py",
        "input_boolean:existing_flag": "helpers/flags.py",
    }
    manifest = _manifest_from(base, sources)

    # Hand-written files on disk (their bytes must survive the loop untouched).
    (tmp_path / "automations").mkdir()
    leave_me_file = tmp_path / "automations" / "leave_me.py"
    leave_me_file.write_text("# hand-written, do not touch\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests" / "test_leave_me.py"
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    leave_me_before = leave_me_file.read_bytes()
    test_before = test_file.read_bytes()

    # --- local edits ------------------------------------------------------------
    local = dict(base)
    local["automation:edit_me"] = (
        "automation",
        {"id": "edit_me", "alias": "Edited locally", "trigger": [], "condition": [], "action": []},
    )
    local["input_boolean:new_helper"] = (
        "input_boolean",
        {"id": "new_helper", "name": "New Helper"},
    )
    del local["script:delete_me"]  # deleted locally

    # --- plan: exactly three push changes --------------------------------------
    remote = _remote_objmap(ha, kinds)
    plan = compute_plan(manifest=manifest, local_objects=local, remote_objects=remote)
    push = [
        e
        for e in plan.entries
        if e.action in (PlanAction.UPDATE, PlanAction.CREATE, PlanAction.DELETE)
    ]
    assert len(push) == 3, [f"{e.object_key}:{e.action}" for e in plan.entries]
    assert plan.entry_for("automation:edit_me").action is PlanAction.UPDATE
    assert plan.entry_for("input_boolean:new_helper").action is PlanAction.CREATE
    assert plan.entry_for("script:delete_me").action is PlanAction.DELETE
    assert plan.entry_for("automation:leave_me").action is PlanAction.NOOP

    # --- push and verify against HA's own API ----------------------------------
    result = apply_plan(plan, ha, manifest, synced_at="after")
    assert result.succeeded is True, result.outcomes
    assert result.manifest is not None

    after = _remote_objmap(ha, kinds)
    assert after["automation:edit_me"][1]["alias"] == "Edited locally"
    assert "input_boolean:new_helper" in after
    assert "script:delete_me" not in after
    assert "automation:leave_me" in after  # untouched object still present

    # --- pull again into the same working tree ---------------------------------
    # Local == what we just pushed (no further local edits); the new manifest is
    # the post-apply baseline. Nothing drifted in the UI, so the pull plan must
    # produce zero bundle-side rewrites — the hand-written file and test are safe.
    local2 = dict(local)  # our working tree now matches what we pushed
    pull_plan = compute_plan(manifest=result.manifest, local_objects=local2, remote_objects=after)
    writer = RecordingSourceWriter()
    apply_pull(pull_plan, writer)

    assert writer.written_files == {}
    assert writer.spliced_objects == []
    assert writer.deleted_objects == []
    # And the actual on-disk bytes are identical.
    assert leave_me_file.read_bytes() == leave_me_before
    assert test_file.read_bytes() == test_before
