"""Regression: `hassle pull` REWROTE an existing `misc.py` to contain ONLY
the newly-adopted objects, silently dropping every pre-existing
uncategorized object in that file while the manifest kept tracking them --
so the very next `hassle plan` proposed a DELETE for each dropped object
against live HA (no local or UI edit may ever be silently lost).

Root cause: `apply_pull_with_decompiler` batches every ADOPT destined for one
file into a single decompiled module and writes it via
`source_writer.write_whole_file` -- correct for a brand-new destination file,
a silent clobber for an ALREADY-EXISTING one (the shared uncategorized
`misc.py` is exactly the file new UI objects keep adopting into forever).

Contract under test: after a pull that adopts new objects into an existing
file, every previously present object must still compile out of the bundle,
and `hassle plan` must propose zero deletes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle.compiler import compile_bundle

PRE_EXISTING_AUTOMATION_ID = "1769914409190"  # "Everything Off"


def _commit_all(bundle: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=bundle, check=True, capture_output=True
    )


def _seed_pre_existing_objects(backend) -> list[str]:
    """Seed uncategorized automations, a script, and a storage helper -- all
    of which place into the shared root-level `misc.py`. Returns their
    object keys."""
    backend.create(
        "automation",
        {
            "id": PRE_EXISTING_AUTOMATION_ID,
            "alias": "Everything Off",
            "triggers": [{"trigger": "state", "entity_id": "input_boolean.leaving", "to": "on"}],
            "conditions": [],
            "actions": [{"action": "light.turn_off", "target": {"entity_id": "light.all"}}],
            "mode": "single",
        },
    )
    backend.create(
        "automation",
        {
            "id": "1769914409191",
            "alias": "Morning Wakeup",
            "triggers": [{"trigger": "time", "at": "07:00:00"}],
            "conditions": [],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.bedroom"}}],
            "mode": "single",
        },
    )
    backend.create(
        "script",
        {
            "alias": "Goodnight routine",
            "sequence": [{"action": "light.turn_off", "target": {"entity_id": "light.all"}}],
        },
    )
    backend.create("input_boolean", {"id": "guest_mode_flag", "name": "Guest mode flag"})
    return [
        f"automation:{PRE_EXISTING_AUTOMATION_ID}",
        "automation:1769914409191",
        "script:goodnight_routine",
        "input_boolean:guest_mode_flag",
    ]


def test_pull_adopt_into_existing_misc_preserves_prior_objects(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """The end-to-end field repro: pull #1 adopts a set of uncategorized
    objects into a fresh `misc.py`; new UI-created objects appear remotely;
    pull #2 adopts them into that now-EXISTING `misc.py`. Every pre-existing
    object must survive, and `hassle plan` must propose no deletes."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    pre_existing_keys = _seed_pre_existing_objects(backend)

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    misc = git_repo / "misc.py"
    assert misc.is_file(), sorted(p.name for p in git_repo.iterdir())
    compiled_keys = set(compile_bundle(git_repo).objects)
    for key in pre_existing_keys:
        assert key in compiled_keys, sorted(compiled_keys)
    _commit_all(git_repo, "first pull")

    # New UI-created, uncategorized objects appear remotely between pulls --
    # their placement is the SAME shared `misc.py`, which now already exists.
    backend.create("input_boolean", {"id": "vacation_mode", "name": "Vacation mode"})
    backend.create(
        "automation",
        {
            "id": "1769914409999",
            "alias": "New UI Automation",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door", "to": "on"}],
            "conditions": [],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}],
            "mode": "single",
        },
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # THE regression assertion: everything previously in misc.py still
    # compiles out of the bundle, alongside the newly adopted objects.
    compiled_keys = set(compile_bundle(git_repo).objects)
    for key in pre_existing_keys:
        assert key in compiled_keys, sorted(compiled_keys)
    assert "input_boolean:vacation_mode" in compiled_keys, sorted(compiled_keys)
    assert "automation:1769914409999" in compiled_keys, sorted(compiled_keys)

    # And the very next plan proposes ZERO deletes (the bug's blast radius
    # was 13 DELETEs against live HA). The one `create` for the bundle
    # fixture's own hallway.py automation (local-only, never pushed to the
    # FakeBackend) is expected and unrelated -- the contract here is that no
    # pulled-then-dropped object shows up as a DELETE.
    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "delete" not in result.output, result.output
    action_lines = [line for line in result.output.splitlines() if line.strip()]
    assert action_lines == ["                  create  automation:hall_light_on_motion"], (
        result.output
    )


def test_apply_pull_adopt_splices_into_existing_file(tmp_path: Path, monkeypatch) -> None:
    """Unit-level: `apply_pull_with_decompiler` with the real
    `SplicingSourceWriter` must MERGE an ADOPT batch into an existing
    destination file, preserving every statement already there (including a
    hand-written comment), never overwrite it whole."""
    from hassle.sync.models import Plan, PlanAction, PlanEntry
    from hassle.sync.pull_apply import apply_pull_with_decompiler
    from hassle.sync.source_writer import SplicingSourceWriter

    monkeypatch.chdir(tmp_path)
    existing_source = """from hassle import automation, service, state, when

# hand-written note: keep this automation last

@automation(id="everything_off", alias="Everything Off")
def everything_off():
    when(state("input_boolean.leaving").to("on"))
    service("light.turn_off", target={"entity_id": "light.all"})
"""
    (tmp_path / "misc.py").write_text(existing_source, encoding="utf-8")

    def adopt_entry(ident: str) -> PlanEntry:
        return PlanEntry(
            object_key=f"automation:{ident}",
            kind="automation",
            action=PlanAction.ADOPT,
            base=None,
            local=None,
            remote={
                "id": ident,
                "alias": f"Adopted {ident}",
                "triggers": [],
                "conditions": [],
                "actions": [],
                "mode": "single",
            },
            remote_hash_at_plan=None,
            source_path="misc.py",
            conflict=None,
        )

    writer = SplicingSourceWriter(updated_on="2026-07-15")
    apply_pull_with_decompiler(
        Plan(entries=[adopt_entry("ui_new_1"), adopt_entry("ui_new_2")]), writer
    )

    merged = (tmp_path / "misc.py").read_text(encoding="utf-8")
    assert 'id="everything_off"' in merged, merged
    assert "hand-written note: keep this automation last" in merged, merged
    assert "ui_new_1" in merged and "ui_new_2" in merged, merged

    compiled_keys = set(compile_bundle(tmp_path).objects)
    assert {
        "automation:everything_off",
        "automation:ui_new_1",
        "automation:ui_new_2",
    } <= compiled_keys, sorted(compiled_keys)
