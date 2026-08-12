"""blueprints-design §3's plan table -- the binding spec, row by row.

A blueprint is push-authoritative (§2.1: HA cannot serve the source back), so
the generic base/local/remote hash comparison does not apply: local and remote
bodies are deliberately different shapes. Existence comes from
``blueprint/list``, content from the manifest's stored hash of the local file
at last push, and drift is optionally corroborated by the substitute-compare
oracle (§2.2).

| Local file | In manifest | Remote (list) | Plan row |
|---|---|---|---|
| yes | no  | no  | `create` |
| yes | no  | yes | `conflict` — remote has a same-path blueprint Hassle didn't put there |
| yes | yes | yes, hash differs from manifest | `update` |
| yes | yes | yes, substitute-compare mismatch | `conflict` — the remote copy was edited in place |
| no  | yes | yes | `delete` |
| no  | no  | yes | `adopt (unmanageable)` — warning row only |
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.blueprints import blueprint_body, blueprint_metadata, blueprint_remote_body
from hassle.ir import BLUEPRINT_KIND, sha256_hash
from hassle.sync.models import ConflictKind, Manifest, ManifestEntry, PlanAction
from hassle.sync.plan import compute_plan

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions: []
"""

PATH = "local/room-switch-controls.yaml"
KEY = f"blueprint:automation/{PATH}"


def _local(source: str = SOURCE) -> dict[str, Any]:
    return blueprint_body(domain="automation", path=PATH, source=source)


def _remote(source: str = SOURCE) -> dict[str, Any]:
    return blueprint_remote_body("automation", PATH, blueprint_metadata(source))


def _manifest(source: str | None = SOURCE) -> Manifest:
    objects: dict[str, ManifestEntry] = {}
    if source is not None:
        objects[KEY] = ManifestEntry(
            source=f"blueprints/automation/{PATH}",
            compiled_hash=sha256_hash(_local(source)),
            kind="blueprint",
        )
    return Manifest(synced_at="2026-08-10T00:00:00Z", ha_version="2026.8.0", objects=objects)


def _plan(
    *,
    local: dict[str, Any] | None,
    remote: dict[str, Any] | None,
    manifest_source: str | None,
    drift: frozenset[str] = frozenset(),
):
    return compute_plan(
        manifest=_manifest(manifest_source),
        local_objects={KEY: (BLUEPRINT_KIND, local)} if local is not None else {},
        remote_objects={KEY: (BLUEPRINT_KIND, remote)} if remote is not None else {},
        blueprint_drift=drift,
    ).entry_for(KEY)


# --- row 1: yes | no | no -> create ----------------------------------------


def test_local_only_and_unmanaged_is_a_create() -> None:
    entry = _plan(local=_local(), remote=None, manifest_source=None)
    assert entry is not None
    assert entry.action is PlanAction.CREATE
    assert entry.local == _local()


# --- row 2: yes | no | yes -> conflict -------------------------------------


def test_local_and_unexpected_remote_is_a_conflict() -> None:
    entry = _plan(local=_local(), remote=_remote(), manifest_source=None)
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT
    assert entry.conflict is not None
    assert entry.conflict.kind is ConflictKind.BOTH_EDITED


def test_the_unexpected_remote_conflict_explains_both_resolutions() -> None:
    """§3: resolve `--accept-local` (overwrite), or copy HA's semantics into
    the bundle by hand -- there is no source read, so Hassle cannot do the
    second for you."""
    entry = _plan(local=_local(), remote=_remote(), manifest_source=None)
    assert entry is not None and entry.message is not None
    assert "--accept-local" in entry.message
    assert "by hand" in entry.message


# --- row 3: yes | yes | yes, hash differs -> update -------------------------


def test_edited_local_file_is_an_update() -> None:
    edited = SOURCE.replace("restart", "single")
    entry = _plan(local=_local(edited), remote=_remote(), manifest_source=SOURCE)
    assert entry is not None
    assert entry.action is PlanAction.UPDATE
    assert entry.local == _local(edited)


def test_an_unedited_local_file_is_a_noop() -> None:
    entry = _plan(local=_local(), remote=_remote(), manifest_source=SOURCE)
    assert entry is not None
    assert entry.action is PlanAction.NOOP


def test_an_update_carries_the_remote_hash_for_reverification() -> None:
    """apply re-verifies against this immediately before writing (DESIGN §8.2).
    For a blueprint the remote body is metadata, so the hash covers metadata --
    which still catches somebody replacing the remote blueprint between plan
    and apply."""
    edited = SOURCE.replace("restart", "single")
    entry = _plan(local=_local(edited), remote=_remote(), manifest_source=SOURCE)
    assert entry is not None
    assert entry.remote_hash_at_plan == sha256_hash(_remote())


# --- row 4: yes | yes | yes, substitute-compare mismatch -> conflict --------


def test_substitute_compare_mismatch_is_a_conflict() -> None:
    entry = _plan(local=_local(), remote=_remote(), manifest_source=SOURCE, drift=frozenset({KEY}))
    assert entry is not None
    assert entry.action is PlanAction.CONFLICT


