"""Owner work item (task #39): interactive CLI.

At a real terminal, `push` prompts instead of demanding flags: deletions get
a render-plan-then-confirm (default NO), ordinary plans a summary confirm
(default YES), and each unresolved conflict a local/remote/abort choice.
Long phases show progress: the apply loop prints one `[i/N]` line per
applied entry. Non-TTY behavior is byte-compatible with before (the
existing test_push_confirm.py suite pins it); interactivity is detected via
`hassle_cli.cli._interactive`, monkeypatched here.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def interactive(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("hassle_cli.cli._interactive", lambda: True, raising=False)


def test_delete_prompt_confirms_and_applies(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    (git_repo / "hallway.py").unlink()

    result = cli(["push"], cwd=git_repo, input="y\n")
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" not in backend.list_remote("automation")


def test_delete_prompt_defaults_to_abort(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    (git_repo / "hallway.py").unlink()

    result = cli(["push"], cwd=git_repo, input="\n")  # bare Enter = the default
    assert result.exit_code != 0
    assert "hall_light_on_motion" in backend.list_remote("automation")  # untouched
    assert "nothing applied" in result.output.lower()


def test_ordinary_plan_prompt_defaults_to_apply(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["push"], cwd=git_repo, input="\n")  # bare Enter accepts
    assert result.exit_code == 0, result.output
    assert "Apply?" in result.output  # the prompt actually happened
    assert "hall_light_on_motion" in backend.list_remote("automation")


def test_ordinary_plan_prompt_can_decline(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["push"], cwd=git_repo, input="n\n")
    assert result.exit_code != 0
    assert "hall_light_on_motion" not in backend.list_remote("automation")


def test_yes_flag_still_skips_all_prompts(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # No stdin available at all: --yes must not read from it.
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" in backend.list_remote("automation")


def _make_conflict(git_repo: Path, cli, backend, token, toml_writer) -> None:
    """Push once, then diverge both sides of the same automation."""
    toml_writer(git_repo, backend_token=token)
    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    identity = next(iter(backend.list_remote("automation")))
    remote = dict(backend.list_remote("automation")[identity])
    remote["alias"] = "Renamed on the HA side"
    backend.update("automation", identity, remote)
    src = (git_repo / "hallway.py").read_text(encoding="utf-8")
    (git_repo / "hallway.py").write_text(
        src.replace('"light.hallway"', '"light.hallway_2"'), encoding="utf-8"
    )


def test_conflict_prompt_accept_local(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)

    # "l" = push our version (then the ordinary apply confirm, default yes).
    result = cli(["push"], cwd=git_repo, input="l\n\n")
    assert result.exit_code == 0, result.output
    identity = next(iter(backend.list_remote("automation")))
    stored = str(backend.list_remote("automation")[identity])
    assert "light.hallway_2" in stored


def test_conflict_prompt_accept_remote(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)

    result = cli(["push"], cwd=git_repo, input="r\n\n")
    assert result.exit_code == 0, result.output
    identity = next(iter(backend.list_remote("automation")))
    stored = str(backend.list_remote("automation")[identity])
    assert "Renamed on the HA side" in stored  # remote kept


def test_accept_local_records_base_so_later_edit_replans_as_update(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """Field report (BrandtCamp bundle, 2026-07-14): after a keep-local
    resolution is pushed, the manifest base must equal the pushed read-back --
    a LATER local edit re-plans as a plain update, never a repeat conflict
    against the owner's own previous push."""
    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)
    assert cli(["push"], cwd=git_repo, input="l\n\n").exit_code == 0

    # NOTE: the replacement changes the file SIZE on purpose -- Python's
    # bytecode cache invalidates on (mtime, size), and this test writes twice
    # within the same second (a same-length edit would re-import stale
    # bytecode in-process; real CLI runs are separate processes).
    src = (git_repo / "hallway.py").read_text(encoding="utf-8")
    (git_repo / "hallway.py").write_text(
        src.replace('"light.hallway_2"', '"light.hallway_edited_again"'), encoding="utf-8"
    )
    plan = _build_plan(git_repo)
    actions = {e.object_key: e.action for e in plan.entries}
    assert actions.get("automation:hall_light_on_motion") is PlanAction.UPDATE, actions


def test_accept_remote_records_base_so_replan_is_refresh_not_conflict(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """Field report hypothesis (1), confirmed: an interactive [r] resolution
    recorded NOTHING -- `ManifestEntry.compiled_hash` kept the stale
    pre-conflict base, so the identical conflict re-surfaced on every
    subsequent plan forever (I6 damage: trains the owner to stop reading
    conflict prompts). A kept remote is a remote-side edit accepted as-is:
    the base must advance to the LOCAL side, so the next plan reads
    `refresh` (pull-side -- push never clobbers the kept remote) until
    `hassle pull` reconciles the bundle, after which everything is noop."""
    import subprocess

    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)
    assert cli(["push"], cwd=git_repo, input="r\n\n").exit_code == 0

    plan = _build_plan(git_repo)
    actions = {e.object_key: e.action for e in plan.entries}
    assert actions.get("automation:hall_light_on_motion") is PlanAction.REFRESH, actions

    # The loop closes through pull: the kept remote lands in the bundle and
    # the next plan has nothing left to do.
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "local state before pull"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    assert cli(["pull"], cwd=git_repo).exit_code == 0
    assert "Renamed on the HA side" in (git_repo / "hallway.py").read_text(encoding="utf-8")
    plan = _build_plan(git_repo)
    non_noop = {
        e.object_key: e.action.value for e in plan.entries if e.action is not PlanAction.NOOP
    }
    assert non_noop == {}, non_noop


def test_conflict_abort_keeps_conflict_pending(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """[a] resolves nothing, so the SAME conflict must re-surface on the next
    plan -- unlike [r], nothing may be recorded (I6: the divergence is still
    real and unresolved)."""
    from hassle.sync.models import PlanAction
    from hassle_cli.cli import _build_plan

    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)
    assert cli(["push"], cwd=git_repo, input="a\n").exit_code != 0

    plan = _build_plan(git_repo)
    actions = {e.object_key: e.action for e in plan.entries}
    assert actions.get("automation:hall_light_on_motion") is PlanAction.CONFLICT, actions


def test_conflict_prompt_abort(interactive, git_repo: Path, cli, fake_backend, toml_writer) -> None:
    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)

    result = cli(["push"], cwd=git_repo, input="a\n")
    assert result.exit_code != 0
    assert "aborted, nothing applied" in result.output.lower()  # the PROMPT path
    identity = next(iter(backend.list_remote("automation")))
    stored = str(backend.list_remote("automation")[identity])
    assert "Renamed on the HA side" in stored  # untouched


def test_apply_prints_per_entry_progress(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    """The hang report: every applied entry gets a visible [i/N] line (TTY or
    not -- progress is honest output, not decoration)."""
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "second.py").write_text(
        (git_repo / "hallway.py")
        .read_text(encoding="utf-8")
        .replace("hall_light_on_motion", "second_light_on_motion")
        .replace("hall_motion", "porch_motion"),
        encoding="utf-8",
    )
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "[1/2]" in result.output and "[2/2]" in result.output


def test_push_explains_adopt_rows(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    """Owner confusion (twice): adopt rows in a push plan look actionable but
    push ignores them entirely. The plan output must say what they are and
    that only pull (or deleting in the HA UI) does anything about them."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    backend.create("input_number", {"name": "Stray Duplicate", "min": 0, "max": 1})
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "not touched by push" in result.output
    assert "pull" in result.output
