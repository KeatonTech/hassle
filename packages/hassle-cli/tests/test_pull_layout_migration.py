"""MILESTONES M15 work item B, tests 5 + 7 -- end-to-end (`hassle pull`):
migrating an old-layout bundle to the new category-first, root-level layout,
reporting every move, bumping `bundle_format`, and leaving a NOOP plan +
byte-stable second pull behind.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle_cli.config import CURRENT_BUNDLE_FORMAT, load_config


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def test_pull_migrates_old_layout_preserving_user_content_and_deleting_empty_files(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)  # writes bundle_format = 1 (old-layout signal)

    # The `git_repo` fixture's own seed automation moves from root-level
    # `hallway.py` into the OLD `automations/` tree for this test, alongside
    # a user comment + a custom def that must survive migration (I6).
    (git_repo / "hallway.py").unlink()
    (git_repo / "automations").mkdir(exist_ok=True)
    (git_repo / "automations" / "hallway.py").write_text(
        '''
from hassle import automation, service, state, when

# Keep this note -- reminder to check the motion sensor battery.
def battery_reminder():
    """Not a Hassle object -- just a note-to-self helper."""
    return "check battery"


@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
''',
        encoding="utf-8",
    )
    # A second old-layout file with NOTHING but the managed object -- must be
    # deleted entirely once migrated out.
    (git_repo / "scripts").mkdir(exist_ok=True)
    (git_repo / "scripts" / "chores.py").write_text(
        """
from hassle import script, service

@script(id="take_out_trash", alias="Take out the trash")
def take_out_trash():
    service("switch.turn_on", target={"entity_id": "switch.porch_light"})
""",
        encoding="utf-8",
    )
    _commit_all(git_repo, "old-layout bundle")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "migrated" in result.output.lower()
    assert "hall_light_on_motion" in result.output
    assert "take_out_trash" in result.output
    assert "deleted" in result.output.lower()

    # The user's comment/custom def survive in the KEPT old file.
    kept = git_repo / "automations" / "hallway.py"
    assert kept.is_file()
    kept_text = kept.read_text(encoding="utf-8")
    assert "Keep this note -- reminder to check the motion sensor battery." in kept_text
    assert "def battery_reminder():" in kept_text
    assert "hall_light_on_motion" not in kept_text

    # The now-empty old script file is gone.
    assert not (git_repo / "scripts" / "chores.py").is_file()

    # Both managed objects landed in the new shared root-level misc.py
    # (neither had a UI category).
    misc = git_repo / "misc.py"
    assert misc.is_file()
    misc_text = misc.read_text(encoding="utf-8")
    assert "hall_light_on_motion" in misc_text
    assert "take_out_trash" in misc_text

    # bundle_format bumped.
    assert load_config(git_repo).bundle_format == CURRENT_BUNDLE_FORMAT

    # Compiles cleanly post-migration.
    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    assert "automation:hall_light_on_motion" in compiled.objects
    assert "script:take_out_trash" in compiled.objects


def test_plan_is_noop_after_migration(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    """MILESTONES M15: migration only moves source, never config -- the very
    next `hassle push --yes` (a create-if-needed apply) must not re-create or
    duplicate anything the bundle already pushed before migrating."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    (git_repo / "hallway.py").unlink()
    (git_repo / "automations").mkdir(exist_ok=True)
    (git_repo / "automations" / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    _commit_all(git_repo, "old-layout bundle")

    # First push, from the OLD layout, establishes the manifest baseline.
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "push")
    assert "hall_light_on_motion" in backend.list_remote("automation")

    # Migrate.
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "migrated" in result.output.lower()
    _commit_all(git_repo, "migrate layout")

    # The plan after migration is a NOOP for this object -- config unchanged,
    # only its source_path metadata moved.
    plan_result = cli(["plan"], cwd=git_repo)
    assert plan_result.exit_code == 0, plan_result.output
    assert "create" not in plan_result.output.lower()
    assert "update" not in plan_result.output.lower()
    assert "delete" not in plan_result.output.lower()


def test_second_pull_after_migration_is_byte_stable(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    (git_repo / "hallway.py").unlink()
    (git_repo / "automations").mkdir(exist_ok=True)
    (git_repo / "automations" / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    _commit_all(git_repo, "old-layout bundle")

    assert cli(["pull"], cwd=git_repo).exit_code == 0
    misc_after_first = (git_repo / "misc.py").read_text(encoding="utf-8")
    _commit_all(git_repo, "migrate layout")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "migrated" not in result.output.lower()  # nothing left to migrate
    misc_after_second = (git_repo / "misc.py").read_text(encoding="utf-8")
    assert misc_after_second == misc_after_first
