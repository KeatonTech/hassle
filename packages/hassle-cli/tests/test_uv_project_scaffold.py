"""MILESTONES M17: `hassle init`/`hassle pull` scaffold `pyproject.toml` at
the bundle root (bundle-as-uv-project), with a `[tool.uv.sources]` local-path
entry when a toolchain source checkout is resolvable. See
`hassle_cli.uv_project` module docstring for the full resolution-order
semantics and `MILESTONES.md`'s M17 section for the binding test list.
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli.init_cmd import init_bundle
from hassle_cli.uv_project import (
    NO_TOOLCHAIN_NOTE,
    resolve_toolchain_path,
    scaffold_pyproject,
)

# ---------------------------------------------------------------------------
# 1. init scaffolds pyproject with sources when toolchain resolvable
# ---------------------------------------------------------------------------


def test_scaffold_writes_pyproject_with_sources_when_toolchain_resolvable(tmp_path: Path) -> None:
    root = tmp_path / "my-house"
    root.mkdir()
    toolchain_root = tmp_path / "toolchain-checkout"

    result = scaffold_pyproject(root, toolchain_path=str(toolchain_root))

    assert result.wrote is True
    assert result.note is None
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "my_house"' in text  # slugify("my-house") -> "my_house"
    assert 'dependencies = ["hassle-cli"]' in text
    assert "[tool.uv.sources]" in text
    expected_path = (toolchain_root / "packages" / "hassle-cli").as_posix()
    assert f'path = "{expected_path}"' in text
    assert "editable = true" in text


def test_scaffold_project_name_is_slugified_bundle_dir_name(tmp_path: Path) -> None:
    root = tmp_path / "My Cool House!!"
    root.mkdir()

    scaffold_pyproject(root, toolchain_path=str(tmp_path / "toolchain"))

    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "my_cool_house"' in text


def test_scaffold_content_has_required_fields(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()

    scaffold_pyproject(root)

    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.0.0"' in text
    assert 'requires-python = ">=3.12"' in text


def test_init_bundle_scaffolds_pyproject(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    assert (tmp_path / "pyproject.toml").is_file()


def test_auto_detect_resolves_this_repo_as_a_toolchain_checkout() -> None:
    # Real, incidental positive case (M17 test list item 1's second half):
    # this very test suite runs against an editable install of `hassle-cli`
    # from THIS repo's own checkout, so auto-detection (no configured_path)
    # must find it without any faking.
    import hassle_cli

    resolved = resolve_toolchain_path(configured_path=None, hassle_cli_file=hassle_cli.__file__)
    assert resolved is not None
    assert (resolved / "packages" / "hassle-cli" / "pyproject.toml").is_file()


# ---------------------------------------------------------------------------
# 2. existing pyproject NEVER modified by init or pull (even malformed TOML)
# ---------------------------------------------------------------------------


def test_scaffold_never_touches_existing_pyproject(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    existing = "this is not [ valid toml at all { { {"
    (root / "pyproject.toml").write_text(existing, encoding="utf-8")

    result = scaffold_pyproject(root, toolchain_path=str(tmp_path / "toolchain"))

    assert result.wrote is False
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == existing


def test_init_bundle_never_touches_existing_pyproject(tmp_path: Path) -> None:
    existing = "[project]\nname = 'already-here'\n"
    (tmp_path / "pyproject.toml").write_text(existing, encoding="utf-8")

    init_bundle(tmp_path)

    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == existing


def test_pull_never_touches_existing_pyproject(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    existing = "garbage { not valid toml"
    (bundle_dir / "pyproject.toml").write_text(existing, encoding="utf-8")
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)

    result = cli(["pull"], cwd=bundle_dir)

    assert result.exit_code == 0, result.output
    assert (bundle_dir / "pyproject.toml").read_text(encoding="utf-8") == existing


def test_pull_scaffolds_pyproject_when_missing(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    assert not (bundle_dir / "pyproject.toml").exists()
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)

    result = cli(["pull"], cwd=bundle_dir)

    assert result.exit_code == 0, result.output
    assert (bundle_dir / "pyproject.toml").is_file()


# ---------------------------------------------------------------------------
# 3. toolchain_path config beats auto-detect; neither -> bare dependency + note
# ---------------------------------------------------------------------------


def test_configured_toolchain_path_wins_over_auto_detect(tmp_path: Path) -> None:
    configured = tmp_path / "configured-checkout"
    # A fake auto-detect target that WOULD resolve, to prove config wins even
    # when auto-detection also has an answer.
    auto = tmp_path / "auto-checkout" / "packages" / "hassle-cli"
    auto.mkdir(parents=True)
    (auto / "pyproject.toml").write_text('[project]\nname = "hassle-cli"\n', encoding="utf-8")

    resolved = resolve_toolchain_path(
        configured_path=str(configured), hassle_cli_file=str(auto / "src" / "hassle_cli" / "x.py")
    )

    assert resolved == configured


def test_neither_configured_nor_auto_detected_scaffolds_bare_dependency(tmp_path: Path) -> None:
    # A fake `hassle_cli.__file__` deep in some directory tree with no
    # `hassle-cli`-named pyproject.toml anywhere above it -- confirms
    # resolution itself returns None in this shape.
    fake_file = tmp_path / "nowhere" / "src" / "hassle_cli" / "cli.py"
    fake_file.parent.mkdir(parents=True)
    resolved = resolve_toolchain_path(configured_path=None, hassle_cli_file=str(fake_file))
    assert resolved is None

    # This process's REAL auto-detection would actually find THIS repo's own
    # checkout (see test_auto_detect_resolves_this_repo_as_a_toolchain_checkout),
    # so the "truly neither resolves" scaffold outcome is driven through
    # suppress_sources instead -- the same code path `hassle-dev
    # acceptance-bundle` uses for its determinism requirement, and the one a
    # published-from-PyPI `hassle-cli` (no checkout to find at all) would take.
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    result = scaffold_pyproject(bundle, toolchain_path=None, suppress_sources=True)

    assert result.wrote is True
    assert result.note == NO_TOOLCHAIN_NOTE
    text = (bundle / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.uv.sources]" not in text
    assert 'dependencies = ["hassle-cli"]' in text


def test_auto_detect_returns_none_when_no_hassle_cli_pyproject_found(tmp_path: Path) -> None:
    fake_file = tmp_path / "nowhere" / "src" / "hassle_cli" / "cli.py"
    fake_file.parent.mkdir(parents=True)

    resolved = resolve_toolchain_path(configured_path=None, hassle_cli_file=str(fake_file))

    assert resolved is None


def test_init_prints_note_when_no_toolchain_and_sources_suppressed(tmp_path: Path) -> None:
    # scaffold_pyproject itself is unit-tested above for the note; this
    # confirms the dataclass result carries exactly the shared constant so
    # cli.py's init/pull bodies can print it verbatim.
    root = tmp_path / "b"
    root.mkdir()
    result = scaffold_pyproject(root, toolchain_path=None, suppress_sources=True)
    assert result.note == NO_TOOLCHAIN_NOTE
