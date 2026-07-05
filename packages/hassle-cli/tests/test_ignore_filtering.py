"""DESIGN §8.2 amendment (owner decision, `ux/pull-organization`): `hassle.toml`'s
`ignore = [...]` globs (fnmatch on object keys) let a user permanently exclude
objects Hassle must never touch -- e.g. UI-generated `input_boolean.material_you_*`
helpers HA itself churns out. This REVISES §8.2's "first-ever pull adopts
everything; nothing is ever unmanaged" -- ignored keys are the one deliberate
exception, and the exclusion happens *before* `compute_plan` ever sees them, so
the plan engine itself (F2, table-driven, MILESTONES M5) needs no change.

Semantics under test:
1. An ignored key present only remotely (never adopted) produces NO plan entry,
   even though a bare `compute_plan` over the same inputs would call that
   `adopt` -- the filter runs before `compute_plan`.
2. THE SAFETY PROPERTY: an ignored key present remotely but ABSENT locally
   must never plan a `delete` (or any action) -- a push must not be able to
   touch it, no matter what local looks like.
3. A LOCAL object matching an ignore glob is excluded from the plan too, and
   emits a warning Finding (declared-but-ignored is a likely user mistake).
4. Manifest migration: an existing manifest entry whose key newly matches an
   ignore glob is dropped from the manifest (with a notice), without any HA
   write.
"""

from __future__ import annotations

from hassle.sync.models import Manifest, ManifestEntry
from hassle_cli.ignore_filter import apply_ignore_globs, migrate_manifest_for_ignores

_AUTOMATION_CFG = {"id": "a", "alias": "A", "triggers": [], "conditions": [], "actions": []}
_HELPER_CFG = {"id": "material_you_primary_color", "name": "Material You Primary Color"}


def test_ignored_remote_only_key_produces_no_entry() -> None:
    local = {}
    remote = {"input_boolean:material_you_primary_color": ("input_boolean", _HELPER_CFG)}
    result = apply_ignore_globs(
        local_objects=local,
        remote_objects=remote,
        ignore_globs=["input_boolean:material_you_*"],
    )
    assert "input_boolean:material_you_primary_color" not in result.remote_objects
    assert "input_boolean:material_you_primary_color" not in result.local_objects
    assert result.findings == []  # no local declaration -> nothing to warn about


def test_ignored_key_never_reaches_compute_plan_as_delete() -> None:
    # THE safety test: an ignored object that exists remotely but was never
    # declared locally must not be planned for deletion (or any action) even
    # though the manifest already "knows" about it from a prior sync (the
    # shape compute_plan would otherwise turn into `delete`).
    from hassle.sync.plan import compute_plan

    manifest = Manifest(
        synced_at="2026-01-01T00:00:00Z",
        ha_version="2026.7.0",
        objects={
            "input_boolean:material_you_primary_color": ManifestEntry(
                source="helpers/misc.py",
                compiled_hash="sha256:deadbeef",
            )
        },
    )
    remote = {"input_boolean:material_you_primary_color": ("input_boolean", _HELPER_CFG)}
    filtered = apply_ignore_globs(
        local_objects={},
        remote_objects=remote,
        ignore_globs=["input_boolean:material_you_*"],
    )
    plan = compute_plan(
        manifest=manifest,
        local_objects=filtered.local_objects,
        remote_objects=filtered.remote_objects,
    )
    assert plan.entry_for("input_boolean:material_you_primary_color") is None


def test_locally_declared_ignored_object_excluded_and_warned() -> None:
    local = {"input_boolean:material_you_primary_color": ("input_boolean", _HELPER_CFG)}
    remote = {}
    result = apply_ignore_globs(
        local_objects=local, remote_objects=remote, ignore_globs=["input_boolean:material_you_*"]
    )
    assert "input_boolean:material_you_primary_color" not in result.local_objects
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.code == "declared-but-ignored"
    assert finding.severity == "warning"
    assert "input_boolean:material_you_primary_color" in finding.message
    assert "ignore" in finding.fix.lower()


def test_non_matching_objects_are_untouched() -> None:
    local = {"automation:a": ("automation", _AUTOMATION_CFG)}
    remote = {"automation:a": ("automation", _AUTOMATION_CFG)}
    result = apply_ignore_globs(
        local_objects=local, remote_objects=remote, ignore_globs=["input_boolean:material_you_*"]
    )
    assert result.local_objects == local
    assert result.remote_objects == remote
    assert result.findings == []


def test_no_globs_is_a_no_op() -> None:
    local = {"automation:a": ("automation", _AUTOMATION_CFG)}
    remote = {"automation:a": ("automation", _AUTOMATION_CFG)}
    result = apply_ignore_globs(local_objects=local, remote_objects=remote, ignore_globs=[])
    assert result.local_objects == local
    assert result.remote_objects == remote
    assert result.findings == []


def test_both_local_and_remote_present_and_ignored_are_both_excluded() -> None:
    local = {"input_boolean:material_you_x": ("input_boolean", _HELPER_CFG)}
    remote = {"input_boolean:material_you_x": ("input_boolean", _HELPER_CFG)}
    result = apply_ignore_globs(
        local_objects=local, remote_objects=remote, ignore_globs=["input_boolean:material_you_*"]
    )
    assert result.local_objects == {}
    assert result.remote_objects == {}
    # It's declared locally (matches), so still warned about.
    assert len(result.findings) == 1


# -- manifest migration ------------------------------------------------------


def test_migrate_manifest_drops_newly_ignored_entries_with_notice() -> None:
    manifest = Manifest(
        synced_at="2026-01-01T00:00:00Z",
        ha_version="2026.7.0",
        objects={
            "input_boolean:material_you_primary_color": ManifestEntry(
                source="helpers/misc.py", compiled_hash="sha256:aaa"
            ),
            "automation:a": ManifestEntry(source="automations/misc.py", compiled_hash="sha256:bbb"),
        },
    )
    result = migrate_manifest_for_ignores(manifest, ignore_globs=["input_boolean:material_you_*"])
    assert "input_boolean:material_you_primary_color" not in result.manifest.objects
    assert "automation:a" in result.manifest.objects
    assert result.dropped_keys == ["input_boolean:material_you_primary_color"]


def test_migrate_manifest_no_matching_globs_is_unchanged() -> None:
    manifest = Manifest(
        synced_at="2026-01-01T00:00:00Z",
        ha_version="2026.7.0",
        objects={"automation:a": ManifestEntry(source="automations/misc.py", compiled_hash="x")},
    )
    result = migrate_manifest_for_ignores(manifest, ignore_globs=["input_boolean:material_you_*"])
    assert result.manifest.objects == manifest.objects
    assert result.dropped_keys == []


def test_migrate_manifest_empty_globs_is_unchanged() -> None:
    manifest = Manifest(
        synced_at="2026-01-01T00:00:00Z",
        ha_version="2026.7.0",
        objects={"automation:a": ManifestEntry(source="automations/misc.py", compiled_hash="x")},
    )
    result = migrate_manifest_for_ignores(manifest, ignore_globs=[])
    assert result.manifest.objects == manifest.objects
    assert result.dropped_keys == []
