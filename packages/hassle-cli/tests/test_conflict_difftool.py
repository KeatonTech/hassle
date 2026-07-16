"""Owner feature request from field use (`ux/conflict-difftool`).

The interactive `hassle push` conflict prompt renders remote/local as an
inline unified diff of decompiled DSL -- unreadable for large objects (the
HVAC status template sensors are single 8KB Jinja strings). Two fixes, both
pinned here:

1. A `[d]iff` choice alongside keep [l]ocal / keep [r]emote / [a]bort that
   writes the decompiled remote and local forms to two temp files and opens
   them in an external diff tool, then returns to the prompt. Tool
   resolution order: `$HASSLE_DIFFTOOL`, then `git difftool --no-index`
   (when a git `diff.tool` is configured), then `diff -u | $PAGER`.
2. The inline diff display-wraps very long single-string values at Jinja
   tag boundaries (`{% %}`, falling back to `{{ }}`), so the inline view
   shows WHICH PART of an 8KB template changed. Display only: decompiled
   sources, temp files, and everything round-trip-relevant (I3) stay
   byte-exact.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"


def _check_snapshot(name: str, actual: str) -> None:
    actual = actual.rstrip("\n")
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


@pytest.fixture
def interactive(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("hassle_cli.cli._interactive", lambda: True, raising=False)


@pytest.fixture
def no_ambient_git_config(monkeypatch: pytest.MonkeyPatch):
    """A developer laptop (or CI image) may carry a global `diff.tool`;
    resolution tests must not depend on it."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")


# ---------------------------------------------------------------------------
# Tool resolution order: $HASSLE_DIFFTOOL, git difftool config, pager fallback
# ---------------------------------------------------------------------------


def test_hassle_difftool_env_wins_and_is_shlex_split() -> None:
    from hassle_cli.difftool import resolve_difftool

    argv = resolve_difftool({"HASSLE_DIFFTOOL": "code --diff --wait"}, None)
    assert argv == ["code", "--diff", "--wait"]


def test_git_difftool_used_when_diff_tool_configured(git_repo: Path, no_ambient_git_config) -> None:
    from hassle_cli.difftool import resolve_difftool

    subprocess.run(
        ["git", "config", "diff.tool", "opendiff"], cwd=git_repo, check=True, capture_output=True
    )
    assert resolve_difftool({}, git_repo) == ["git", "difftool", "--no-index", "-y"]


def test_no_configured_tool_resolves_to_pager_fallback(
    tmp_path: Path, no_ambient_git_config
) -> None:
    from hassle_cli.difftool import resolve_difftool

    # Not a git repo, no $HASSLE_DIFFTOOL: resolution yields the
    # `diff -u | $PAGER` fallback (signalled as None).
    assert resolve_difftool({}, tmp_path) is None


def test_git_repo_without_diff_tool_config_still_falls_back(
    git_repo: Path, no_ambient_git_config
) -> None:
    from hassle_cli.difftool import resolve_difftool

    assert resolve_difftool({}, git_repo) is None


def test_fallback_pipes_unified_diff_into_pager(tmp_path: Path, no_ambient_git_config) -> None:
    from hassle_cli.difftool import run_external_diff

    remote = tmp_path / "remote.py"
    local = tmp_path / "local.py"
    remote.write_text("alias = 'remote side'\nshared = 1\n", encoding="utf-8")
    local.write_text("alias = 'local side'\nshared = 1\n", encoding="utf-8")
    capture = tmp_path / "pager-capture.txt"

    error = run_external_diff(remote, local, env={"PAGER": f"cat > {capture}"}, cwd=tmp_path)

    assert error is None
    paged = capture.read_text(encoding="utf-8")
    assert "-alias = 'remote side'" in paged
    assert "+alias = 'local side'" in paged


