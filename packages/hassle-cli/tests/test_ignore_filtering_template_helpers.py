"""MILESTONES M10 test 5 (part 2/2) — ignore-glob interplay for the
config-entry template-helper domain.

`hassle_cli.ignore_filter` is a pure string-glob-on-object-key module (see
`test_ignore_filtering.py`'s module docstring); a `"template_number:*"` glob
works identically to a storage-helper glob with zero code changes -- these
tests are the M10 proof of that, mirroring the storage-helper cases exactly.
"""

from __future__ import annotations

from hassle.sync.models import Manifest, ManifestEntry
from hassle.sync.plan import compute_plan
from hassle_cli.ignore_filter import apply_ignore_globs, migrate_manifest_for_ignores

_TEMPLATE_CFG = {"unique_id": "active_hvac_zones", "name": "Zones", "state": "{{ 1 }}"}


def test_ignored_template_helper_key_produces_no_plan_entry() -> None:
    manifest = Manifest(
        synced_at="2026-01-01T00:00:00Z",
        ha_version="2026.7.0",
        objects={
            "template_number:active_hvac_zones": ManifestEntry(
                source="helpers/misc.py", compiled_hash="sha256:deadbeef"
            )
        },
    )
    remote = {"template_number:active_hvac_zones": ("template_number", _TEMPLATE_CFG)}
    ignore_globs = ["template_number:active_hvac_zones"]
    migrated = migrate_manifest_for_ignores(manifest, ignore_globs=ignore_globs)
    filtered = apply_ignore_globs(
        local_objects={}, remote_objects=remote, ignore_globs=ignore_globs
    )
    plan = compute_plan(
        manifest=migrated.manifest,
        local_objects=filtered.local_objects,
        remote_objects=filtered.remote_objects,
    )
    assert plan.entry_for("template_number:active_hvac_zones") is None


def test_locally_declared_ignored_template_helper_is_warned() -> None:
    local = {"template_number:active_hvac_zones": ("template_number", _TEMPLATE_CFG)}
    result = apply_ignore_globs(
        local_objects=local, remote_objects={}, ignore_globs=["template_number:*"]
    )
    assert "template_number:active_hvac_zones" not in result.local_objects
    assert len(result.findings) == 1
    assert result.findings[0].code == "declared-but-ignored"


def test_ignored_template_helper_never_plans_delete() -> None:
    # THE safety property (mirrors test_ignore_filtering.py): an ignored
    # template helper present remotely but absent locally must never plan a
    # delete, no matter what a bare compute_plan would otherwise say.
    manifest = Manifest(
        synced_at="t",
        ha_version="v",
        objects={
            "template_number:active_hvac_zones": ManifestEntry(
                source="helpers/misc.py", compiled_hash="sha256:deadbeef"
            )
        },
    )
    remote = {"template_number:active_hvac_zones": ("template_number", _TEMPLATE_CFG)}
    ignore_globs = ["template_number:*"]
    filtered = apply_ignore_globs(
        local_objects={}, remote_objects=remote, ignore_globs=ignore_globs
    )
    migrated = migrate_manifest_for_ignores(manifest, ignore_globs=ignore_globs)
    plan = compute_plan(
        manifest=migrated.manifest,
        local_objects=filtered.local_objects,
        remote_objects=filtered.remote_objects,
    )
    assert plan.entry_for("template_number:active_hvac_zones") is None
