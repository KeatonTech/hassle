"""`test_plan_labels_modernization_diffs`.

A legacy-form remote object (inner `platform:`/scalar `delay:`, or outer
singular `trigger:`/`action:` + `service:`) adopted then re-pushed produces a
ONE-TIME plan diff: Hassle compiles the modern (plural, `action:`) form, but
HA stores whatever it was given verbatim thereafter (docs/ha-api-notes.md
§17.1: HA does NOT rewrite inner `platform:` on storage). So after `adopt`,
the bundle's compiled (modern) form differs from the remote's still-legacy
form, purely as a schema/style difference -- not a behavior change. The plan
renderer must label this class of diff "modernization (one-time)" so users
aren't alarmed, and it must NOT be labeled as a conflict (there was no
concurrent edit).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle_dev.snapshots import check_snapshot

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def test_adopted_legacy_form_diff_labeled_modernization(
    git_repo: Path, cli, fake_backend, tmp_path: Path, toml_writer, output_normalizer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # Push+commit the pre-existing local automation first so it doesn't show
    # up as noise in this test's plan/snapshot output.
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "push hallway"], cwd=git_repo, check=True, capture_output=True
    )

    # Seed a remote automation in legacy singular form + `service:` (as if
    # hand-authored YAML or an old UI export), bypassing FakeBackend.create's
    # normalize_ha so it stays legacy exactly like real HA would preserve the
    # inner `platform:`/`service:` discriminators it doesn't rewrite (§17.1).
    backend._store["automation"]["legacy_guest_light"] = {
        "id": "legacy_guest_light",
        "alias": "Legacy Guest Light",
        "trigger": [{"platform": "state", "entity_id": "input_boolean.guest_mode", "to": "on"}],
        "condition": [],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        "mode": "single",
    }

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "legacy_guest_light" in result.output

    # Re-plan without touching anything: local (decompiled-then-recompiled
    # modern form) vs remote (still legacy) now differ structurally only.
    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "modernization (one-time)" in result.output.lower() or "modernization" in result.output
    assert "conflict" not in result.output.lower().split("legacy_guest_light")[0][-200:]
    _check_snapshot("modernization_one_time_diff", output_normalizer(result.output, tmp_path))
