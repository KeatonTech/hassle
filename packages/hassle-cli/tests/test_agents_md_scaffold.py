"""`hassle init` (and `hassle pull`, when it creates the scaffold dirs) writes
`AGENTS.md` (generated, DESIGN §12) plus `docs/DSL.md`/`docs/COOKBOOK.md`
(the bundle's own copy of the reference docs -- MILESTONES M9 deliverable
1). All three are idempotent to re-run but AGENTS.md/docs/*.md are
REGENERATED every time (unlike lib/README.md/tests/README.md, which are
user territory) since they are wholly generated content the user never
hand-edits (the module docstring says so) -- mirrors `.vscode/settings.json`
always being rewritten, not `lib/README.md`'s "only if missing" rule.
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli.init_cmd import init_bundle


def test_init_writes_agents_md(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.is_file()
    content = agents_md.read_text(encoding="utf-8")
    assert "hassle validate" in content
    assert "hassle test" in content
    assert "hassle plan" in content


def test_init_writes_docs_dsl_and_cookbook(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    assert (tmp_path / "docs" / "DSL.md").is_file()
    assert (tmp_path / "docs" / "COOKBOOK.md").is_file()


def test_init_agents_md_uses_bundle_directory_name(tmp_path: Path) -> None:
    bundle = tmp_path / "chez-keaton"
    bundle.mkdir()
    init_bundle(bundle)
    content = (bundle / "AGENTS.md").read_text(encoding="utf-8")
    assert "chez-keaton" in content


def test_init_regenerates_agents_md_on_rerun(tmp_path: Path) -> None:
    """Unlike lib/README.md, AGENTS.md is machine-owned and always refreshed
    -- re-running init after a hand-edit restores the generated content
    (the file's own header says "do not hand-edit")."""
    init_bundle(tmp_path)
    (tmp_path / "AGENTS.md").write_text("stale hand-edit\n", encoding="utf-8")

    init_bundle(tmp_path)

    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "stale hand-edit" not in content
    assert "hassle validate" in content


def test_pull_writes_agents_md_when_scaffolding(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)
    assert not (bundle_dir / "AGENTS.md").exists()

    result = cli(["pull"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output

    assert (bundle_dir / "AGENTS.md").is_file()
    assert (bundle_dir / "docs" / "DSL.md").is_file()
    assert (bundle_dir / "docs" / "COOKBOOK.md").is_file()
