"""Rich output must have a plain-text capture mode for snapshot tests
(NO_COLOR/--plain); snapshots are the UX contract (R6 applies to error output).
"""

from __future__ import annotations

from pathlib import Path


def test_no_color_env_strips_ansi_codes(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["plan"], cwd=git_repo, env={"NO_COLOR": "1"})
    assert "\x1b[" not in result.output


def test_plain_flag_strips_ansi_codes(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["plan", "--plain"], cwd=git_repo, env={})
    assert "\x1b[" not in result.output


def test_render_module_exposes_plain_capture_helper() -> None:
    from hassle_cli.render import render_plain

    text = render_plain(lambda console: console.print("[red]hello[/red]"))
    assert text.strip() == "hello"
    assert "\x1b[" not in text