def test_launch_failure_returns_r6_error_message(tmp_path: Path) -> None:
    """R6: what / where / fix, one paragraph, snapshot-tested. A missing tool
    must produce a message, never a traceback."""
    from hassle_cli.difftool import run_external_diff

    remote = tmp_path / "remote.py"
    local = tmp_path / "local.py"
    remote.write_text("a\n", encoding="utf-8")
    local.write_text("b\n", encoding="utf-8")

    error = run_external_diff(
        remote,
        local,
        env={"HASSLE_DIFFTOOL": "hassle-no-such-difftool-xyz"},
        cwd=tmp_path,
    )

    assert error is not None
    assert "Fix:" in error
    _check_snapshot("difftool_launch_failure", error)


# ---------------------------------------------------------------------------
# The interactive [d]iff choice
# ---------------------------------------------------------------------------


def _make_conflict(git_repo: Path, cli, backend, token, toml_writer) -> None:
    """Push once, then diverge both sides of the same automation (same
    scenario as test_cli_interactive.py's conflict tests)."""
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


def test_conflict_prompt_offers_diff_and_returns_to_prompt(
    interactive, git_repo: Path, cli, fake_backend, toml_writer, tmp_path: Path
) -> None:
    """[d] writes both decompiled sides to temp files, hands them to
    $HASSLE_DIFFTOOL (remote first, local second -- same order as the inline
    diff's fromfile/tofile), and then re-prompts for a real resolution."""
    from hassle_cli.diffing import decompile_dsl

    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)
    identity = next(iter(backend.list_remote("automation")))
    remote_before_push = dict(backend.list_remote("automation")[identity])

    record_dir = tmp_path / "recorded"
    record_dir.mkdir()
    recorder = tmp_path / "record-difftool.sh"
    recorder.write_text(
        f'#!/bin/sh\ncp "$1" "{record_dir}/remote.py"\ncp "$2" "{record_dir}/local.py"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o755)

    result = cli(
        ["push"],
        cwd=git_repo,
        env={"HASSLE_DIFFTOOL": str(recorder)},
        input="d\nl\n\n",
    )
    assert result.exit_code == 0, result.output

    # The prompt advertises the new choice and was shown AGAIN after the diff.
    assert "[d]iff" in result.output
    assert result.output.count("keep [l]ocal") == 2

    # The temp files carried the byte-exact decompiled DSL of each side (no
    # display wrapping): remote is HA's renamed version...
    recorded_remote = (record_dir / "remote.py").read_text(encoding="utf-8")
    assert "Renamed on the HA side" in recorded_remote
    # ...and local is the bundle's edit.
    recorded_local = (record_dir / "local.py").read_text(encoding="utf-8")
    assert "light.hallway_2" in recorded_local

    # After returning to the prompt, [l] resolved and pushed the local side.
    stored = str(backend.list_remote("automation")[identity])
    assert "light.hallway_2" in stored

    # Byte-exactness of the remote side, pinned against the decompiler itself
    # (captured BEFORE the push -- [l] replaced HA's version afterwards).
    assert recorded_remote == decompile_dsl(
        f"automation:{identity}", "automation", remote_before_push
    )


def test_diff_tool_failure_prints_error_and_returns_to_prompt(
    interactive, git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """A broken $HASSLE_DIFFTOOL must not eat the resolution flow: the R6
    message prints, the prompt comes back, and [r] still resolves."""
    backend, token = fake_backend
    _make_conflict(git_repo, cli, backend, token, toml_writer)

    result = cli(
        ["push"],
        cwd=git_repo,
        env={"HASSLE_DIFFTOOL": "hassle-no-such-difftool-xyz"},
        input="d\nr\n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Fix:" in result.output
    assert result.output.count("keep [l]ocal") == 2
    identity = next(iter(backend.list_remote("automation")))
    stored = str(backend.list_remote("automation")[identity])
    assert "Renamed on the HA side" in stored  # remote kept


# ---------------------------------------------------------------------------
# Inline diff: display-only wrapping of long single-string Jinja values
# ---------------------------------------------------------------------------

_JINJA_BLOCKS = [
    "{% set supply = states('sensor.hvac_supply_temp') | float(0) %}",
    "{% set return_t = states('sensor.hvac_return_temp') | float(0) %}",
    "{% set delta = supply - return_t %}",
    "{% if delta > 4 %}heating",
    "{% elif delta < -4 %}cooling",
    "{% else %}idle",
    "{% endif %}",
]


def _template_sensor(state: str) -> dict[str, object]:
    return {"name": "HVAC Status", "state": state}


def test_inline_diff_wraps_long_jinja_at_block_boundaries() -> None:
    """An 8KB-single-string-style conflict: the inline diff must show WHICH
    `{% %}` segment changed, as its own -/+ pair, with unchanged segments as
    plain context lines -- not one inscrutable full-string -/+ pair."""
    from hassle_cli.diffing import dsl_diff

    local = _template_sensor("".join(_JINJA_BLOCKS))
    remote_blocks = list(_JINJA_BLOCKS)
    remote_blocks[3] = "{% if delta > 6 %}heating"  # a UI-side threshold tweak
    remote = _template_sensor("".join(remote_blocks))

    diff = dsl_diff("template_sensor:hvac_status", "template_sensor", local, remote)
    lines = diff.splitlines()

    removed = [line for line in lines if line.startswith("-") and not line.startswith("---")]
    added = [line for line in lines if line.startswith("+") and not line.startswith("+++")]
    assert any("{% if delta > 6 %}" in line for line in removed), diff  # remote side
    assert any("{% if delta > 4 %}" in line for line in added), diff  # local side
    # The changed -/+ lines carry ONLY the changed segment...
    assert all("endif" not in line for line in removed + added), diff
    assert all("{% set supply" not in line for line in removed + added), diff
    # ...and an unchanged segment shows up as a context line.
    assert any(line.startswith(" ") and "{% set supply" in line for line in lines), diff


def test_inline_diff_wraps_expression_only_templates_at_expr_boundaries() -> None:
    """A long template with no `{% %}` blocks still wraps -- at `{{ }}`
    expression boundaries instead."""
    from hassle_cli.diffing import dsl_diff

    exprs = [f"zone {i}: {{{{ states('sensor.hvac_zone_{i}_temp') }}}} " for i in range(6)]
    local = _template_sensor("".join(exprs))
    remote_exprs = list(exprs)
    remote_exprs[4] = "zone 4: {{ states('sensor.hvac_zone_4_temp_new') }} "
    remote = _template_sensor("".join(remote_exprs))

    diff = dsl_diff("template_sensor:hvac_status", "template_sensor", local, remote)
    changed = [
        line
        for line in diff.splitlines()
        if line.startswith(("-", "+")) and not line.startswith(("---", "+++"))
    ]
    assert changed, diff
    assert all("hvac_zone_4" in line for line in changed), diff
    assert all("zone 0" not in line for line in changed), diff


def test_short_and_non_jinja_lines_are_never_wrapped() -> None:
    """Wrapping targets long Jinja strings ONLY: a long decompiled
    `@automation(...)` line with no Jinja in it stays a single diff line
    (pinned separately by the conflict_3way_diff snapshot, belt-and-
    suspenders here at the dsl_diff layer)."""
    from hassle_cli.diffing import dsl_diff

    local = {
        "id": "hall",
        "alias": "Hallway light on motion with a deliberately long alias for line length",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [],
    }
    remote = {**local, "alias": "Renamed on the HA side"}

    diff = dsl_diff("automation:hall", "automation", local, remote)
    decorator_lines = [line for line in diff.splitlines() if "@automation(" in line]
    assert decorator_lines, diff
    assert all("triggers=[state(" in line for line in decorator_lines), diff


def test_decompiled_sources_stay_unwrapped_for_round_trip_and_temp_files() -> None:
    """The wrap is display-only (I3 adjacency: nothing that feeds compile/
    decompile round trips may change): `decompile_dsl` keeps the whole Jinja
    string on its original single line."""
    from hassle_cli.diffing import decompile_dsl

    state = "".join(_JINJA_BLOCKS)
    src = decompile_dsl("template_sensor:hvac_status", "template_sensor", _template_sensor(state))
    assert state in src  # intact, unbroken, on one line