def test_drift_on_an_EDITED_local_file_is_an_update_not_a_conflict() -> None:
    """Regression (R4), caught by the golden bundle: escalating here would
    make EVERY ordinary blueprint edit a conflict.

    `blueprint/substitute` compares HA's copy against the bundle's copy AS IT
    IS NOW -- the BASE version cannot be expanded (the manifest stores only its
    hash, and HA will not serve a source back). So when the local file has
    changed, the mismatch is fully explained by that change and says nothing
    about the remote side. The drift row therefore applies only when the local
    file is UNCHANGED since base, where the difference can have come from
    nowhere else.
    """
    edited = SOURCE.replace("restart", "single")
    entry = _plan(
        local=_local(edited), remote=_remote(), manifest_source=SOURCE, drift=frozenset({KEY})
    )
    assert entry is not None
    assert entry.action is PlanAction.UPDATE


def test_the_drift_conflict_says_the_remote_was_edited_in_place() -> None:
    entry = _plan(local=_local(), remote=_remote(), manifest_source=SOURCE, drift=frozenset({KEY}))
    assert entry is not None and entry.message is not None
    assert "edited in place" in entry.message
    assert "--accept-local" in entry.message


def test_drift_is_opt_in_and_absent_by_default() -> None:
    """§3: "when enabled". Omitting the argument entirely must reproduce the
    pre-oracle behaviour exactly."""
    entry = _plan(local=_local(), remote=_remote(), manifest_source=SOURCE)
    assert entry is not None
    assert entry.action is PlanAction.NOOP


# --- row 5: no | yes | yes -> delete ---------------------------------------


def test_a_removed_local_file_is_a_delete() -> None:
    entry = _plan(local=None, remote=_remote(), manifest_source=SOURCE)
    assert entry is not None
    assert entry.action is PlanAction.DELETE
    assert entry.remote_hash_at_plan == sha256_hash(_remote())


# --- row 6: no | no | yes -> adopt (unmanageable) --------------------------


def test_a_remote_only_blueprint_is_an_unmanageable_adopt() -> None:
    entry = _plan(local=None, remote=_remote(), manifest_source=None)
    assert entry is not None
    assert entry.action is PlanAction.ADOPT


def test_the_unmanageable_adopt_says_exactly_what_a_human_must_do() -> None:
    """§3: "HA cannot serve the source, so adopting requires a human to place
    the file in `blueprints/<domain>/<path>`; the row's message says exactly
    that"."""
    entry = _plan(local=None, remote=_remote(), manifest_source=None)
    assert entry is not None and entry.message is not None
    assert f"blueprints/automation/{PATH}" in entry.message


def test_the_unmanageable_adopt_is_a_warning_row_only() -> None:
    """It must never be actioned: apply only ever executes create/update/
    delete, and pull excludes the kind from writes entirely (§5). Pinning the
    action as ADOPT (rather than inventing a new PlanAction) is what keeps the
    frozen action set of DESIGN §8.2 exactly as wide as it was."""
    entry = _plan(local=None, remote=_remote(), manifest_source=None)
    assert entry is not None
    assert entry.action is PlanAction.ADOPT
    assert entry.local is None
    assert entry.warning is True


# --- rows the design's table leaves implicit -------------------------------


def test_a_remotely_deleted_blueprint_is_re_created() -> None:
    """Not in §3's six rows. The bundle has the file and HA does not, so the
    only non-destructive answer is to push it -- identical to row 1. A `drop`
    here (the generic table's answer) would delete an authored file because
    somebody removed it in HA, which I6 forbids."""
    entry = _plan(local=_local(), remote=None, manifest_source=SOURCE)
    assert entry is not None
    assert entry.action is PlanAction.CREATE


def test_gone_from_both_sides_is_a_drop() -> None:
    """Also implicit: nothing to push either way, and the stale manifest entry
    should not survive. Matches the generic table's "both sides gone" row."""
    entry = _plan(local=None, remote=None, manifest_source=SOURCE)
    assert entry is not None
    assert entry.action is PlanAction.DROP


# --- the rest of the plan is untouched --------------------------------------


def test_other_kinds_are_unaffected_by_the_blueprint_branch() -> None:
    plan = compute_plan(
        manifest=Manifest(synced_at="x", ha_version="y", objects={}),
        local_objects={"automation:a": ("automation", {"id": "a", "alias": "A"})},
        remote_objects={},
    )
    entry = plan.entry_for("automation:a")
    assert entry is not None
    assert entry.action is PlanAction.CREATE
    assert entry.message is None
    assert entry.warning is False


@pytest.mark.parametrize(
    "action",
    [PlanAction.CREATE, PlanAction.UPDATE, PlanAction.DELETE, PlanAction.NOOP],
)
def test_non_warning_rows_never_set_the_warning_flag(action: PlanAction) -> None:
    cases: dict[PlanAction, dict[str, Any]] = {
        PlanAction.CREATE: {"local": _local(), "remote": None, "manifest_source": None},
        PlanAction.UPDATE: {
            "local": _local(SOURCE.replace("restart", "single")),
            "remote": _remote(),
            "manifest_source": SOURCE,
        },
        PlanAction.DELETE: {"local": None, "remote": _remote(), "manifest_source": SOURCE},
        PlanAction.NOOP: {"local": _local(), "remote": _remote(), "manifest_source": SOURCE},
    }
    entry = _plan(**cases[action])
    assert entry is not None
    assert entry.action is action
    assert entry.warning is False
